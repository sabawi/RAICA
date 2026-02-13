"""
RAICA Context Management System
===============================

Provides 4-layer context retention for RAICA agents:
1. DirectoryContext - Per-directory settings and history
2. ProjectContext - Project goals, patterns, conventions
3. TaskContext - Current task state and progress
4. ConversationContext - Conversation history and decisions

Also includes:
- DebuggingDiscipline - Systematic debugging rules enforcement
- ContextManager - Coordinator for all context layers

Storage:
- ~/.raica/ - Global user settings
- .raica/ - Project-specific context (in project root)
"""

from .directory_context import DirectoryContext
from .project_context import ProjectContext
from .task_context import TaskContext
from .conversation_context import ConversationContext
from .debugging_discipline import DebuggingDiscipline, Assumption, IssueFound
from .manager import ContextManager

__all__ = [
    'ContextManager',
    'DirectoryContext',
    'ProjectContext',
    'TaskContext',
    'ConversationContext',
    'DebuggingDiscipline',
    'Assumption',
    'IssueFound',
]
