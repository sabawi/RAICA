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
    - Risk classification for commands
    - Approval workflow for risky operations
    - Timeout handling
    - Output capture and parsing
    - Sudo handling (requests user to run)
    """

    # Commands that are always safe (read-only)
    SAFE_COMMANDS = [
        'cat', 'ls', 'pwd', 'echo', 'which', 'whereis', 'type',
        'head', 'tail', 'grep', 'find', 'locate', 'wc',
        'uname', 'hostname', 'whoami', 'id', 'groups',
        'date', 'uptime', 'free', 'df', 'du', 'ps', 'top',
        'env', 'printenv', 'lsb_release', 'lscpu', 'lsmem'
    ]

    # Commands requiring medium caution
    MEDIUM_RISK_COMMANDS = [
        'mkdir', 'touch', 'cp', 'mv', 'ln',
        'pip', 'npm', 'yarn', 'cargo', 'go',
        'git', 'curl', 'wget', 'tar', 'unzip'
    ]

    # High risk commands requiring sudo
    HIGH_RISK_COMMANDS = [
        'apt', 'apt-get', 'yum', 'dnf', 'pacman', 'brew',
        'systemctl', 'service', 'init',
        'chmod', 'chown', 'chgrp',
        'mount', 'umount',
        'useradd', 'userdel', 'usermod', 'groupadd',
        'iptables', 'firewall-cmd', 'ufw'
    ]

    # Critical/destructive commands - require explicit confirmation
    CRITICAL_COMMANDS = [
        'rm', 'rmdir', 'dd', 'mkfs', 'fdisk', 'parted',
        'shutdown', 'reboot', 'poweroff', 'halt',
        'kill', 'killall', 'pkill',
        'truncate', 'shred'
    ]

    # Patterns that indicate destructive intent
    DESTRUCTIVE_PATTERNS = [
        r'rm\s+-rf?\s+/',        # rm -rf /
        r'rm\s+-rf?\s+\*',       # rm -rf *
        r'>\s*/dev/',            # Redirect to device
        r'dd\s+.*of=/dev/',      # dd to device
        r'mkfs',                 # Format filesystem
        r':()\{.*\}',            # Fork bomb pattern
    ]

    def __init__(
        self,
        approval_callback: Optional[Callable[[str, str, CommandRisk], Awaitable[bool]]] = None,
        default_timeout: int = 120,
        allow_sudo: bool = False
    ):
        """
        Initialize the executor.

        Args:
            approval_callback: Async function to get user approval
                Signature: async (command, description, risk) -> bool
            default_timeout: Default command timeout in seconds
            allow_sudo: Whether to allow sudo commands (with approval)
        """
        self.approval_callback = approval_callback
        self.default_timeout = default_timeout
        self.allow_sudo = allow_sudo
        self._execution_history: List[ExecutionResult] = []

    def classify_risk(self, command: str) -> CommandRisk:
        """
        Classify the risk level of a command.

        Args:
            command: Command string to classify

        Returns:
            CommandRisk level
        """
        command = command.strip()

        # Check for destructive patterns first
        for pattern in self.DESTRUCTIVE_PATTERNS:
            if re.search(pattern, command):
                return CommandRisk.CRITICAL

        # Extract the base command
        parts = shlex.split(command) if command else []
        if not parts:
            return CommandRisk.LOW

        base_cmd = parts[0]

        # Handle sudo prefix
        if base_cmd == 'sudo':
            if len(parts) > 1:
                base_cmd = parts[1]
                # Sudo automatically makes it at least HIGH risk
                if base_cmd in self.CRITICAL_COMMANDS:
                    return CommandRisk.CRITICAL
                return CommandRisk.HIGH

        # Check against command lists
        if base_cmd in self.CRITICAL_COMMANDS:
            return CommandRisk.CRITICAL
        if base_cmd in self.HIGH_RISK_COMMANDS:
            return CommandRisk.HIGH
        if base_cmd in self.MEDIUM_RISK_COMMANDS:
            return CommandRisk.MEDIUM
        if base_cmd in self.SAFE_COMMANDS:
            return CommandRisk.LOW

        # Check for pipes and redirects
        if '|' in command or '>' in command or '>>' in command:
            # Piped commands need more scrutiny
            return CommandRisk.MEDIUM

        # Default to medium for unknown commands
        return CommandRisk.MEDIUM

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
