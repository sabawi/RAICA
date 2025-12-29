#!/usr/bin/env python3
"""
Command Safety Classifier for Website Deployer Agent
=====================================================

Classifies SSH commands by safety level to prevent dangerous operations.

Safety Levels:
- READ_ONLY (0): Commands that only read data (ls, cat, grep)
- SAFE (1): Commands that make safe changes (mkdir, pip install)
- PRIVILEGED (2): Commands requiring elevated privileges (systemctl, database ops)
- DANGEROUS (3): Commands that can cause data loss (rm -rf, DROP DATABASE)

Author: Agentic-RAG Development Team
Version: 1.0.0
"""

import re
import logging
from enum import Enum
from typing import List, Tuple, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class CommandSafetyLevel(Enum):
    """Safety levels for SSH commands."""
    READ_ONLY = 0        # ls, cat, grep, ps
    SAFE = 1             # mkdir, pip install, cd
    PRIVILEGED = 2       # systemctl, apt install, database operations
    DANGEROUS = 3        # rm -rf, DROP DATABASE, passwd


@dataclass
class CommandClassification:
    """Result of command safety classification."""
    command: str
    safety_level: CommandSafetyLevel
    matched_pattern: Optional[str] = None
    reason: Optional[str] = None
    requires_sudo: bool = False


class CommandSafetyClassifier:
    """
    Classifies commands by safety level using pattern matching.

    Uses regex patterns to identify command types and assign
    appropriate safety levels.
    """

    # Safety pattern definitions
    PATTERNS = {
        CommandSafetyLevel.READ_ONLY: [
            # File system read operations
            (r'^ls\s', "List directory contents"),
            (r'^cat\s', "Display file contents"),
            (r'^head\s', "Display file head"),
            (r'^tail\s', "Display file tail"),
            (r'^less\s', "View file with pager"),
            (r'^more\s', "View file with pager"),
            (r'^grep\s', "Search file contents"),
            (r'^find\s', "Find files"),
            (r'^locate\s', "Locate files"),

            # System information
            (r'^df\s', "Show disk usage"),
            (r'^du\s', "Show directory usage"),
            (r'^free\s', "Show memory usage"),
            (r'^ps\s', "List processes"),
            (r'^top$', "Monitor processes"),
            (r'^htop$', "Monitor processes"),
            (r'^uptime$', "Show system uptime"),
            (r'^whoami$', "Show current user"),
            (r'^pwd$', "Print working directory"),
            (r'^date$', "Show current date/time"),
            (r'^hostname$', "Show hostname"),
            (r'^uname\s', "Show system information"),

            # Version checks (READ_ONLY operations)
            (r'.*--version$', "Check version"),
            (r'.*-v$', "Check version"),
            (r'.*-V$', "Check version"),

            # Service status checks
            (r'^systemctl\s+status', "Check service status"),
            (r'^systemctl\s+is-active', "Check if service is active"),
            (r'^systemctl\s+is-enabled', "Check if service is enabled"),

            # Log viewing
            (r'^journalctl\s', "View system logs"),

            # Network information
            (r'^ping\s', "Ping host"),
            (r'^netstat\s', "Show network connections"),
            (r'^ss\s', "Show sockets"),
            (r'^curl\s+-I', "Check HTTP headers"),
            (r'^wget\s+--spider', "Check URL"),

            # Test commands
            (r'^echo\s', "Print message"),
            (r'^test\s', "Test condition"),
            (r'^\[.*\]$', "Test condition"),
        ],

        CommandSafetyLevel.SAFE: [
            # Directory operations
            (r'^mkdir\s+(?!.*-p\s*/)', "Create directory"),  # Exclude mkdir -p /
            (r'^cd\s', "Change directory"),
            (r'^touch\s', "Create empty file"),

            # File operations (in /tmp or /var/www)
            (r'^cp\s+.*(/tmp/|/var/www/)', "Copy files to safe location"),
            (r'^mv\s+.*(/tmp/|/var/www/)', "Move files to safe location"),

            # Python package management
            (r'^pip\s+install', "Install Python package"),
            (r'^pip3\s+install', "Install Python package"),
            (r'^python.*-m\s+venv', "Create virtual environment"),
            (r'^source\s+.*venv/bin/activate', "Activate virtual environment"),

            # Git operations
            (r'^git\s+clone', "Clone git repository"),
            (r'^git\s+pull', "Pull git changes"),
            (r'^git\s+fetch', "Fetch git changes"),
            (r'^git\s+status', "Check git status"),
            (r'^git\s+log', "View git log"),
            (r'^git\s+diff', "View git diff"),

            # Archive extraction (to safe locations)
            (r'^tar\s+.*(/tmp/|/var/www/)', "Extract archive to safe location"),
            (r'^unzip\s+.*(/tmp/|/var/www/)', "Extract zip to safe location"),

            # File permissions (non-recursive, safe locations)
            (r'^chmod\s+[0-7]{3}\s+(/var/www/|/tmp/)', "Change file permissions"),
            (r'^chown\s+.*(/var/www/|/tmp/)', "Change file ownership"),
        ],

        CommandSafetyLevel.PRIVILEGED: [
            # Package management
            (r'^sudo\s+apt\s+update$', "Update package lists"),
            (r'^sudo\s+apt\s+install', "Install system package"),
            (r'^sudo\s+apt\s+upgrade', "Upgrade packages"),
            (r'^sudo\s+yum\s+install', "Install system package (yum)"),
            (r'^sudo\s+dnf\s+install', "Install system package (dnf)"),

            # Service management
            (r'^sudo\s+systemctl\s+start', "Start system service"),
            (r'^sudo\s+systemctl\s+stop', "Stop system service"),
            (r'^sudo\s+systemctl\s+restart', "Restart system service"),
            (r'^sudo\s+systemctl\s+reload', "Reload system service"),
            (r'^sudo\s+systemctl\s+enable', "Enable system service"),
            (r'^sudo\s+systemctl\s+disable', "Disable system service"),
            (r'^sudo\s+systemctl\s+daemon-reload', "Reload systemd configuration"),

            # Nginx operations
            (r'^sudo\s+nginx\s+-t', "Test nginx configuration"),
            (r'^sudo\s+systemctl\s+(reload|restart)\s+nginx', "Reload/restart nginx"),

            # Database operations
            (r'^sudo\s+-u\s+postgres\s+psql\s+-c\s+"CREATE\s+USER', "Create PostgreSQL user"),
            (r'^sudo\s+-u\s+postgres\s+psql\s+-c\s+"CREATE\s+DATABASE', "Create PostgreSQL database"),
            (r'^sudo\s+-u\s+postgres\s+psql\s+-c\s+"GRANT', "Grant database privileges"),
            (r'^sudo\s+-u\s+postgres\s+psql\s+-c\s+"ALTER', "Alter database"),

            # SSL certificate operations
            (r'^sudo\s+certbot\s+', "Obtain/manage SSL certificate"),

            # File system operations with sudo
            (r'^sudo\s+mkdir\s+', "Create directory with sudo"),
            (r'^sudo\s+chown\s+', "Change ownership with sudo"),
            (r'^sudo\s+chmod\s+', "Change permissions with sudo"),
            (r'^sudo\s+mv\s+(/tmp/.*)\s+(/etc/|/var/)', "Move config files"),
            (r'^sudo\s+cp\s+', "Copy files with sudo"),
            (r'^sudo\s+ln\s+-s', "Create symbolic link"),

            # Application migrations
            (r'alembic\s+upgrade\s+head', "Run database migrations"),
        ],

        CommandSafetyLevel.DANGEROUS: [
            # File deletion
            (r'^rm\s+-rf', "Recursive force delete"),
            (r'^sudo\s+rm\s+-rf', "Recursive force delete with sudo"),
            (r'^rm\s+.*(/etc/|/var/|/usr/)', "Delete system files"),

            # Database destruction
            (r'DROP\s+DATABASE', "Drop database"),
            (r'DROP\s+TABLE', "Drop table"),
            (r'TRUNCATE\s+TABLE', "Truncate table"),
            (r'DELETE\s+FROM\s+(?!.*WHERE)', "Delete without WHERE clause"),

            # User management
            (r'^sudo\s+passwd', "Change password"),
            (r'^sudo\s+userdel', "Delete user"),
            (r'^sudo\s+groupdel', "Delete group"),

            # System modification
            (r'^sudo\s+reboot', "Reboot system"),
            (r'^sudo\s+shutdown', "Shutdown system"),
            (r'^sudo\s+init\s+', "Change runlevel"),

            # Firewall changes
            (r'^sudo\s+iptables\s+-F', "Flush firewall rules"),
            (r'^sudo\s+ufw\s+disable', "Disable firewall"),

            # Package removal
            (r'^sudo\s+apt\s+remove', "Remove package"),
            (r'^sudo\s+apt\s+purge', "Purge package"),

            # Disk operations
            (r'^sudo\s+fdisk', "Partition disk"),
            (r'^sudo\s+mkfs', "Format filesystem"),
            (r'^sudo\s+dd\s+', "Disk operations"),

            # Service disable/mask
            (r'^sudo\s+systemctl\s+mask', "Mask service"),
        ],
    }

    @classmethod
    def classify(cls, command: str) -> CommandClassification:
        """
        Classify a command by safety level.

        Args:
            command: Shell command string

        Returns:
            CommandClassification with safety level and metadata
        """
        command_stripped = command.strip()
        command_lower = command_stripped.lower()

        # Check if command requires sudo
        requires_sudo = command_lower.startswith('sudo ')

        # Try to match patterns in order of danger (most dangerous first)
        for level in [
            CommandSafetyLevel.DANGEROUS,
            CommandSafetyLevel.PRIVILEGED,
            CommandSafetyLevel.SAFE,
            CommandSafetyLevel.READ_ONLY
        ]:
            for pattern, reason in cls.PATTERNS[level]:
                if re.match(pattern, command_lower):
                    logger.debug(f"Command matched {level.name}: {command}")
                    return CommandClassification(
                        command=command_stripped,
                        safety_level=level,
                        matched_pattern=pattern,
                        reason=reason,
                        requires_sudo=requires_sudo
                    )

        # If no pattern matched, default to PRIVILEGED (conservative)
        logger.warning(f"⚠️ Unknown command pattern, defaulting to PRIVILEGED: {command}")
        return CommandClassification(
            command=command_stripped,
            safety_level=CommandSafetyLevel.PRIVILEGED,
            matched_pattern=None,
            reason="Unknown command - defaulting to privileged for safety",
            requires_sudo=requires_sudo
        )

    @classmethod
    def is_dangerous(cls, command: str) -> bool:
        """
        Check if a command is dangerous.

        Args:
            command: Shell command string

        Returns:
            True if command is dangerous, False otherwise
        """
        classification = cls.classify(command)
        return classification.safety_level == CommandSafetyLevel.DANGEROUS

    @classmethod
    def requires_approval(cls, command: str) -> bool:
        """
        Check if a command requires user approval.

        Args:
            command: Shell command string

        Returns:
            True if command requires approval (PRIVILEGED or DANGEROUS)
        """
        classification = cls.classify(command)
        return classification.safety_level in [
            CommandSafetyLevel.PRIVILEGED,
            CommandSafetyLevel.DANGEROUS
        ]

    @classmethod
    def get_approval_level(cls, command: str) -> str:
        """
        Get the approval level required for a command.

        Args:
            command: Shell command string

        Returns:
            Approval level string: "none", "confirm", "explicit"
        """
        classification = cls.classify(command)

        if classification.safety_level in [CommandSafetyLevel.READ_ONLY, CommandSafetyLevel.SAFE]:
            return "none"
        elif classification.safety_level == CommandSafetyLevel.PRIVILEGED:
            return "confirm"
        else:  # DANGEROUS
            return "explicit"
