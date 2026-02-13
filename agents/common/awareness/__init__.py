"""
RAICA Awareness System
======================

Provides system and environment awareness for RAICA agents.
Initialized at agent startup to detect capabilities before any requests.

Components:
- SystemProfile: OS, tools, package managers detection
- UserProfile: User preferences and patterns
- EnvironmentState: Runtime environment state
- AwarenessSystem: Coordinator for all awareness components
"""

from .system_profile import SystemProfile, ToolCapability
from .user_profile import UserProfile, ApprovalPreference, WorkingPattern
from .environment_state import EnvironmentState, ActiveProject
from .system import AwarenessSystem

__all__ = [
    'AwarenessSystem',
    'SystemProfile',
    'ToolCapability',
    'UserProfile',
    'ApprovalPreference',
    'WorkingPattern',
    'EnvironmentState',
    'ActiveProject',
]
