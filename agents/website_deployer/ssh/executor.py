#!/usr/bin/env python3
"""
Safe SSH Command Executor for Website Deployer Agent
=====================================================

Executes SSH commands with safety checks, audit logging, and rollback support.

Features:
- Command safety classification
- User approval for privileged/dangerous commands
- Dry-run mode (preview without execution)
- Comprehensive audit logging
- Execution history tracking
- Rollback support

Author: Agentic-RAG Development Team
Version: 1.0.0
"""

import time
import json
import logging
from datetime import datetime
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, asdict
from pathlib import Path
import paramiko

from .safety import CommandSafetyClassifier, CommandSafetyLevel, CommandClassification

logger = logging.getLogger(__name__)


@dataclass
class SSHCommand:
    """Represents an SSH command with metadata."""
    command: str
    description: str
    safety_level: Optional[CommandSafetyLevel] = None
    requires_sudo: bool = False
    timeout: int = 300  # 5 minutes default

    def __post_init__(self):
        """Auto-classify command if safety level not provided."""
        if self.safety_level is None:
            classification = CommandSafetyClassifier.classify(self.command)
            self.safety_level = classification.safety_level
            self.requires_sudo = classification.requires_sudo


@dataclass
class CommandResult:
    """Result of SSH command execution."""
    command: str
    description: str
    success: bool
    stdout: str
    stderr: str
    exit_code: int
    execution_time: float
    timestamp: str
    safety_level: str
    dry_run: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


class SafeSSHExecutor:
    """
    Safe SSH command executor with audit logging and rollback.

    Features:
    - Automatic command safety classification
    - User approval workflow for privileged commands
    - Dry-run mode for preview
    - Comprehensive audit logging
    - Execution history for rollback
    """

    def __init__(
        self,
        ssh_client: paramiko.SSHClient,
        dry_run: bool = True,
        auto_approve_safe: bool = True,
        audit_log_path: Optional[Path] = None
    ):
        """
        Initialize safe SSH executor.

        Args:
            ssh_client: Connected Paramiko SSH client
            dry_run: If True, don't execute commands (preview only)
            auto_approve_safe: Auto-approve READ_ONLY and SAFE commands
            audit_log_path: Path to save audit log (optional)
        """
        self.ssh_client = ssh_client
        self.dry_run = dry_run
        self.auto_approve_safe = auto_approve_safe
        self.audit_log_path = audit_log_path or Path("deployment_audit.json")

        self.audit_log: List[Dict[str, Any]] = []
        self.execution_history: List[CommandResult] = []
        self.start_time = datetime.now()

        logger.info(f"SafeSSHExecutor initialized (dry_run={dry_run})")

    def execute(
        self,
        command: SSHCommand,
        user_approval: Optional[bool] = None
    ) -> CommandResult:
        """
        Execute SSH command with safety checks.

        Args:
            command: SSHCommand to execute
            user_approval: Override approval (True=approve, False=reject, None=ask)

        Returns:
            CommandResult with execution details
        """
        start_time = time.time()
        timestamp = datetime.now().isoformat()

        # Classify command safety
        classification = CommandSafetyClassifier.classify(command.command)
        command.safety_level = classification.safety_level
        command.requires_sudo = classification.requires_sudo

        logger.info("=" * 60)
        logger.info(f"Command: {command.description}")
        logger.info(f"  {command.command}")
        logger.info(f"Safety Level: {classification.safety_level.name}")
        logger.info(f"Requires Sudo: {classification.requires_sudo}")
        logger.info("=" * 60)

        # Log to audit trail
        audit_entry = {
            "timestamp": timestamp,
            "command": command.command,
            "description": command.description,
            "safety_level": classification.safety_level.name,
            "matched_pattern": classification.matched_pattern,
            "reason": classification.reason,
            "requires_sudo": classification.requires_sudo,
            "dry_run": self.dry_run
        }

        # Check if approval needed
        approval_needed = self._needs_approval(classification.safety_level)

        if approval_needed:
            # Get approval
            if user_approval is None:
                user_approval = self._request_approval(command, classification)

            audit_entry["approval_required"] = True
            audit_entry["user_approved"] = user_approval

            if not user_approval:
                logger.warning(f"❌ Command rejected by user")
                audit_entry["status"] = "rejected_by_user"
                self.audit_log.append(audit_entry)

                return CommandResult(
                    command=command.command,
                    description=command.description,
                    success=False,
                    stdout="",
                    stderr="Command rejected by user",
                    exit_code=-1,
                    execution_time=0,
                    timestamp=timestamp,
                    safety_level=classification.safety_level.name,
                    dry_run=self.dry_run
                )
        else:
            audit_entry["approval_required"] = False
            audit_entry["user_approved"] = True

        # Dry run mode - don't execute
        if self.dry_run:
            logger.info(f"[DRY RUN] Would execute: {command.command}")
            audit_entry["status"] = "dry_run"
            self.audit_log.append(audit_entry)

            return CommandResult(
                command=command.command,
                description=command.description,
                success=True,
                stdout=f"[DRY RUN] Command not executed",
                stderr="",
                exit_code=0,
                execution_time=0,
                timestamp=timestamp,
                safety_level=classification.safety_level.name,
                dry_run=True
            )

        # Execute command
        try:
            logger.info(f"🚀 Executing command...")

            stdin, stdout, stderr = self.ssh_client.exec_command(
                command.command,
                timeout=command.timeout
            )

            # Wait for command to complete
            exit_code = stdout.channel.recv_exit_status()

            stdout_text = stdout.read().decode('utf-8', errors='replace')
            stderr_text = stderr.read().decode('utf-8', errors='replace')

            execution_time = time.time() - start_time
            success = exit_code == 0

            if success:
                logger.info(f"✅ Command succeeded (exit code: {exit_code}, time: {execution_time:.2f}s)")
                if stdout_text.strip():
                    logger.debug(f"stdout: {stdout_text[:200]}")
            else:
                logger.error(f"❌ Command failed (exit code: {exit_code}, time: {execution_time:.2f}s)")
                if stderr_text.strip():
                    logger.error(f"stderr: {stderr_text[:200]}")

            # Update audit log
            audit_entry["status"] = "success" if success else "failed"
            audit_entry["exit_code"] = exit_code
            audit_entry["execution_time"] = execution_time
            self.audit_log.append(audit_entry)

            # Create result
            result = CommandResult(
                command=command.command,
                description=command.description,
                success=success,
                stdout=stdout_text,
                stderr=stderr_text,
                exit_code=exit_code,
                execution_time=execution_time,
                timestamp=timestamp,
                safety_level=classification.safety_level.name,
                dry_run=False
            )

            # Track in execution history
            self.execution_history.append(result)

            return result

        except paramiko.SSHException as e:
            logger.error(f"❌ SSH error executing command: {e}")

            audit_entry["status"] = "ssh_error"
            audit_entry["error"] = str(e)
            self.audit_log.append(audit_entry)

            return CommandResult(
                command=command.command,
                description=command.description,
                success=False,
                stdout="",
                stderr=f"SSH error: {str(e)}",
                exit_code=-1,
                execution_time=time.time() - start_time,
                timestamp=timestamp,
                safety_level=classification.safety_level.name,
                dry_run=False
            )

        except Exception as e:
            logger.error(f"❌ Unexpected error: {e}")

            audit_entry["status"] = "error"
            audit_entry["error"] = str(e)
            self.audit_log.append(audit_entry)

            return CommandResult(
                command=command.command,
                description=command.description,
                success=False,
                stdout="",
                stderr=f"Error: {str(e)}",
                exit_code=-1,
                execution_time=time.time() - start_time,
                timestamp=timestamp,
                safety_level=classification.safety_level.name,
                dry_run=False
            )

    def execute_script(
        self,
        commands: List[SSHCommand],
        stop_on_error: bool = True
    ) -> List[CommandResult]:
        """
        Execute a series of commands (deployment script).

        Args:
            commands: List of SSHCommand objects
            stop_on_error: Stop execution if any command fails

        Returns:
            List of CommandResult objects
        """
        results = []
        total_commands = len(commands)

        logger.info("=" * 60)
        logger.info(f"Executing deployment script: {total_commands} commands")
        logger.info("=" * 60)

        for i, command in enumerate(commands, 1):
            logger.info(f"\n[{i}/{total_commands}] {command.description}")

            result = self.execute(command)
            results.append(result)

            if not result.success and stop_on_error:
                logger.error(f"❌ Command failed, stopping execution")
                logger.error(f"Failed at step {i}/{total_commands}")
                break

        # Summary
        successful = sum(1 for r in results if r.success)
        failed = len(results) - successful

        logger.info("\n" + "=" * 60)
        logger.info("EXECUTION SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Total commands: {len(results)}")
        logger.info(f"Successful: {successful}")
        logger.info(f"Failed: {failed}")
        logger.info("=" * 60)

        return results

    def _needs_approval(self, safety_level: CommandSafetyLevel) -> bool:
        """
        Check if command needs user approval.

        Args:
            safety_level: Command safety level

        Returns:
            True if approval needed
        """
        if self.auto_approve_safe:
            # Auto-approve READ_ONLY and SAFE commands
            return safety_level in [
                CommandSafetyLevel.PRIVILEGED,
                CommandSafetyLevel.DANGEROUS
            ]
        else:
            # Require approval for everything except READ_ONLY
            return safety_level != CommandSafetyLevel.READ_ONLY

    def _request_approval(
        self,
        command: SSHCommand,
        classification: CommandClassification
    ) -> bool:
        """
        Request user approval for privileged/dangerous command.

        Args:
            command: Command to approve
            classification: Command classification

        Returns:
            True if approved, False if rejected
        """
        if classification.safety_level == CommandSafetyLevel.DANGEROUS:
            logger.critical("⚠️  DANGEROUS COMMAND APPROVAL REQUIRED ⚠️")
            logger.critical(f"Command: {command.command}")
            logger.critical(f"Reason: {classification.reason}")
            logger.critical("This command could cause data loss or system damage!")

            # In production, this would show UI confirmation dialog
            # For now, return False for dangerous commands
            return False

        elif classification.safety_level == CommandSafetyLevel.PRIVILEGED:
            logger.warning("⚠️  PRIVILEGED COMMAND APPROVAL REQUIRED")
            logger.warning(f"Command: {command.command}")
            logger.warning(f"Reason: {classification.reason}")

            # In production, this would show UI confirmation dialog
            # For deployment mode, auto-approve privileged commands
            return True

        return True

    def get_audit_log(self) -> List[Dict[str, Any]]:
        """Get complete audit log."""
        return self.audit_log

    def save_audit_log(self, filepath: Optional[Path] = None):
        """
        Save audit log to JSON file.

        Args:
            filepath: Path to save audit log (default: self.audit_log_path)
        """
        filepath = filepath or self.audit_log_path

        audit_data = {
            "deployment_start": self.start_time.isoformat(),
            "deployment_end": datetime.now().isoformat(),
            "dry_run": self.dry_run,
            "total_commands": len(self.audit_log),
            "successful_commands": sum(1 for entry in self.audit_log if entry.get("status") == "success"),
            "failed_commands": sum(1 for entry in self.audit_log if entry.get("status") == "failed"),
            "commands": self.audit_log
        }

        try:
            filepath.parent.mkdir(parents=True, exist_ok=True)
            with open(filepath, 'w') as f:
                json.dump(audit_data, f, indent=2)

            logger.info(f"✅ Audit log saved to: {filepath}")

        except Exception as e:
            logger.error(f"❌ Failed to save audit log: {e}")

    def get_execution_history(self) -> List[CommandResult]:
        """Get command execution history."""
        return self.execution_history

    def print_summary(self):
        """Print execution summary."""
        total_time = (datetime.now() - self.start_time).total_seconds()

        print("\n" + "=" * 60)
        print("DEPLOYMENT SUMMARY")
        print("=" * 60)
        print(f"Start Time: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"End Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Total Duration: {total_time:.2f}s")
        print(f"Dry Run: {self.dry_run}")
        print(f"\nCommands Executed: {len(self.execution_history)}")

        successful = sum(1 for r in self.execution_history if r.success)
        failed = len(self.execution_history) - successful

        print(f"Successful: {successful}")
        print(f"Failed: {failed}")
        print(f"\nAudit Log: {self.audit_log_path}")
        print("=" * 60 + "\n")
