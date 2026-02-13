"""
System Executor
===============

Safely executes system commands with approval workflow and output capture.
Includes risk classification, timeout handling, and result parsing.
"""

import asyncio
import subprocess
import logging
import shlex
import re
from enum import Enum, auto
from typing import List, Dict, Any, Optional, Callable, Awaitable
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


class CommandRisk(Enum):
    """Risk level of a command."""
    LOW = auto()       # Read-only, informational
    MEDIUM = auto()    # Modifies system but reversible
    HIGH = auto()      # Potentially destructive, requires sudo
    CRITICAL = auto()  # Destructive, irreversible


@dataclass
class ExecutionResult:
    """Result of command execution."""
    command: str
    success: bool
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False
    error: Optional[str] = None
    parsed_data: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'command': self.command,
            'success': self.success,
            'exit_code': self.exit_code,
            'stdout': self.stdout[:1000] if self.stdout else '',
            'stderr': self.stderr[:500] if self.stderr else '',
            'duration_seconds': self.duration_seconds,
            'timed_out': self.timed_out,
            'error': self.error
        }


class SystemExecutor:
    """
    Safely executes system commands with approval workflow.

    Features:
    - LLM-driven risk classification for commands
    - Security guardrails for critical patterns (always blocked)
    - Approval workflow for risky operations
    - Timeout handling
    - Output capture and parsing
    - Sudo handling (requests user to run)

    ARCHITECTURE: LLM assesses command risk, RAICA executes with guardrails.
    Only truly dangerous patterns (fork bombs, rm -rf /) are hardcoded blocks.
    """

    # SECURITY GUARDRAILS: These patterns are ALWAYS blocked
    # This is not "LLM deciding" - this is a safety net that protects the system
    BLOCKED_PATTERNS = [
        r'rm\s+-rf?\s+/',        # rm -rf / (catastrophic)
        r'rm\s+-rf?\s+\*',       # rm -rf * in root
        r'>\s*/dev/sd',          # Overwrite disk
        r'dd\s+.*of=/dev/sd',    # dd to disk
        r'mkfs\.',               # Format filesystem
        r':()\{\s*:\|:&\s*\};:', # Fork bomb
        r'chmod\s+-R\s+777\s+/', # Chmod 777 recursively from root
    ]

    # Patterns that indicate interactive mode (will freeze agent)
    INTERACTIVE_PATTERNS = [
        r'^python[23]?\s*$',     # Python REPL (no script)
        r'^node\s*$',            # Node REPL
        r'^irb\s*$',             # Ruby REPL
        r'^ghci\s*$',            # Haskell REPL
        r'--interactive',        # Explicit interactive flag
        r'\s+-i\s*$',            # -i flag at end
    ]

    def __init__(
        self,
        llm_client: Optional[Any] = None,
        approval_callback: Optional[Callable[[str, str, CommandRisk], Awaitable[bool]]] = None,
        default_timeout: int = 120,
        allow_sudo: bool = False
    ):
        """
        Initialize the executor.

        Args:
            llm_client: LLM client for risk assessment
            approval_callback: Async function to get user approval
                Signature: async (command, description, risk) -> bool
            default_timeout: Default command timeout in seconds
            allow_sudo: Whether to allow sudo commands (with approval)
        """
        self.llm_client = llm_client
        self.approval_callback = approval_callback
        self.default_timeout = default_timeout
        self.allow_sudo = allow_sudo
        self._execution_history: List[ExecutionResult] = []
        self._risk_cache: Dict[str, CommandRisk] = {}  # Cache LLM risk assessments

    def is_interactive_command(self, command: str) -> bool:
        """
        Check if a command is interactive (would block waiting for input).

        Args:
            command: Command string to check

        Returns:
            True if command is interactive and should not be executed
        """
        command = command.strip()
        if not command:
            return False

        # Extract the base command
        try:
            parts = shlex.split(command)
        except ValueError:
            parts = command.split()

        if not parts:
            return False

        base_cmd = parts[0]

        # Handle sudo prefix
        if base_cmd == 'sudo' and len(parts) > 1:
            base_cmd = parts[1]
            parts = parts[1:]  # Remove sudo for further analysis

        # Extract just the command name from full path (e.g., /usr/games/gnuchess -> gnuchess)
        if '/' in base_cmd:
            base_cmd = base_cmd.split('/')[-1]

        # Special handling for shells - they're only interactive without args or scripts
        shell_commands = ['bash', 'sh', 'zsh', 'fish', 'csh', 'tcsh']
        if base_cmd in shell_commands:
            # bash/sh with -c flag is NOT interactive (runs command and exits)
            if '-c' in parts:
                return False
            # bash/sh with a script file is NOT interactive
            if len(parts) > 1 and not parts[1].startswith('-'):
                # Likely a script file argument
                return False
            # bash/sh with no meaningful args IS interactive
            if len(parts) == 1:
                return True
            # If only flags like -l, -i, it's likely interactive
            return True

        # Special handling for Python/Node - only interactive without script
        repl_commands = ['python', 'python3', 'ipython', 'node', 'irb', 'ghci']
        if base_cmd in repl_commands:
            # python/node with a script or -c is NOT interactive
            if len(parts) > 1:
                if '-c' in parts or '-m' in parts:
                    return False
                # Has a script argument
                for arg in parts[1:]:
                    if not arg.startswith('-'):
                        return False  # Likely a script file
            # Just 'python' with no args IS interactive
            return len(parts) == 1

        # Check against interactive patterns
        for pattern in self.INTERACTIVE_PATTERNS:
            if re.search(pattern, command):
                return True

        # Known interactive programs (editors, file managers, etc.)
        # These are not "LLM decisions" - they're functional guardrails
        # to prevent agent from hanging on programs that need TTY input
        known_interactive = {
            'vim', 'vi', 'nano', 'emacs', 'pico',
            'less', 'more', 'most',
            'top', 'htop',
            'man', 'info',
            'ssh', 'telnet',
        }
        if base_cmd in known_interactive:
            return True

        return False

    def classify_risk(self, command: str) -> CommandRisk:
        """
        Classify the risk level of a command using LLM assessment.

        ARCHITECTURE: LLM assesses risk, with security guardrails for critical patterns.

        Args:
            command: Command string to classify

        Returns:
            CommandRisk level
        """
        command = command.strip()

        # Security guardrail: Check for blocked patterns first (always)
        for pattern in self.BLOCKED_PATTERNS:
            if re.search(pattern, command):
                logger.warning(f"Command blocked by security guardrail: {command[:50]}")
                return CommandRisk.CRITICAL

        # Extract the base command
        try:
            parts = shlex.split(command) if command else []
        except ValueError:
            parts = command.split()

        if not parts:
            return CommandRisk.LOW

        base_cmd = parts[0]

        # Handle sudo prefix - sudo always elevates risk
        if base_cmd == 'sudo':
            if len(parts) > 1:
                # Assess the actual command after sudo
                inner_risk = self._assess_command_risk(parts[1:])
                # Sudo elevates risk by at least one level
                if inner_risk == CommandRisk.LOW:
                    return CommandRisk.MEDIUM
                elif inner_risk == CommandRisk.MEDIUM:
                    return CommandRisk.HIGH
                else:
                    return CommandRisk.CRITICAL

        return self._assess_command_risk(parts)

    def _assess_command_risk(self, parts: List[str]) -> CommandRisk:
        """Assess command risk using LLM or heuristics.

        Args:
            parts: Command parts (excluding sudo if present)

        Returns:
            CommandRisk level
        """
        if not parts:
            return CommandRisk.LOW

        command = ' '.join(parts)

        # Check cache first
        if command in self._risk_cache:
            return self._risk_cache[command]

        # Quick heuristics for common patterns (not hardcoded command lists)
        # These are structural checks, not command-specific
        if '|' in command or '>' in command or '>>' in command:
            # Piped/redirected commands need more scrutiny
            return CommandRisk.MEDIUM

        # If LLM available, use it for assessment
        if self.llm_client:
            risk = self._llm_assess_risk(command)
            self._risk_cache[command] = risk
            return risk

        # No LLM available - default to MEDIUM for safety
        logger.warning(f"No LLM for risk assessment, defaulting to MEDIUM: {command[:50]}")
        return CommandRisk.MEDIUM

    def _llm_assess_risk(self, command: str) -> CommandRisk:
        """Use LLM to assess command risk.

        Args:
            command: Command to assess

        Returns:
            CommandRisk level from LLM assessment
        """
        prompt = f"""Assess the risk level of this shell command.

COMMAND: {command}

Risk levels:
- LOW: Read-only commands, status checks, safe operations (ls, cat, echo, pwd, date, etc.)
- MEDIUM: Creates/modifies files in current directory, installs user packages, downloads files
- HIGH: System-wide changes, installs system packages, modifies permissions, starts services
- CRITICAL: Destructive operations, deletes files/directories, modifies system config, disk operations

Return ONLY a JSON response:
{{"risk": "LOW"}} or {{"risk": "MEDIUM"}} or {{"risk": "HIGH"}} or {{"risk": "CRITICAL"}}
"""
        try:
            response = self.llm_client.generate(prompt, max_tokens=50)
            content = response.content if hasattr(response, 'content') else str(response)
            content_lower = content.strip().lower()

            # Try to parse JSON using robust utility
            from ..utils.json_utils import extract_json_from_llm_response
            data = extract_json_from_llm_response(content)
            if data:
                risk_str = data.get('risk', 'MEDIUM').upper()
            else:
                # Fallback: look for risk level in text
                if 'critical' in content_lower:
                    risk_str = 'CRITICAL'
                elif 'high' in content_lower:
                    risk_str = 'HIGH'
                elif 'low' in content_lower:
                    risk_str = 'LOW'
                else:
                    risk_str = 'MEDIUM'

            risk_map = {
                'LOW': CommandRisk.LOW,
                'MEDIUM': CommandRisk.MEDIUM,
                'HIGH': CommandRisk.HIGH,
                'CRITICAL': CommandRisk.CRITICAL
            }
            return risk_map.get(risk_str, CommandRisk.MEDIUM)

        except Exception as e:
            logger.warning(f"LLM risk assessment failed: {e}")
            return CommandRisk.MEDIUM  # Safe default

    async def execute(
        self,
        command: str,
        description: str = "",
        timeout: Optional[int] = None,
        require_approval: bool = True,
        working_dir: Optional[str] = None,
        env: Optional[Dict[str, str]] = None
    ) -> ExecutionResult:
        """
        Execute a command safely.

        Args:
            command: Command to execute
            description: Human-readable description
            timeout: Command timeout (uses default if None)
            require_approval: Whether to require user approval
            working_dir: Working directory for command
            env: Environment variables

        Returns:
            ExecutionResult with output and status
        """
        risk = self.classify_risk(command)
        timeout = timeout or self.default_timeout

        logger.info(f"Executing command (risk={risk.name}): {command[:50]}...")

        # Block interactive commands - they would freeze the agent
        if self.is_interactive_command(command):
            logger.warning(f"Blocked interactive command: {command[:50]}")
            return ExecutionResult(
                command=command,
                success=False,
                exit_code=-1,
                stdout="",
                stderr="",
                duration_seconds=0,
                error=f"BLOCKED: This is an interactive command that requires user input. "
                      f"Please run it manually in your terminal: {command}"
            )

        # Check if command needs sudo
        needs_sudo = command.strip().startswith('sudo') or risk == CommandRisk.HIGH

        # Reject critical commands without explicit override
        if risk == CommandRisk.CRITICAL:
            if not require_approval:
                return ExecutionResult(
                    command=command,
                    success=False,
                    exit_code=-1,
                    stdout="",
                    stderr="",
                    duration_seconds=0,
                    error="CRITICAL risk command blocked. Requires explicit approval."
                )

        # Get approval if required
        if require_approval and risk in [CommandRisk.HIGH, CommandRisk.CRITICAL]:
            if self.approval_callback:
                approved = await self.approval_callback(command, description, risk)
                if not approved:
                    return ExecutionResult(
                        command=command,
                        success=False,
                        exit_code=-1,
                        stdout="",
                        stderr="",
                        duration_seconds=0,
                        error="Command not approved by user"
                    )
            else:
                # No approval callback, block high-risk commands
                return ExecutionResult(
                    command=command,
                    success=False,
                    exit_code=-1,
                    stdout="",
                    stderr="",
                    duration_seconds=0,
                    error=f"High-risk command requires approval callback"
                )

        # Handle sudo commands
        if needs_sudo and not self.allow_sudo:
            return ExecutionResult(
                command=command,
                success=False,
                exit_code=-1,
                stdout="",
                stderr="",
                duration_seconds=0,
                error="Sudo commands not allowed. Please run manually with sudo privileges."
            )

        # Execute the command
        start_time = datetime.now()

        try:
            # Run command asynchronously
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir,
                env=env
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout
                )

                duration = (datetime.now() - start_time).total_seconds()

                result = ExecutionResult(
                    command=command,
                    success=process.returncode == 0,
                    exit_code=process.returncode or 0,
                    stdout=stdout.decode('utf-8', errors='replace'),
                    stderr=stderr.decode('utf-8', errors='replace'),
                    duration_seconds=duration
                )

            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                duration = (datetime.now() - start_time).total_seconds()

                result = ExecutionResult(
                    command=command,
                    success=False,
                    exit_code=-1,
                    stdout="",
                    stderr="",
                    duration_seconds=duration,
                    timed_out=True,
                    error=f"Command timed out after {timeout} seconds"
                )

        except Exception as e:
            duration = (datetime.now() - start_time).total_seconds()
            result = ExecutionResult(
                command=command,
                success=False,
                exit_code=-1,
                stdout="",
                stderr="",
                duration_seconds=duration,
                error=str(e)
            )

        # Store in history
        self._execution_history.append(result)

        return result

    async def execute_multiple(
        self,
        commands: List[str],
        description: str = "",
        stop_on_failure: bool = True,
        require_approval: bool = True
    ) -> List[ExecutionResult]:
        """
        Execute multiple commands in sequence.

        Args:
            commands: List of commands to execute
            description: Description for approval
            stop_on_failure: Stop if any command fails
            require_approval: Require approval for high-risk commands

        Returns:
            List of ExecutionResults
        """
        results = []

        for i, command in enumerate(commands):
            logger.info(f"Executing command {i+1}/{len(commands)}: {command[:50]}...")

            result = await self.execute(
                command,
                description=f"{description} (step {i+1}/{len(commands)})",
                require_approval=require_approval
            )

            results.append(result)

            if not result.success and stop_on_failure:
                logger.warning(f"Command failed, stopping: {result.error or result.stderr}")
                break

        return results

    def parse_version_output(self, output: str) -> Optional[str]:
        """Parse version string from command output."""
        # Common version patterns
        patterns = [
            r'(\d+\.\d+\.\d+(?:-\w+)?)',  # 1.2.3 or 1.2.3-beta
            r'version\s+(\d+\.\d+)',       # version 1.2
            r'v(\d+\.\d+\.\d+)',           # v1.2.3
        ]

        for pattern in patterns:
            match = re.search(pattern, output, re.IGNORECASE)
            if match:
                return match.group(1)

        return None

    def parse_status_output(self, output: str) -> Dict[str, Any]:
        """Parse systemctl status output."""
        status = {
            'active': False,
            'running': False,
            'enabled': False,
            'description': ''
        }

        if 'Active: active' in output:
            status['active'] = True
        if 'running' in output.lower():
            status['running'] = True
        if 'enabled' in output:
            status['enabled'] = True

        # Extract description
        desc_match = re.search(r'Description:\s*(.+)', output)
        if desc_match:
            status['description'] = desc_match.group(1).strip()

        return status

    def get_history(self) -> List[ExecutionResult]:
        """Get execution history."""
        return self._execution_history.copy()

    def clear_history(self) -> None:
        """Clear execution history."""
        self._execution_history.clear()

    def get_summary(self) -> Dict[str, Any]:
        """Get summary of execution history."""
        if not self._execution_history:
            return {'total': 0, 'successful': 0, 'failed': 0}

        successful = sum(1 for r in self._execution_history if r.success)
        failed = len(self._execution_history) - successful

        return {
            'total': len(self._execution_history),
            'successful': successful,
            'failed': failed,
            'total_duration': sum(r.duration_seconds for r in self._execution_history)
        }


class SudoHelper:
    """
    Helper for handling sudo operations safely.

    Instead of executing sudo commands directly (which would require password),
    this generates instructions for the user to run manually.
    """

    @staticmethod
    def generate_sudo_script(commands: List[str], script_name: str = "install.sh") -> str:
        """
        Generate a shell script that the user can run with sudo.

        Args:
            commands: List of commands to include
            script_name: Name for the script

        Returns:
            Script content
        """
        script_lines = [
            "#!/bin/bash",
            "# Auto-generated installation script",
            "# Run with: sudo bash " + script_name,
            "",
            "set -e  # Exit on error",
            "",
            "echo '=== Starting installation ==='",
            ""
        ]

        for cmd in commands:
            # Remove sudo prefix if present (script runs as root)
            if cmd.strip().startswith('sudo '):
                cmd = cmd.strip()[5:]

            script_lines.append(f"echo 'Running: {cmd}'")
            script_lines.append(cmd)
            script_lines.append("")

        script_lines.extend([
            "echo '=== Installation complete ==='",
            ""
        ])

        return "\n".join(script_lines)

    @staticmethod
    def get_sudo_instructions(commands: List[str]) -> str:
        """
        Generate instructions for running sudo commands manually.

        Args:
            commands: List of commands

        Returns:
            Human-readable instructions
        """
        lines = [
            "The following commands require sudo privileges.",
            "Please run them manually in a terminal:",
            ""
        ]

        for cmd in commands:
            lines.append(f"  $ {cmd}")

        lines.extend([
            "",
            "Or run them all at once:",
            f"  $ sudo bash -c '{' && '.join(commands)}'",
            ""
        ])

        return "\n".join(lines)
