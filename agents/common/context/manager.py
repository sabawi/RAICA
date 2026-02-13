"""
Context Manager
===============

Central coordinator for all context layers.
Manages directory, project, task, and conversation contexts.
Integrates with the AwarenessSystem for system/user awareness.

Usage:
    context_manager = ContextManager(project_dir=Path.cwd())
    context_manager.initialize()

    # Access context layers
    context_manager.project_context.add_goal("Implement feature X")
    context_manager.task_context.create_task("Fix bug Y")

    # Get full context for LLM
    context = context_manager.get_full_context()
"""

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from ..awareness.system import AwarenessSystem
from .directory_context import DirectoryContext
from .project_context import ProjectContext
from .task_context import TaskContext
from .conversation_context import ConversationContext
from .debugging_discipline import DebuggingDiscipline

logger = logging.getLogger(__name__)


class ContextManager:
    """
    Coordinates all context layers.

    Provides unified access to:
    - DirectoryContext: Per-directory settings and history
    - ProjectContext: Project goals, patterns, conventions
    - TaskContext: Current task state and progress
    - ConversationContext: Conversation history and decisions
    - DebuggingDiscipline: Systematic debugging rules
    - AwarenessSystem: System and user awareness
    """

    def __init__(
        self,
        project_dir: Optional[Path] = None,
        user_home: Optional[Path] = None,
        session_id: Optional[str] = None,
        auto_initialize: bool = True
    ):
        """
        Initialize ContextManager.

        Args:
            project_dir: Root directory of the current project
            user_home: User home directory for global storage
            session_id: Session ID for conversation context
            auto_initialize: If True, initialize all contexts on creation
        """
        self.project_dir = Path(project_dir).resolve() if project_dir else Path.cwd()
        self.user_home = user_home or Path.home()
        self.global_storage = self.user_home / ".raica"

        # Initialize context layers
        self.directory_context = DirectoryContext(
            global_storage=self.global_storage
        )
        self.project_context = ProjectContext(
            project_dir=self.project_dir
        )
        self.task_context = TaskContext(
            project_dir=self.project_dir
        )
        self.conversation_context = ConversationContext(
            global_storage=self.global_storage,
            session_id=session_id
        )
        self.debugging_discipline = DebuggingDiscipline(
            project_dir=self.project_dir
        )

        # Initialize awareness system
        self.awareness = AwarenessSystem(
            user_home=self.user_home,
            auto_initialize=False  # We'll initialize it ourselves
        )

        self._initialized = False

        if auto_initialize:
            self.initialize()

    def initialize(self) -> None:
        """
        Initialize all context layers.
        Loads persisted data and detects current environment.
        """
        logger.info(f"Initializing ContextManager for: {self.project_dir}")

        # Ensure global storage exists
        self.global_storage.mkdir(parents=True, exist_ok=True)

        # Initialize awareness first (detects system capabilities)
        self.awareness.initialize()

        # Load directory context
        self.directory_context.load()
        self.directory_context.enter_directory(str(self.project_dir))

        # Load project context
        self.project_context.load()

        # Task context is session-specific, no load needed
        # But we can load history for reference
        self.task_context.load_history(limit=10)

        # Conversation context - set project path
        self.conversation_context.project_path = str(self.project_dir)

        # Load debugging discipline state
        self.debugging_discipline.load()

        # Refresh environment for current directory
        self.awareness.refresh_environment(str(self.project_dir))

        self._initialized = True
        logger.info("ContextManager initialized")

    def switch_project(self, new_project_dir: Path) -> None:
        """
        Switch to a different project directory.

        Args:
            new_project_dir: New project directory to switch to
        """
        # Save current state
        self.save_all()

        # Update project directory
        self.project_dir = Path(new_project_dir).resolve()

        # Reinitialize project-specific contexts
        self.project_context = ProjectContext(project_dir=self.project_dir)
        self.project_context.load()

        self.task_context = TaskContext(project_dir=self.project_dir)

        self.debugging_discipline = DebuggingDiscipline(project_dir=self.project_dir)
        self.debugging_discipline.load()

        # Update directory context
        self.directory_context.enter_directory(str(self.project_dir))

        # Update conversation context
        self.conversation_context.project_path = str(self.project_dir)

        # Refresh environment awareness
        self.awareness.refresh_environment(str(self.project_dir))

        logger.info(f"Switched to project: {self.project_dir}")

    def get_full_context(self) -> Dict[str, Any]:
        """
        Get merged context from all layers for LLM prompts.

        Returns:
            Dictionary with all context data
        """
        # Ensure file structure is scanned (will skip if not stale)
        self.project_context.scan_file_structure(force=False)

        # Build file structure context
        file_structure = {}
        if self.project_context.directory_tree:
            file_structure['file_tree'] = self.project_context.directory_tree.tree_string
            file_structure['file_count'] = self.project_context.directory_tree.file_count
            file_structure['directory_count'] = self.project_context.directory_tree.directory_count
        file_structure['tracked_files_count'] = len(self.project_context.file_entries)
        file_structure['key_files'] = list(self.project_context.key_file_contents.keys())

        return {
            'system': self.awareness.get_context_for_llm(),
            'project': {
                'name': self.project_context.project_name,
                'description': self.project_context.project_description,
                'type': self.project_context.project_type,
                'active_goals': [
                    g.description for g in self.project_context.get_active_goals()
                ],
                'conventions': [
                    c.name for c in self.project_context.conventions
                ],
                'tech_stack': self.project_context.tech_stack,
            },
            'file_structure': file_structure,
            'task': self.task_context.to_dict() if self.task_context.current_task else None,
            'conversation': {
                'session_id': self.conversation_context.session_id,
                'message_count': len(self.conversation_context.messages),
                'topics': self.conversation_context.topics_discussed[-5:],
                'recent_decisions': [
                    d.description for d in self.conversation_context.get_recent_decisions(3)
                ],
            },
            'debugging': {
                'assumptions_count': len(self.debugging_discipline.assumptions),
                'unverified_count': len(self.debugging_discipline.get_unverified_assumptions()),
                'issues_pending': len(self.debugging_discipline.get_unapproved_issues()),
                'root_cause_identified': self.debugging_discipline.root_cause_identified,
            },
            'directory': {
                'path': str(self.project_dir),
                'recent_commands': self.directory_context.get_recent_commands(5),
            }
        }

    def get_context_summary(self) -> str:
        """
        Get a human-readable summary for LLM system prompts.

        Returns:
            Multi-line string with context summary
        """
        sections = []

        # System awareness
        awareness_summary = self.awareness.get_capabilities_summary()
        if awareness_summary:
            sections.append(awareness_summary)

        # Project context
        project_summary = self.project_context.get_summary()
        if project_summary:
            sections.append("=== Project ===\n" + project_summary)

        # Task progress
        task_summary = self.task_context.get_progress_summary()
        if task_summary and task_summary != "No active task":
            sections.append("=== Task ===\n" + task_summary)

        # Conversation context
        conv_summary = self.conversation_context.get_summary_for_llm()
        if conv_summary:
            sections.append("=== Conversation ===\n" + conv_summary)

        # Debugging discipline
        debug_summary = self.debugging_discipline.get_discipline_status()
        if debug_summary and debug_summary != "No debugging activity yet":
            sections.append("=== Debugging ===\n" + debug_summary)

        return "\n\n".join(sections)

    def get_file_structure_context(self, include_symbols: bool = True, force_rescan: bool = False) -> str:
        """
        Get formatted file structure context for LLM prompts.

        This method ensures the file structure is scanned (if stale) and returns
        a formatted string suitable for injection into LLM prompts.

        Args:
            include_symbols: Whether to include extracted Python symbols
            force_rescan: If True, force a rescan even if not stale

        Returns:
            Formatted string with project file structure
        """
        # Ensure file structure is scanned
        self.project_context.scan_file_structure(force=force_rescan)

        return self.project_context.get_file_structure_context(include_symbols=include_symbols)

    def record_command(self, command: str) -> None:
        """Record a command executed in current directory."""
        self.directory_context.record_command(command)

    def record_file_modified(self, file_path: str) -> None:
        """Record that a file was modified."""
        self.task_context.record_file_modified(file_path)

    def add_conversation_message(self, role: str, content: str) -> None:
        """Add a message to conversation history."""
        self.conversation_context.add_message(role, content)

    def get_recent_messages(self, limit: int = 10) -> list:
        """Get recent conversation messages."""
        messages = self.conversation_context.get_recent_messages(limit=limit)
        # Convert Message objects to dicts for compatibility
        return [{'role': msg.role, 'content': msg.content} for msg in messages]

    def record_decision(
        self,
        description: str,
        choice: str,
        rationale: str
    ) -> None:
        """Record a decision in conversation context."""
        self.conversation_context.record_decision(description, choice, rationale)

    def document_assumption(self, description: str) -> int:
        """
        Document an assumption in debugging discipline.

        Returns:
            Assumption ID
        """
        assumption = self.debugging_discipline.document_assumption(description)
        return assumption.id

    def verify_assumption(
        self,
        assumption_id: int,
        method: str,
        result: str,
        is_true: bool
    ) -> bool:
        """Verify an assumption."""
        return self.debugging_discipline.verify_assumption(
            assumption_id, method, result, is_true
        )

    def flag_issue(
        self,
        description: str,
        severity: str = "medium",
        found_in: str = "",
        suggested_fix: str = ""
    ) -> int:
        """
        Flag an issue found during work.

        Returns:
            Issue ID
        """
        from .debugging_discipline import IssueSeverity
        severity_enum = IssueSeverity(severity)
        issue = self.debugging_discipline.flag_issue(
            description=description,
            severity=severity_enum,
            found_in=found_in,
            suggested_fix=suggested_fix
        )
        return issue.id

    def save_all(self) -> bool:
        """
        Save all context layers to disk.

        Returns:
            True if all saves successful
        """
        success = True

        try:
            self.directory_context.save()
        except Exception as e:
            logger.warning(f"Failed to save directory context: {e}")
            success = False

        try:
            self.project_context.save()
        except Exception as e:
            logger.warning(f"Failed to save project context: {e}")
            success = False

        try:
            self.task_context.save_history()
        except Exception as e:
            logger.warning(f"Failed to save task history: {e}")
            success = False

        try:
            self.conversation_context.save()
        except Exception as e:
            logger.warning(f"Failed to save conversation: {e}")
            success = False

        try:
            self.debugging_discipline.save()
        except Exception as e:
            logger.warning(f"Failed to save debugging state: {e}")
            success = False

        try:
            self.awareness.save()
        except Exception as e:
            logger.warning(f"Failed to save awareness state: {e}")
            success = False

        if success:
            logger.debug("All context layers saved")

        return success

    def to_dict(self) -> Dict[str, Any]:
        """Export full state to dictionary."""
        return {
            'initialized': self._initialized,
            'project_dir': str(self.project_dir),
            'awareness': self.awareness.to_dict(),
            'directory_context': self.directory_context.to_dict(),
            'project_context': self.project_context.to_dict(),
            'task_context': self.task_context.to_dict(),
            'conversation_context': self.conversation_context.to_dict(),
            'debugging_discipline': self.debugging_discipline.to_dict(),
        }

    @property
    def is_initialized(self) -> bool:
        """Check if the manager has been initialized."""
        return self._initialized
