"""
Project Debug Context
=====================

Manages persistent debug context stored in the project directory.
All context is saved to {project_dir}/.raica/ for continuity across sessions.
"""

import json
import logging
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any
from ..config_accessor import get_max_iterations

logger = logging.getLogger(__name__)


class DebugStatus(Enum):
    """Status of the debug session."""
    INITIALIZING = "initializing"
    ANALYZING = "analyzing"
    GENERATING_TEST = "generating_test"
    FIXING = "fixing"
    TESTING = "testing"
    VERIFYING = "verifying"
    BLOCKED = "blocked"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class RootCause:
    """Identified root cause of a bug."""
    description: str
    file_path: str
    line_number: Optional[int] = None
    code_snippet: Optional[str] = None
    confidence: float = 0.0
    hypothesis_number: int = 1


@dataclass
class DebugIteration:
    """A single debug iteration attempt."""
    iteration_number: int
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    # What we tried
    hypothesis: Optional[str] = None
    action_taken: Optional[str] = None
    files_modified: List[str] = field(default_factory=list)

    # Results
    test_generated: Optional[str] = None
    test_result_before: Optional[bool] = None  # Should be False (bug exists)
    test_result_after: Optional[bool] = None   # Should be True (bug fixed)
    regression_check_passed: Optional[bool] = None

    # Outcome
    success: bool = False
    failure_reason: Optional[str] = None
    rollback_performed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DebugIteration':
        return cls(**data)


@dataclass
class DebugSession:
    """Complete debug session state."""
    session_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    # User's input
    bug_description: str = ""
    error_trace: Optional[str] = None
    user_messages: List[Dict[str, str]] = field(default_factory=list)

    # Iterative state
    current_iteration: int = 0
    max_iterations: int = field(default_factory=get_max_iterations)
    iterations: List[DebugIteration] = field(default_factory=list)

    # Root cause tracking
    root_cause_identified: bool = False
    root_cause: Optional[Dict[str, Any]] = None
    hypotheses: List[str] = field(default_factory=list)

    # Fix tracking
    fix_applied: bool = False
    fix_verified: bool = False
    files_modified: List[str] = field(default_factory=list)
    original_file_contents: Dict[str, str] = field(default_factory=dict)

    # Test state
    bug_test_path: Optional[str] = None
    bug_test_passes: bool = False
    existing_tests_pass: bool = True

    # Status
    status: str = DebugStatus.INITIALIZING.value
    blocked_reason: Optional[str] = None
    completion_summary: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        # Convert iterations to dicts
        data['iterations'] = [it if isinstance(it, dict) else asdict(it) for it in self.iterations]
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DebugSession':
        # Convert iteration dicts back to objects
        if 'iterations' in data:
            data['iterations'] = [
                DebugIteration.from_dict(it) if isinstance(it, dict) else it
                for it in data['iterations']
            ]
        return cls(**data)

    def add_iteration(self, iteration: DebugIteration) -> None:
        """Add an iteration to the session."""
        self.iterations.append(iteration)
        self.current_iteration = iteration.iteration_number
        self.updated_at = datetime.now().isoformat()

    def set_status(self, status: DebugStatus, reason: Optional[str] = None) -> None:
        """Update session status."""
        self.status = status.value
        if status == DebugStatus.BLOCKED:
            self.blocked_reason = reason
        self.updated_at = datetime.now().isoformat()

    def set_root_cause(self, root_cause: RootCause) -> None:
        """Set the identified root cause."""
        self.root_cause_identified = True
        self.root_cause = asdict(root_cause)
        self.updated_at = datetime.now().isoformat()

    def log_message(self, role: str, content: str) -> None:
        """Log a message in the session."""
        self.user_messages.append({
            'role': role,
            'content': content,
            'timestamp': datetime.now().isoformat()
        })
        self.updated_at = datetime.now().isoformat()


class ProjectDebugContext:
    """
    Manages persistent debug context for a project.

    All context is stored in {project_dir}/.raica/ including:
    - debug_session.json: Current session state
    - conversation.json: All user interactions
    - iterations/: Each debug iteration preserved
    - test_cases/: Auto-generated bug-specific tests
    - decisions.json: Key decisions made
    """

    def __init__(self, project_dir: Path):
        self.project_dir = Path(project_dir)
        self.context_dir = self.project_dir / ".raica"
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        """Ensure all required directories exist."""
        dirs = [
            self.context_dir,
            self.context_dir / "iterations",
            self.context_dir / "test_cases",
            self.context_dir / "backups",
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)

    @property
    def session_file(self) -> Path:
        return self.context_dir / "debug_session.json"

    @property
    def conversation_file(self) -> Path:
        return self.context_dir / "conversation.json"

    @property
    def decisions_file(self) -> Path:
        return self.context_dir / "decisions.json"

    @property
    def test_cases_dir(self) -> Path:
        return self.context_dir / "test_cases"

    @property
    def backups_dir(self) -> Path:
        return self.context_dir / "backups"

    # ─────────────────────────────────────────────────────────────
    # Session Management
    # ─────────────────────────────────────────────────────────────

    def has_session(self) -> bool:
        """Check if an active debug session exists."""
        return self.session_file.exists()

    def load_session(self) -> Optional[DebugSession]:
        """Load existing debug session if any."""
        if not self.session_file.exists():
            return None
        try:
            with open(self.session_file, 'r') as f:
                data = json.load(f)
            session = DebugSession.from_dict(data)
            logger.info(f"Loaded debug session {session.session_id} (iteration {session.current_iteration})")
            return session
        except Exception as e:
            logger.error(f"Failed to load session: {e}")
            return None

    def save_session(self, session: DebugSession) -> bool:
        """Save session state to project directory."""
        try:
            session.updated_at = datetime.now().isoformat()
            with open(self.session_file, 'w') as f:
                json.dump(session.to_dict(), f, indent=2)
            logger.debug(f"Saved debug session {session.session_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to save session: {e}")
            return False

    def create_session(self, bug_description: str, error_trace: Optional[str] = None) -> DebugSession:
        """Create a new debug session."""
        session = DebugSession(
            bug_description=bug_description,
            error_trace=error_trace,
            status=DebugStatus.ANALYZING.value
        )
        session.log_message('user', bug_description)
        self.save_session(session)
        logger.info(f"Created new debug session {session.session_id}")
        return session

    def clear_session(self) -> None:
        """Clear the current debug session."""
        if self.session_file.exists():
            self.session_file.unlink()
            logger.info("Cleared debug session")

    # ─────────────────────────────────────────────────────────────
    # Iteration Management
    # ─────────────────────────────────────────────────────────────

    def save_iteration(self, iteration: DebugIteration) -> bool:
        """Save an iteration to the iterations directory."""
        try:
            iter_file = self.context_dir / "iterations" / f"{iteration.iteration_number:03d}.json"
            with open(iter_file, 'w') as f:
                json.dump(iteration.to_dict(), f, indent=2)
            logger.debug(f"Saved iteration {iteration.iteration_number}")
            return True
        except Exception as e:
            logger.error(f"Failed to save iteration: {e}")
            return False

    def load_iterations(self) -> List[DebugIteration]:
        """Load all iterations from disk."""
        iterations = []
        iter_dir = self.context_dir / "iterations"
        if not iter_dir.exists():
            return iterations
        for iter_file in sorted(iter_dir.glob("*.json")):
            try:
                with open(iter_file, 'r') as f:
                    data = json.load(f)
                iterations.append(DebugIteration.from_dict(data))
            except Exception as e:
                logger.warning(f"Failed to load iteration {iter_file}: {e}")
        return iterations

    # ─────────────────────────────────────────────────────────────
    # Conversation Management
    # ─────────────────────────────────────────────────────────────

    def get_conversation_history(self) -> List[Dict[str, str]]:
        """Get all user interactions for this project."""
        if not self.conversation_file.exists():
            return []
        try:
            with open(self.conversation_file, 'r') as f:
                return json.load(f)
        except Exception:
            return []

    def add_message(self, role: str, content: str) -> None:
        """Add a message to conversation history."""
        history = self.get_conversation_history()
        history.append({
            'role': role,
            'content': content,
            'timestamp': datetime.now().isoformat()
        })
        try:
            with open(self.conversation_file, 'w') as f:
                json.dump(history, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save conversation: {e}")

    # ─────────────────────────────────────────────────────────────
    # File Backup Management
    # ─────────────────────────────────────────────────────────────

    def backup_file(self, file_path: Path) -> bool:
        """Backup a file before modification."""
        try:
            if not file_path.exists():
                return True  # Nothing to backup

            rel_path = file_path.relative_to(self.project_dir)
            backup_path = self.backups_dir / rel_path
            backup_path.parent.mkdir(parents=True, exist_ok=True)

            # Save with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = backup_path.parent / f"{backup_path.stem}_{timestamp}{backup_path.suffix}"

            import shutil
            shutil.copy2(file_path, backup_file)
            logger.debug(f"Backed up {file_path} to {backup_file}")
            return True
        except Exception as e:
            logger.error(f"Failed to backup {file_path}: {e}")
            return False

    def get_original_content(self, file_path: Path) -> Optional[str]:
        """Get original content of a file before any modifications."""
        try:
            rel_path = file_path.relative_to(self.project_dir)
            backup_dir = self.backups_dir / rel_path.parent
            if not backup_dir.exists():
                return None

            # Find oldest backup
            backups = sorted(backup_dir.glob(f"{file_path.stem}_*{file_path.suffix}"))
            if not backups:
                return None

            with open(backups[0], 'r') as f:
                return f.read()
        except Exception:
            return None

    def restore_file(self, file_path: Path) -> bool:
        """Restore a file from backup."""
        original = self.get_original_content(file_path)
        if original is None:
            return False
        try:
            with open(file_path, 'w') as f:
                f.write(original)
            logger.info(f"Restored {file_path} from backup")
            return True
        except Exception as e:
            logger.error(f"Failed to restore {file_path}: {e}")
            return False

    # ─────────────────────────────────────────────────────────────
    # Test Case Management
    # ─────────────────────────────────────────────────────────────

    def save_bug_test(self, test_name: str, test_content: str) -> Path:
        """Save a bug-specific test case."""
        test_file = self.test_cases_dir / f"test_{test_name}.py"
        try:
            with open(test_file, 'w') as f:
                f.write(test_content)
            logger.info(f"Saved bug test to {test_file}")
            return test_file
        except Exception as e:
            logger.error(f"Failed to save bug test: {e}")
            raise

    def get_bug_tests(self) -> List[Path]:
        """Get all bug-specific test files."""
        return list(self.test_cases_dir.glob("test_*.py"))

    # ─────────────────────────────────────────────────────────────
    # Decision Tracking
    # ─────────────────────────────────────────────────────────────

    def record_decision(self, decision_type: str, description: str, reasoning: str) -> None:
        """Record a key decision made during debugging."""
        decisions = []
        if self.decisions_file.exists():
            try:
                with open(self.decisions_file, 'r') as f:
                    decisions = json.load(f)
            except Exception:
                pass

        decisions.append({
            'type': decision_type,
            'description': description,
            'reasoning': reasoning,
            'timestamp': datetime.now().isoformat()
        })

        try:
            with open(self.decisions_file, 'w') as f:
                json.dump(decisions, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to record decision: {e}")

    def get_decisions(self) -> List[Dict[str, str]]:
        """Get all recorded decisions."""
        if not self.decisions_file.exists():
            return []
        try:
            with open(self.decisions_file, 'r') as f:
                return json.load(f)
        except Exception:
            return []
