"""
State Persistence Module
========================

Provides full state persistence for CLI Coding Agent session resumption.

Features:
- Save/restore agent state (phase, iteration, context)
- Checkpoint management (named checkpoints)
- Automatic state recovery on crashes
"""

import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict, field

logger = logging.getLogger(__name__)


@dataclass
class Checkpoint:
    """A named checkpoint for the agent state."""
    name: str
    timestamp: str
    phase: str
    iteration: int
    context_summary: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Checkpoint':
        return cls(**data)


@dataclass
class AgentState:
    """Complete agent state for persistence."""
    timestamp: str
    phase: str
    iteration: int
    original_request: str
    refined_requirements: List[str]
    generated_files: Dict[str, str]
    validation_history: List[Dict[str, Any]]
    error_history: List[str]
    context_data: Dict[str, Any]
    version: str = "2.1.0"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AgentState':
        return cls(**data)


class StatePersistence:
    """
    Manages state persistence for the CLI Coding Agent.

    State is saved to a JSON file in the project directory,
    allowing sessions to be resumed after interruption.
    """

    STATE_FILENAME = ".coding_agent_state.json"
    CHECKPOINTS_DIR = ".checkpoints"
    MAX_CHECKPOINTS = 10

    def __init__(self, project_dir: Path):
        """
        Initialize state persistence.

        Args:
            project_dir: Directory where state files will be stored
        """
        self.project_dir = Path(project_dir)
        self.state_file = self.project_dir / self.STATE_FILENAME
        self.checkpoints_dir = self.project_dir / self.CHECKPOINTS_DIR

        logger.debug(f"StatePersistence initialized for {project_dir}")

    def save_state(
        self,
        phase: str,
        iteration: int,
        original_request: str,
        refined_requirements: List[str],
        generated_files: Dict[str, str],
        validation_history: Optional[List[Dict[str, Any]]] = None,
        error_history: Optional[List[str]] = None,
        context_data: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Save current agent state to disk.

        Args:
            phase: Current development phase
            iteration: Current iteration number
            original_request: User's original request
            refined_requirements: List of refined requirements
            generated_files: Dict of filepath -> content
            validation_history: History of validation results
            error_history: History of errors encountered
            context_data: Additional context data

        Returns:
            True if save successful, False otherwise
        """
        try:
            state = AgentState(
                timestamp=datetime.now().isoformat(),
                phase=phase,
                iteration=iteration,
                original_request=original_request,
                refined_requirements=refined_requirements or [],
                generated_files=generated_files or {},
                validation_history=validation_history or [],
                error_history=error_history or [],
                context_data=context_data or {}
            )

            # Ensure project directory exists
            self.project_dir.mkdir(parents=True, exist_ok=True)

            # Write state to file
            self.state_file.write_text(
                json.dumps(state.to_dict(), indent=2, default=str)
            )

            logger.info(f"State saved: phase={phase}, iteration={iteration}")
            return True

        except Exception as e:
            logger.error(f"Failed to save state: {e}")
            return False

    def load_state(self) -> Optional[AgentState]:
        """
        Load state from disk.

        Returns:
            AgentState if found and valid, None otherwise
        """
        try:
            if not self.state_file.exists():
                logger.debug("No state file found")
                return None

            data = json.loads(self.state_file.read_text())
            state = AgentState.from_dict(data)

            logger.info(f"State loaded: phase={state.phase}, iteration={state.iteration}")
            return state

        except Exception as e:
            logger.error(f"Failed to load state: {e}")
            return None

    def has_saved_state(self) -> bool:
        """Check if a saved state exists."""
        return self.state_file.exists()

    def clear_state(self) -> bool:
        """
        Clear the saved state.

        Returns:
            True if cleared successfully, False otherwise
        """
        try:
            if self.state_file.exists():
                self.state_file.unlink()
                logger.info("State cleared")
            return True
        except Exception as e:
            logger.error(f"Failed to clear state: {e}")
            return False

    def create_checkpoint(
        self,
        name: str,
        phase: str,
        iteration: int,
        context_summary: Dict[str, Any]
    ) -> bool:
        """
        Create a named checkpoint.

        Args:
            name: Checkpoint name (will be sanitized)
            phase: Current phase
            iteration: Current iteration
            context_summary: Summary of context (not full files)

        Returns:
            True if checkpoint created successfully
        """
        try:
            # Ensure checkpoints directory exists
            self.checkpoints_dir.mkdir(parents=True, exist_ok=True)

            # Sanitize name
            safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            checkpoint = Checkpoint(
                name=safe_name,
                timestamp=timestamp,
                phase=phase,
                iteration=iteration,
                context_summary=context_summary
            )

            # Write checkpoint
            checkpoint_file = self.checkpoints_dir / f"{safe_name}_{timestamp}.json"
            checkpoint_file.write_text(
                json.dumps(checkpoint.to_dict(), indent=2)
            )

            # Cleanup old checkpoints if over limit
            self._cleanup_old_checkpoints()

            logger.info(f"Checkpoint created: {safe_name}")
            return True

        except Exception as e:
            logger.error(f"Failed to create checkpoint: {e}")
            return False

    def list_checkpoints(self) -> List[Checkpoint]:
        """
        List available checkpoints.

        Returns:
            List of Checkpoint objects, sorted by timestamp (newest first)
        """
        checkpoints = []

        try:
            if not self.checkpoints_dir.exists():
                return []

            for checkpoint_file in self.checkpoints_dir.glob("*.json"):
                try:
                    data = json.loads(checkpoint_file.read_text())
                    checkpoints.append(Checkpoint.from_dict(data))
                except Exception as e:
                    logger.warning(f"Failed to read checkpoint {checkpoint_file}: {e}")

            # Sort by timestamp, newest first
            checkpoints.sort(key=lambda c: c.timestamp, reverse=True)

        except Exception as e:
            logger.error(f"Failed to list checkpoints: {e}")

        return checkpoints

    def restore_checkpoint(self, name: str) -> Optional[Checkpoint]:
        """
        Restore from a named checkpoint.

        Args:
            name: Checkpoint name (or partial match)

        Returns:
            Checkpoint if found, None otherwise
        """
        try:
            if not self.checkpoints_dir.exists():
                return None

            # Try exact match first
            matches = list(self.checkpoints_dir.glob(f"{name}*.json"))

            if not matches:
                # Try partial match
                matches = list(self.checkpoints_dir.glob(f"*{name}*.json"))

            if not matches:
                logger.warning(f"No checkpoint found matching: {name}")
                return None

            # Use most recent match
            matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            checkpoint_file = matches[0]

            data = json.loads(checkpoint_file.read_text())
            checkpoint = Checkpoint.from_dict(data)

            logger.info(f"Checkpoint restored: {checkpoint.name}")
            return checkpoint

        except Exception as e:
            logger.error(f"Failed to restore checkpoint: {e}")
            return None

    def delete_checkpoint(self, name: str) -> bool:
        """
        Delete a checkpoint by name.

        Args:
            name: Checkpoint name (or partial match)

        Returns:
            True if deleted, False otherwise
        """
        try:
            if not self.checkpoints_dir.exists():
                return False

            matches = list(self.checkpoints_dir.glob(f"*{name}*.json"))

            if not matches:
                logger.warning(f"No checkpoint found matching: {name}")
                return False

            for match in matches:
                match.unlink()
                logger.info(f"Deleted checkpoint: {match.name}")

            return True

        except Exception as e:
            logger.error(f"Failed to delete checkpoint: {e}")
            return False

    def _cleanup_old_checkpoints(self):
        """Remove old checkpoints if over the limit."""
        try:
            checkpoints = list(self.checkpoints_dir.glob("*.json"))

            if len(checkpoints) <= self.MAX_CHECKPOINTS:
                return

            # Sort by modification time, oldest first
            checkpoints.sort(key=lambda p: p.stat().st_mtime)

            # Delete oldest until within limit
            to_delete = len(checkpoints) - self.MAX_CHECKPOINTS
            for checkpoint_file in checkpoints[:to_delete]:
                checkpoint_file.unlink()
                logger.debug(f"Cleaned up old checkpoint: {checkpoint_file.name}")

        except Exception as e:
            logger.warning(f"Failed to cleanup old checkpoints: {e}")

    def get_state_summary(self) -> Optional[Dict[str, Any]]:
        """
        Get a summary of the saved state without loading full content.

        Returns:
            Dict with state summary or None
        """
        try:
            if not self.state_file.exists():
                return None

            data = json.loads(self.state_file.read_text())

            return {
                'timestamp': data.get('timestamp'),
                'phase': data.get('phase'),
                'iteration': data.get('iteration'),
                'original_request': data.get('original_request', '')[:100] + '...',
                'num_requirements': len(data.get('refined_requirements', [])),
                'num_generated_files': len(data.get('generated_files', {})),
                'num_errors': len(data.get('error_history', [])),
                'version': data.get('version')
            }

        except Exception as e:
            logger.error(f"Failed to get state summary: {e}")
            return None


# Convenience function for quick state check
def check_resumable_session(project_dir: Path) -> Optional[Dict[str, Any]]:
    """
    Check if there's a resumable session in the given directory.

    Args:
        project_dir: Directory to check

    Returns:
        State summary if resumable session exists, None otherwise
    """
    persistence = StatePersistence(project_dir)
    return persistence.get_state_summary()
