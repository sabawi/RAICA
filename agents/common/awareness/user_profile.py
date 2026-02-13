"""
User Profile
============

Tracks user preferences and patterns including:
- Approval preferences (auto-approve certain actions)
- Working patterns (preferred times, common directories)
- Communication preferences

Persisted to ~/.raica/profiles/user_profile.yaml
"""

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import yaml

logger = logging.getLogger(__name__)


class ApprovalLevel(Enum):
    """Levels of approval required for actions."""
    ALWAYS_ASK = "always_ask"
    ASK_FIRST_TIME = "ask_first_time"
    AUTO_APPROVE = "auto_approve"
    NEVER_ALLOW = "never_allow"


@dataclass
class ApprovalPreference:
    """A user's approval preference for an action type."""
    action_type: str
    level: ApprovalLevel
    last_approved: Optional[str] = None
    approved_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'action_type': self.action_type,
            'level': self.level.value,
            'last_approved': self.last_approved,
            'approved_count': self.approved_count
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ApprovalPreference':
        return cls(
            action_type=data.get('action_type', ''),
            level=ApprovalLevel(data.get('level', 'always_ask')),
            last_approved=data.get('last_approved'),
            approved_count=data.get('approved_count', 0)
        )


@dataclass
class WorkingPattern:
    """Detected working pattern of the user."""
    name: str
    value: Any
    confidence: float = 0.5
    last_observed: Optional[str] = None
    observation_count: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            'name': self.name,
            'value': self.value,
            'confidence': self.confidence,
            'last_observed': self.last_observed,
            'observation_count': self.observation_count
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'WorkingPattern':
        return cls(
            name=data.get('name', ''),
            value=data.get('value'),
            confidence=data.get('confidence', 0.5),
            last_observed=data.get('last_observed'),
            observation_count=data.get('observation_count', 1)
        )


class UserProfile:
    """
    Tracks user preferences and working patterns.
    Persists to ~/.raica/profiles/user_profile.yaml
    """

    PROFILE_FILE = "user_profile.yaml"

    # Default action types that can have approval preferences
    DEFAULT_ACTION_TYPES = [
        'file_create',
        'file_modify',
        'file_delete',
        'command_execute',
        'git_commit',
        'git_push',
        'package_install',
        'config_change',
        'test_run',
        'build_run',
    ]

    def __init__(self, profiles_dir: Optional[Path] = None):
        """
        Initialize UserProfile.

        Args:
            profiles_dir: Directory for profile storage. Defaults to ~/.raica/profiles/
        """
        self.profiles_dir = profiles_dir or (Path.home() / ".raica" / "profiles")
        self.profile_file = self.profiles_dir / self.PROFILE_FILE

        # User preferences
        self.approval_preferences: Dict[str, ApprovalPreference] = {}
        self.working_patterns: Dict[str, WorkingPattern] = {}

        # Communication preferences
        self.preferred_verbosity: str = "normal"  # minimal, normal, verbose
        self.preferred_language: str = "en"
        self.use_emojis: bool = False
        self.show_explanations: bool = True

        # Common directories and projects
        self.frequent_directories: List[str] = []
        self.favorite_projects: List[str] = []
        self.recent_projects: List[Dict[str, Any]] = []

        # Session tracking
        self.total_sessions: int = 0
        self.total_tasks_completed: int = 0
        self.first_seen: Optional[str] = None
        self.last_seen: Optional[str] = None

        # Custom preferences (user-defined)
        self.custom_preferences: Dict[str, Any] = {}

    def load(self) -> bool:
        """Load profile from disk."""
        if not self.profile_file.exists():
            logger.info("No user profile found, using defaults")
            return False

        try:
            with open(self.profile_file, 'r') as f:
                data = yaml.safe_load(f)

            if not data:
                return False

            self._from_dict(data)
            logger.info("Loaded user profile")
            return True

        except Exception as e:
            logger.warning(f"Failed to load user profile: {e}")
            return False

    def save(self) -> bool:
        """Save profile to disk."""
        try:
            self.profiles_dir.mkdir(parents=True, exist_ok=True)
            with open(self.profile_file, 'w') as f:
                yaml.dump(self.to_dict(), f, default_flow_style=False)
            logger.debug("Saved user profile")
            return True
        except Exception as e:
            logger.warning(f"Failed to save user profile: {e}")
            return False

    def record_session_start(self) -> None:
        """Record the start of a new session."""
        now = datetime.now().isoformat()

        if not self.first_seen:
            self.first_seen = now

        self.last_seen = now
        self.total_sessions += 1
        self.save()

    def record_task_completed(self) -> None:
        """Record a completed task."""
        self.total_tasks_completed += 1
        self.last_seen = datetime.now().isoformat()

    def add_recent_project(self, project_path: str, project_name: Optional[str] = None) -> None:
        """Add a project to recent projects list."""
        project_path = str(Path(project_path).resolve())

        # Remove if already exists
        self.recent_projects = [
            p for p in self.recent_projects
            if p.get('path') != project_path
        ]

        # Add to front
        self.recent_projects.insert(0, {
            'path': project_path,
            'name': project_name or Path(project_path).name,
            'last_accessed': datetime.now().isoformat()
        })

        # Keep only last 20
        self.recent_projects = self.recent_projects[:20]

    def add_frequent_directory(self, directory: str) -> None:
        """Track a frequently used directory."""
        directory = str(Path(directory).resolve())

        if directory not in self.frequent_directories:
            self.frequent_directories.append(directory)
            # Keep only last 50
            self.frequent_directories = self.frequent_directories[-50:]

    def get_approval_preference(self, action_type: str) -> ApprovalPreference:
        """Get approval preference for an action type."""
        if action_type not in self.approval_preferences:
            # Default to always ask
            self.approval_preferences[action_type] = ApprovalPreference(
                action_type=action_type,
                level=ApprovalLevel.ALWAYS_ASK
            )
        return self.approval_preferences[action_type]

    def set_approval_preference(
        self,
        action_type: str,
        level: ApprovalLevel
    ) -> None:
        """Set approval preference for an action type."""
        self.approval_preferences[action_type] = ApprovalPreference(
            action_type=action_type,
            level=level,
            last_approved=datetime.now().isoformat() if level != ApprovalLevel.ALWAYS_ASK else None,
            approved_count=self.approval_preferences.get(action_type, ApprovalPreference(action_type, ApprovalLevel.ALWAYS_ASK)).approved_count
        )
        self.save()

    def record_approval(self, action_type: str) -> None:
        """Record that an action was approved."""
        pref = self.get_approval_preference(action_type)
        pref.last_approved = datetime.now().isoformat()
        pref.approved_count += 1
        self.approval_preferences[action_type] = pref

    def should_auto_approve(self, action_type: str) -> bool:
        """Check if an action type should be auto-approved."""
        pref = self.get_approval_preference(action_type)

        if pref.level == ApprovalLevel.AUTO_APPROVE:
            return True
        elif pref.level == ApprovalLevel.NEVER_ALLOW:
            return False
        elif pref.level == ApprovalLevel.ASK_FIRST_TIME:
            # Auto-approve if previously approved
            return pref.approved_count > 0
        else:  # ALWAYS_ASK
            return False

    def observe_pattern(self, name: str, value: Any) -> None:
        """
        Record an observed working pattern.
        Patterns gain confidence with repeated observations.
        """
        now = datetime.now().isoformat()

        if name in self.working_patterns:
            pattern = self.working_patterns[name]
            if pattern.value == value:
                # Same value observed again - increase confidence
                pattern.observation_count += 1
                pattern.confidence = min(1.0, pattern.confidence + 0.1)
            else:
                # Different value - decrease confidence and update
                pattern.confidence = max(0.1, pattern.confidence - 0.2)
                if pattern.confidence < 0.3:
                    pattern.value = value
                    pattern.observation_count = 1
            pattern.last_observed = now
        else:
            # New pattern
            self.working_patterns[name] = WorkingPattern(
                name=name,
                value=value,
                confidence=0.5,
                last_observed=now,
                observation_count=1
            )

    def get_pattern(self, name: str, default: Any = None) -> Any:
        """Get a working pattern value if confidence is high enough."""
        if name in self.working_patterns:
            pattern = self.working_patterns[name]
            if pattern.confidence >= 0.5:
                return pattern.value
        return default

    def set_preference(self, key: str, value: Any) -> None:
        """Set a custom preference."""
        self.custom_preferences[key] = value
        self.save()

    def get_preference(self, key: str, default: Any = None) -> Any:
        """Get a custom preference."""
        return self.custom_preferences.get(key, default)

    def get_summary(self) -> str:
        """Get a human-readable summary for LLM prompts."""
        lines = []

        # Session info
        if self.total_sessions > 0:
            lines.append(f"Sessions: {self.total_sessions}, Tasks completed: {self.total_tasks_completed}")

        # Communication preferences
        if self.preferred_verbosity != "normal":
            lines.append(f"Verbosity: {self.preferred_verbosity}")
        if self.use_emojis:
            lines.append("Emojis: enabled")

        # High-confidence patterns
        confident_patterns = [
            p for p in self.working_patterns.values()
            if p.confidence >= 0.7
        ]
        if confident_patterns:
            pattern_strs = [f"{p.name}={p.value}" for p in confident_patterns[:5]]
            lines.append(f"Patterns: {', '.join(pattern_strs)}")

        # Auto-approved actions
        auto_approved = [
            pref.action_type for pref in self.approval_preferences.values()
            if pref.level == ApprovalLevel.AUTO_APPROVE
        ]
        if auto_approved:
            lines.append(f"Auto-approved: {', '.join(auto_approved[:5])}")

        return '\n'.join(lines) if lines else "New user (no preferences yet)"

    def to_dict(self) -> Dict[str, Any]:
        """Export to dictionary."""
        return {
            'approval_preferences': {
                k: v.to_dict() for k, v in self.approval_preferences.items()
            },
            'working_patterns': {
                k: v.to_dict() for k, v in self.working_patterns.items()
            },
            'preferred_verbosity': self.preferred_verbosity,
            'preferred_language': self.preferred_language,
            'use_emojis': self.use_emojis,
            'show_explanations': self.show_explanations,
            'frequent_directories': self.frequent_directories,
            'favorite_projects': self.favorite_projects,
            'recent_projects': self.recent_projects,
            'total_sessions': self.total_sessions,
            'total_tasks_completed': self.total_tasks_completed,
            'first_seen': self.first_seen,
            'last_seen': self.last_seen,
            'custom_preferences': self.custom_preferences,
        }

    def _from_dict(self, data: Dict[str, Any]) -> None:
        """Restore from dictionary."""
        # Approval preferences
        self.approval_preferences = {}
        for k, v in data.get('approval_preferences', {}).items():
            self.approval_preferences[k] = ApprovalPreference.from_dict(v)

        # Working patterns
        self.working_patterns = {}
        for k, v in data.get('working_patterns', {}).items():
            self.working_patterns[k] = WorkingPattern.from_dict(v)

        # Communication preferences
        self.preferred_verbosity = data.get('preferred_verbosity', 'normal')
        self.preferred_language = data.get('preferred_language', 'en')
        self.use_emojis = data.get('use_emojis', False)
        self.show_explanations = data.get('show_explanations', True)

        # Directories and projects
        self.frequent_directories = data.get('frequent_directories', [])
        self.favorite_projects = data.get('favorite_projects', [])
        self.recent_projects = data.get('recent_projects', [])

        # Session tracking
        self.total_sessions = data.get('total_sessions', 0)
        self.total_tasks_completed = data.get('total_tasks_completed', 0)
        self.first_seen = data.get('first_seen')
        self.last_seen = data.get('last_seen')

        # Custom preferences
        self.custom_preferences = data.get('custom_preferences', {})
