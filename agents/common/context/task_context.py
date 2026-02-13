"""
Task Context
============

Current task state and progress tracking.
Tracks the current task, subtasks, and progress within a session.

In-memory during session, can be persisted for resumption.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

import json

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """Status of a task."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskPriority(Enum):
    """Priority of a task."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class SubTask:
    """A subtask within a larger task."""
    id: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    completed_at: Optional[str] = None
    notes: List[str] = field(default_factory=list)
    files_affected: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'description': self.description,
            'status': self.status.value,
            'created_at': self.created_at,
            'completed_at': self.completed_at,
            'notes': self.notes,
            'files_affected': self.files_affected,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SubTask':
        return cls(
            id=data.get('id', str(uuid.uuid4())[:8]),
            description=data.get('description', ''),
            status=TaskStatus(data.get('status', 'pending')),
            created_at=data.get('created_at', datetime.now().isoformat()),
            completed_at=data.get('completed_at'),
            notes=data.get('notes', []),
            files_affected=data.get('files_affected', []),
        )


@dataclass
class Task:
    """A main task being worked on."""
    id: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = TaskPriority.MEDIUM
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    subtasks: List[SubTask] = field(default_factory=list)
    files_affected: List[str] = field(default_factory=list)
    context_notes: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'description': self.description,
            'status': self.status.value,
            'priority': self.priority.value,
            'created_at': self.created_at,
            'started_at': self.started_at,
            'completed_at': self.completed_at,
            'subtasks': [s.to_dict() for s in self.subtasks],
            'files_affected': self.files_affected,
            'context_notes': self.context_notes,
            'blockers': self.blockers,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Task':
        return cls(
            id=data.get('id', str(uuid.uuid4())[:8]),
            description=data.get('description', ''),
            status=TaskStatus(data.get('status', 'pending')),
            priority=TaskPriority(data.get('priority', 'medium')),
            created_at=data.get('created_at', datetime.now().isoformat()),
            started_at=data.get('started_at'),
            completed_at=data.get('completed_at'),
            subtasks=[SubTask.from_dict(s) for s in data.get('subtasks', [])],
            files_affected=data.get('files_affected', []),
            context_notes=data.get('context_notes', []),
            blockers=data.get('blockers', []),
        )

    def add_subtask(self, description: str) -> SubTask:
        """Add a subtask."""
        subtask = SubTask(
            id=str(uuid.uuid4())[:8],
            description=description
        )
        self.subtasks.append(subtask)
        return subtask

    def get_progress(self) -> float:
        """Get task completion progress (0.0 to 1.0)."""
        if not self.subtasks:
            return 1.0 if self.status == TaskStatus.COMPLETED else 0.0

        completed = sum(1 for s in self.subtasks if s.status == TaskStatus.COMPLETED)
        return completed / len(self.subtasks)


class TaskContext:
    """
    Manages current task state and progress.
    Tracks the active task and maintains task history.
    """

    def __init__(self, project_dir: Optional[Path] = None):
        """
        Initialize TaskContext.

        Args:
            project_dir: Project directory for task history storage
        """
        self.project_dir = project_dir or Path.cwd()
        self.task_history_file = self.project_dir / ".raica" / "task_history.json"

        # Current session
        self.session_id: str = str(uuid.uuid4())[:12]
        self.session_start: str = datetime.now().isoformat()

        # Current task
        self.current_task: Optional[Task] = None

        # Task history (completed tasks)
        self.completed_tasks: List[Task] = []

        # Session metrics
        self.tasks_started: int = 0
        self.tasks_completed: int = 0
        self.files_modified: List[str] = []

    def create_task(
        self,
        description: str,
        priority: TaskPriority = TaskPriority.MEDIUM
    ) -> Task:
        """
        Create and set the current task.

        Args:
            description: Task description
            priority: Task priority

        Returns:
            Created Task
        """
        # Archive current task if exists
        if self.current_task:
            self._archive_current_task()

        self.current_task = Task(
            id=str(uuid.uuid4())[:8],
            description=description,
            priority=priority
        )
        self.tasks_started += 1

        logger.info(f"Created task: {description}")
        return self.current_task

    def start_task(self) -> bool:
        """Mark current task as in progress."""
        if not self.current_task:
            return False

        self.current_task.status = TaskStatus.IN_PROGRESS
        self.current_task.started_at = datetime.now().isoformat()
        return True

    def complete_task(self, notes: Optional[str] = None) -> bool:
        """
        Mark current task as completed.

        Args:
            notes: Optional completion notes

        Returns:
            True if successful
        """
        if not self.current_task:
            return False

        self.current_task.status = TaskStatus.COMPLETED
        self.current_task.completed_at = datetime.now().isoformat()

        if notes:
            self.current_task.context_notes.append(f"[Completed] {notes}")

        self.tasks_completed += 1
        self._archive_current_task()
        self.current_task = None

        return True

    def fail_task(self, reason: str) -> bool:
        """
        Mark current task as failed.

        Args:
            reason: Failure reason

        Returns:
            True if successful
        """
        if not self.current_task:
            return False

        self.current_task.status = TaskStatus.FAILED
        self.current_task.completed_at = datetime.now().isoformat()
        self.current_task.context_notes.append(f"[Failed] {reason}")

        self._archive_current_task()
        self.current_task = None

        return True

    def block_task(self, blocker: str) -> bool:
        """
        Mark current task as blocked.

        Args:
            blocker: What is blocking the task

        Returns:
            True if successful
        """
        if not self.current_task:
            return False

        self.current_task.status = TaskStatus.BLOCKED
        self.current_task.blockers.append(blocker)
        return True

    def add_subtask(self, description: str) -> Optional[SubTask]:
        """Add a subtask to current task."""
        if not self.current_task:
            return None

        return self.current_task.add_subtask(description)

    def complete_subtask(self, subtask_id: str) -> bool:
        """Mark a subtask as completed."""
        if not self.current_task:
            return False

        for subtask in self.current_task.subtasks:
            if subtask.id == subtask_id:
                subtask.status = TaskStatus.COMPLETED
                subtask.completed_at = datetime.now().isoformat()
                return True

        return False

    def add_context_note(self, note: str) -> None:
        """Add a context note to current task."""
        if self.current_task:
            timestamp = datetime.now().strftime("%H:%M")
            self.current_task.context_notes.append(f"[{timestamp}] {note}")

    def record_file_modified(self, file_path: str) -> None:
        """Record that a file was modified."""
        if file_path not in self.files_modified:
            self.files_modified.append(file_path)

        if self.current_task and file_path not in self.current_task.files_affected:
            self.current_task.files_affected.append(file_path)

    def _archive_current_task(self) -> None:
        """Archive the current task to history."""
        if self.current_task:
            self.completed_tasks.append(self.current_task)
            # Keep only last 50 tasks in memory
            self.completed_tasks = self.completed_tasks[-50:]

    def save_history(self) -> bool:
        """Save task history to disk."""
        try:
            self.task_history_file.parent.mkdir(parents=True, exist_ok=True)

            # Load existing history
            existing = []
            if self.task_history_file.exists():
                with open(self.task_history_file, 'r') as f:
                    data = json.load(f)
                    existing = data.get('tasks', [])

            # Append new completed tasks
            for task in self.completed_tasks:
                existing.append(task.to_dict())

            # Keep last 200 tasks
            existing = existing[-200:]

            with open(self.task_history_file, 'w') as f:
                json.dump({'tasks': existing}, f, indent=2)

            return True

        except Exception as e:
            logger.warning(f"Failed to save task history: {e}")
            return False

    def load_history(self, limit: int = 20) -> List[Task]:
        """
        Load recent task history from disk.

        Args:
            limit: Maximum tasks to load

        Returns:
            List of recent tasks
        """
        if not self.task_history_file.exists():
            return []

        try:
            with open(self.task_history_file, 'r') as f:
                data = json.load(f)

            tasks = [Task.from_dict(t) for t in data.get('tasks', [])]
            return tasks[-limit:]

        except Exception as e:
            logger.warning(f"Failed to load task history: {e}")
            return []

    def get_progress_summary(self) -> str:
        """Get a summary of current progress."""
        lines = []

        if self.current_task:
            progress = self.current_task.get_progress()
            status = self.current_task.status.value

            lines.append(f"Current: {self.current_task.description}")
            lines.append(f"Status: {status} ({progress*100:.0f}% complete)")

            if self.current_task.subtasks:
                completed = sum(1 for s in self.current_task.subtasks if s.status == TaskStatus.COMPLETED)
                lines.append(f"Subtasks: {completed}/{len(self.current_task.subtasks)}")

            if self.current_task.blockers:
                lines.append(f"Blockers: {', '.join(self.current_task.blockers)}")

        if self.files_modified:
            lines.append(f"Files modified: {len(self.files_modified)}")

        return '\n'.join(lines) if lines else "No active task"

    def to_dict(self) -> Dict[str, Any]:
        """Export to dictionary."""
        return {
            'session_id': self.session_id,
            'session_start': self.session_start,
            'current_task': self.current_task.to_dict() if self.current_task else None,
            'tasks_started': self.tasks_started,
            'tasks_completed': self.tasks_completed,
            'files_modified': self.files_modified,
        }
