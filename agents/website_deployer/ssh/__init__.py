"""
SSH Module for Website Deployer Agent
======================================

Provides secure SSH connection management, command execution,
and safety classification.

Components:
- SSHConnectionManager: Manage SSH connections
- SafeSSHExecutor: Execute commands with safety checks
- CommandSafetyClassifier: Classify command safety levels

Author: RAICA Development Team
Version: 1.0.0
"""

from .connection import SSHConnectionManager, SSHCredentials
from .safety import CommandSafetyClassifier, CommandSafetyLevel, CommandClassification
from .executor import SafeSSHExecutor, SSHCommand, CommandResult

__all__ = [
    "SSHConnectionManager",
    "SSHCredentials",
    "CommandSafetyClassifier",
    "CommandSafetyLevel",
    "CommandClassification",
    "SafeSSHExecutor",
    "SSHCommand",
    "CommandResult",
]
