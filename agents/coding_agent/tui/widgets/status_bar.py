"""
Status Bar Widget
=================

Displays current phase, iteration, progress, and status information.
Includes thread/task monitoring for visibility into background work.
"""

import threading
import asyncio
from textual.widgets import Static
from textual.reactive import reactive
from rich.text import Text
from rich.table import Table
from typing import Optional, Dict, List
from datetime import datetime
from dataclasses import dataclass, field


@dataclass
class TaskInfo:
    """Information about a running task."""
    task_id: str
    name: str
    description: str
    started_at: datetime = field(default_factory=datetime.now)
    status: str = "running"  # running, completed, failed


class StatusBar(Static):
    """
    Status bar showing current phase, iteration, and progress.

    Features:
    - Current phase indicator
    - Iteration counter
    - Progress percentage
    - Elapsed time
    - Status messages
    """

    DEFAULT_CSS = """
    StatusBar {
        height: auto;
        min-height: 3;
        max-height: 5;
        background: $surface;
        border: solid $primary-darken-2;
        padding: 0 1;
    }
    """

    # Reactive attributes for automatic updates
    phase = reactive("READY")
    iteration = reactive(1)
    progress = reactive(0.0)
    status_message = reactive("")
    files_generated = reactive(0)
    errors_count = reactive(0)

    PHASE_COLORS = {
        "READY": "white",
        "REQUIREMENTS": "cyan",
        "PLANNING": "blue",
        "ARCHITECTURE": "magenta",
        "DESIGN": "yellow",
        "INTERFACE_GENERATION": "cyan",
        "CODING": "green",
        "DEBUGGING": "red",
        "TESTING": "yellow",
        "COMPLETE": "green bold",
        "ERROR": "red bold",
        "PAUSED": "yellow bold",
    }

    def __init__(
        self,
        *,
        name: Optional[str] = None,
        id: Optional[str] = None,
        classes: Optional[str] = None,
    ):
        """Initialize the status bar."""
        super().__init__(name=name, id=id, classes=classes)
        self._start_time: Optional[datetime] = None
        self._active_tasks: Dict[str, TaskInfo] = {}
        self._task_counter = 0

    def on_mount(self) -> None:
        """Called when widget is mounted."""
        self._start_time = datetime.now()
        self._update_display()

    def watch_phase(self, value: str) -> None:
        """React to phase changes."""
        self._update_display()

    def watch_iteration(self, value: int) -> None:
        """React to iteration changes."""
        self._update_display()

    def watch_progress(self, value: float) -> None:
        """React to progress changes."""
        self._update_display()

    def watch_status_message(self, value: str) -> None:
        """React to status message changes."""
        self._update_display()

    def watch_files_generated(self, value: int) -> None:
        """React to files generated count changes."""
        self._update_display()

    def watch_errors_count(self, value: int) -> None:
        """React to errors count changes."""
        self._update_display()

    def _get_elapsed_time(self) -> str:
        """Get formatted elapsed time."""
        if not self._start_time:
            return "00:00"

        elapsed = datetime.now() - self._start_time
        minutes = int(elapsed.total_seconds() // 60)
        seconds = int(elapsed.total_seconds() % 60)
        return f"{minutes:02d}:{seconds:02d}"

    def _get_progress_bar(self, width: int = 20) -> Text:
        """Generate a text-based progress bar."""
        filled = int(width * self.progress / 100) if self.progress > 0 else 0
        empty = width - filled

        bar = Text()
        bar.append("█" * filled, style="green")
        bar.append("░" * empty, style="dim")
        return bar

    def _update_display(self) -> None:
        """Update the status bar display."""
        # Create status line
        output = Text()

        # Phase indicator
        phase_color = self.PHASE_COLORS.get(self.phase.upper(), "white")
        output.append("Phase: ", style="bold")
        output.append(f"{self.phase}", style=phase_color)

        # Separator
        output.append(" │ ", style="dim")

        # Iteration
        output.append("Iter: ", style="bold")
        output.append(f"{self.iteration}", style="cyan")

        # Separator
        output.append(" │ ", style="dim")

        # Progress
        output.append("Progress: ", style="bold")
        progress_bar = self._get_progress_bar(15)
        output.append_text(progress_bar)
        output.append(f" {self.progress:.0f}%", style="cyan")

        # Separator
        output.append(" │ ", style="dim")

        # Files generated
        output.append("Files: ", style="bold")
        output.append(f"{self.files_generated}", style="green")

        # Errors (if any)
        if self.errors_count > 0:
            output.append(" │ ", style="dim")
            output.append("Errors: ", style="bold")
            output.append(f"{self.errors_count}", style="red bold")

        # Separator
        output.append(" │ ", style="dim")

        # Active tasks count
        active_count = len([t for t in self._active_tasks.values() if t.status == "running"])
        output.append("Tasks: ", style="bold")
        if active_count > 0:
            output.append(f"{active_count} running", style="yellow")
        else:
            output.append("idle", style="dim")

        # Separator
        output.append(" │ ", style="dim")

        # Elapsed time
        output.append("Time: ", style="bold")
        output.append(self._get_elapsed_time(), style="dim")

        # Status message on second line if present
        if self.status_message:
            output.append("\n")
            output.append("→ ", style="dim")
            output.append(self.status_message, style="italic")

        # Show active tasks on third line if any
        running_tasks = [t for t in self._active_tasks.values() if t.status == "running"]
        if running_tasks:
            output.append("\n")
            output.append("⚙ Active: ", style="bold yellow")
            task_names = [f"{t.name}" for t in running_tasks[:3]]  # Show max 3
            output.append(", ".join(task_names), style="yellow")
            if len(running_tasks) > 3:
                output.append(f" +{len(running_tasks) - 3} more", style="dim")

        self.update(output)

    def set_phase(self, phase: str, iteration: int = 1) -> None:
        """
        Set the current phase.

        Args:
            phase: Phase name
            iteration: Current iteration
        """
        self.phase = phase
        self.iteration = iteration

    def set_progress(self, progress: float, message: str = "") -> None:
        """
        Set progress percentage.

        Args:
            progress: Progress 0-100
            message: Optional status message
        """
        self.progress = min(100.0, max(0.0, progress))
        if message:
            self.status_message = message

    def set_status(self, message: str) -> None:
        """Set status message."""
        self.status_message = message

    def increment_files(self, count: int = 1) -> None:
        """Increment files generated count."""
        self.files_generated += count

    def increment_errors(self, count: int = 1) -> None:
        """Increment errors count."""
        self.errors_count += count

    def reset_counters(self) -> None:
        """Reset file and error counters."""
        self.files_generated = 0
        self.errors_count = 0

    def reset(self) -> None:
        """Reset status bar to initial state."""
        self.phase = "READY"
        self.iteration = 1
        self.progress = 0.0
        self.status_message = ""
        self.files_generated = 0
        self.errors_count = 0
        self._start_time = datetime.now()

    def start_timer(self) -> None:
        """Start or restart the elapsed time timer."""
        self._start_time = datetime.now()

    # =========================================================================
    # Task/Thread Monitoring
    # =========================================================================

    def register_task(self, name: str, description: str = "") -> str:
        """
        Register a new task and return its ID.

        Args:
            name: Short name for the task (e.g., "LLM Call", "File Write")
            description: Longer description of what the task is doing

        Returns:
            Task ID that can be used to update/complete the task
        """
        self._task_counter += 1
        task_id = f"task_{self._task_counter}"
        self._active_tasks[task_id] = TaskInfo(
            task_id=task_id,
            name=name,
            description=description,
        )
        self._update_display()
        return task_id

    def update_task(self, task_id: str, description: str) -> None:
        """Update a task's description."""
        if task_id in self._active_tasks:
            self._active_tasks[task_id].description = description
            self._update_display()

    def complete_task(self, task_id: str, success: bool = True) -> None:
        """
        Mark a task as complete.

        Args:
            task_id: The task ID returned by register_task
            success: Whether the task completed successfully
        """
        if task_id in self._active_tasks:
            self._active_tasks[task_id].status = "completed" if success else "failed"
            self._update_display()

    def remove_task(self, task_id: str) -> None:
        """Remove a task from the active list."""
        if task_id in self._active_tasks:
            del self._active_tasks[task_id]
            self._update_display()

    def get_active_tasks(self) -> List[TaskInfo]:
        """Get list of currently active tasks."""
        return [t for t in self._active_tasks.values() if t.status == "running"]

    def get_task_count(self) -> int:
        """Get count of running tasks."""
        return len(self.get_active_tasks())

    def clear_completed_tasks(self) -> None:
        """Remove all completed/failed tasks from the list."""
        self._active_tasks = {
            k: v for k, v in self._active_tasks.items()
            if v.status == "running"
        }
        self._update_display()

    def get_system_info(self) -> Dict:
        """
        Get system thread/process information.

        Returns:
            Dict with thread and asyncio task counts
        """
        # Count Python threads
        thread_count = threading.active_count()
        thread_names = [t.name for t in threading.enumerate()]

        # Count asyncio tasks (if in async context)
        try:
            loop = asyncio.get_running_loop()
            asyncio_tasks = len(asyncio.all_tasks(loop))
        except RuntimeError:
            asyncio_tasks = 0

        return {
            "threads": thread_count,
            "thread_names": thread_names,
            "asyncio_tasks": asyncio_tasks,
            "registered_tasks": len(self._active_tasks),
            "running_tasks": self.get_task_count(),
        }
