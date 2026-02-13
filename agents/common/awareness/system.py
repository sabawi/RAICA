"""
Awareness System
================

Coordinator for all awareness components.
Initialized at agent startup to detect capabilities before any requests.

Components:
- SystemProfile: OS, tools, package managers detection
- UserProfile: User preferences and patterns
- EnvironmentState: Runtime environment state
"""

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from .system_profile import SystemProfile
from .user_profile import UserProfile
from .environment_state import EnvironmentState

logger = logging.getLogger(__name__)


class AwarenessSystem:
    """
    Coordinates system awareness - INITIALIZED AT AGENT STARTUP.

    This system provides the agent with awareness of:
    - System capabilities (OS, tools, package managers)
    - User preferences and patterns
    - Current runtime environment state

    All detection happens at initialization, with environment state
    refreshed on-demand when switching directories.
    """

    def __init__(
        self,
        user_home: Optional[Path] = None,
        auto_initialize: bool = True
    ):
        """
        Initialize the AwarenessSystem.

        Args:
            user_home: User home directory. Defaults to Path.home()
            auto_initialize: If True, run full initialization immediately
        """
        self.user_home = user_home or Path.home()
        self.profiles_dir = self.user_home / ".raica" / "profiles"

        # Initialize components
        self.system_profile = SystemProfile(profiles_dir=self.profiles_dir)
        self.user_profile = UserProfile(profiles_dir=self.profiles_dir)
        self.environment = EnvironmentState()

        self._initialized = False

        if auto_initialize:
            self.initialize()

    def initialize(self, force_refresh: bool = False) -> None:
        """
        Run full system initialization.

        This detects system capabilities, loads user preferences,
        and captures current environment state.

        Args:
            force_refresh: If True, bypass caches and re-detect everything
        """
        logger.info("Initializing Awareness System...")

        # Ensure profiles directory exists
        self.profiles_dir.mkdir(parents=True, exist_ok=True)

        # Detect system capabilities (cached for 24 hours by default)
        self.system_profile.detect(force=force_refresh)
        logger.info(f"System: {self.system_profile.os_name} {self.system_profile.distro or ''}")

        # Load user preferences
        self.user_profile.load()
        self.user_profile.record_session_start()
        logger.info(f"User profile loaded (sessions: {self.user_profile.total_sessions})")

        # Capture current environment
        self.environment.refresh()
        if self.environment.active_project:
            logger.info(f"Active project: {self.environment.active_project.name}")

        self._initialized = True
        logger.info("Awareness System initialized")

    def refresh_environment(self, directory: Optional[str] = None) -> None:
        """
        Refresh environment state for a directory.

        Call this when switching directories or projects.

        Args:
            directory: Directory to refresh for. Defaults to current directory.
        """
        self.environment.refresh(directory)

        # Track frequently used directories
        if directory:
            self.user_profile.add_frequent_directory(directory)

        # Track recent projects
        if self.environment.active_project:
            self.user_profile.add_recent_project(
                self.environment.active_project.path,
                self.environment.active_project.name
            )

    def check_capability(self, tool_name: str) -> bool:
        """
        Check if a tool is available on the system.

        Args:
            tool_name: Name of the tool to check (e.g., 'git', 'docker')

        Returns:
            True if the tool is available
        """
        return self.system_profile.is_tool_available(tool_name)

    def get_install_command(self, package: str) -> Optional[str]:
        """
        Get the appropriate install command for a package.

        Args:
            package: Package name to install

        Returns:
            Install command string (e.g., 'sudo apt install package')
        """
        return self.system_profile.get_install_command(package)

    def should_auto_approve(self, action_type: str) -> bool:
        """
        Check if an action type should be auto-approved.

        Args:
            action_type: Type of action (e.g., 'file_create', 'git_commit')

        Returns:
            True if the action should be auto-approved
        """
        return self.user_profile.should_auto_approve(action_type)

    def record_approval(self, action_type: str) -> None:
        """Record that an action was approved."""
        self.user_profile.record_approval(action_type)

    def observe_pattern(self, name: str, value: Any) -> None:
        """
        Record an observed working pattern.

        Args:
            name: Pattern name (e.g., 'preferred_test_runner')
            value: Observed value (e.g., 'pytest')
        """
        self.user_profile.observe_pattern(name, value)

    def get_pattern(self, name: str, default: Any = None) -> Any:
        """
        Get a working pattern value if confidence is high enough.

        Args:
            name: Pattern name
            default: Default value if pattern not found or low confidence

        Returns:
            Pattern value or default
        """
        return self.user_profile.get_pattern(name, default)

    def get_capabilities_summary(self) -> str:
        """
        Get a summary of system capabilities for LLM prompts.

        Returns:
            Multi-line string summarizing system, user, and environment state
        """
        sections = []

        # System capabilities
        system_summary = self.system_profile.get_summary()
        if system_summary:
            sections.append("=== System ===\n" + system_summary)

        # User preferences
        user_summary = self.user_profile.get_summary()
        if user_summary:
            sections.append("=== User ===\n" + user_summary)

        # Environment state
        env_summary = self.environment.get_summary()
        if env_summary:
            sections.append("=== Environment ===\n" + env_summary)

        return "\n\n".join(sections)

    def get_context_for_llm(self) -> Dict[str, Any]:
        """
        Get structured context data for LLM prompts.

        Returns:
            Dictionary with system, user, and environment context
        """
        return {
            'system': {
                'os': self.system_profile.os_name,
                'distro': self.system_profile.distro,
                'architecture': self.system_profile.architecture,
                'shell': self.system_profile.shell,
                'package_managers': self.system_profile.package_managers,
                'python_version': self.system_profile.python_version,
                'node_version': self.system_profile.node_version,
            },
            'user': {
                'sessions': self.user_profile.total_sessions,
                'tasks_completed': self.user_profile.total_tasks_completed,
                'verbosity': self.user_profile.preferred_verbosity,
                'use_emojis': self.user_profile.use_emojis,
            },
            'environment': {
                'cwd': self.environment.cwd,
                'git_branch': self.environment.git_state.current_branch if self.environment.git_state.is_repo else None,
                'has_uncommitted': self.environment.git_state.has_uncommitted_changes,
                'venv_active': self.environment.venv_state.is_active,
                'project_name': self.environment.active_project.name if self.environment.active_project else None,
                'project_type': self.environment.active_project.project_type if self.environment.active_project else None,
            }
        }

    def save(self) -> None:
        """Save all persistent data."""
        self.user_profile.save()
        # System profile auto-saves after detection

    def to_dict(self) -> Dict[str, Any]:
        """Export full state to dictionary."""
        return {
            'initialized': self._initialized,
            'system_profile': self.system_profile.to_dict(),
            'user_profile': self.user_profile.to_dict(),
            'environment': self.environment.to_dict(),
        }

    @property
    def is_initialized(self) -> bool:
        """Check if the system has been initialized."""
        return self._initialized
