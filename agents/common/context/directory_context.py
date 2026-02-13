"""
Directory Context
=================

Per-directory settings and history tracking.
Stores directory-specific preferences and command history.

Persisted to ~/.raica/history/directories.json
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class DirectoryEntry:
    """Entry for a tracked directory."""
    path: str
    last_accessed: str
    access_count: int = 1
    last_commands: List[str] = field(default_factory=list)
    preferences: Dict[str, Any] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'path': self.path,
            'last_accessed': self.last_accessed,
            'access_count': self.access_count,
            'last_commands': self.last_commands[-20:],  # Keep last 20
            'preferences': self.preferences,
            'notes': self.notes[-10:],  # Keep last 10
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DirectoryEntry':
        return cls(
            path=data.get('path', ''),
            last_accessed=data.get('last_accessed', ''),
            access_count=data.get('access_count', 1),
            last_commands=data.get('last_commands', []),
            preferences=data.get('preferences', {}),
            notes=data.get('notes', []),
        )


class DirectoryContext:
    """
    Manages per-directory context and history.
    Tracks commands, preferences, and notes for each directory.
    """

    HISTORY_FILE = "directories.json"
    MAX_DIRECTORIES = 100  # Limit stored directories

    def __init__(self, global_storage: Optional[Path] = None):
        """
        Initialize DirectoryContext.

        Args:
            global_storage: Path to global storage. Defaults to ~/.raica/
        """
        self.global_storage = global_storage or (Path.home() / ".raica")
        self.history_dir = self.global_storage / "history"
        self.history_file = self.history_dir / self.HISTORY_FILE

        self.directories: Dict[str, DirectoryEntry] = {}
        self.current_directory: Optional[str] = None

    def load(self) -> bool:
        """Load directory history from disk."""
        if not self.history_file.exists():
            return False

        try:
            with open(self.history_file, 'r') as f:
                data = json.load(f)

            self.directories = {}
            for path, entry_data in data.get('directories', {}).items():
                self.directories[path] = DirectoryEntry.from_dict(entry_data)

            logger.debug(f"Loaded {len(self.directories)} directory entries")
            return True

        except Exception as e:
            logger.warning(f"Failed to load directory history: {e}")
            return False

    def save(self) -> bool:
        """Save directory history to disk."""
        try:
            self.history_dir.mkdir(parents=True, exist_ok=True)

            # Prune old entries if over limit
            if len(self.directories) > self.MAX_DIRECTORIES:
                self._prune_old_entries()

            data = {
                'directories': {
                    path: entry.to_dict()
                    for path, entry in self.directories.items()
                }
            }

            with open(self.history_file, 'w') as f:
                json.dump(data, f, indent=2)

            return True

        except Exception as e:
            logger.warning(f"Failed to save directory history: {e}")
            return False

    def _prune_old_entries(self) -> None:
        """Remove oldest entries to stay under limit."""
        # Sort by last_accessed, keep most recent
        sorted_entries = sorted(
            self.directories.items(),
            key=lambda x: x[1].last_accessed,
            reverse=True
        )
        self.directories = dict(sorted_entries[:self.MAX_DIRECTORIES])

    def enter_directory(self, directory: str) -> DirectoryEntry:
        """
        Record entering a directory.

        Args:
            directory: Path to the directory

        Returns:
            DirectoryEntry for this directory
        """
        directory = str(Path(directory).resolve())
        self.current_directory = directory
        now = datetime.now().isoformat()

        if directory in self.directories:
            entry = self.directories[directory]
            entry.last_accessed = now
            entry.access_count += 1
        else:
            entry = DirectoryEntry(
                path=directory,
                last_accessed=now,
                access_count=1
            )
            self.directories[directory] = entry

        return entry

    def record_command(self, command: str, directory: Optional[str] = None) -> None:
        """
        Record a command executed in a directory.

        Args:
            command: The command that was executed
            directory: Directory where it was executed (defaults to current)
        """
        directory = directory or self.current_directory
        if not directory:
            return

        directory = str(Path(directory).resolve())

        if directory not in self.directories:
            self.enter_directory(directory)

        entry = self.directories[directory]
        entry.last_commands.append(command)
        entry.last_commands = entry.last_commands[-20:]  # Keep last 20

    def set_preference(
        self,
        key: str,
        value: Any,
        directory: Optional[str] = None
    ) -> None:
        """
        Set a preference for a directory.

        Args:
            key: Preference key
            value: Preference value
            directory: Directory (defaults to current)
        """
        directory = directory or self.current_directory
        if not directory:
            return

        directory = str(Path(directory).resolve())

        if directory not in self.directories:
            self.enter_directory(directory)

        self.directories[directory].preferences[key] = value

    def get_preference(
        self,
        key: str,
        default: Any = None,
        directory: Optional[str] = None
    ) -> Any:
        """
        Get a preference for a directory.

        Args:
            key: Preference key
            default: Default value if not found
            directory: Directory (defaults to current)

        Returns:
            Preference value or default
        """
        directory = directory or self.current_directory
        if not directory:
            return default

        directory = str(Path(directory).resolve())

        if directory not in self.directories:
            return default

        return self.directories[directory].preferences.get(key, default)

    def add_note(self, note: str, directory: Optional[str] = None) -> None:
        """
        Add a note for a directory.

        Args:
            note: Note text
            directory: Directory (defaults to current)
        """
        directory = directory or self.current_directory
        if not directory:
            return

        directory = str(Path(directory).resolve())

        if directory not in self.directories:
            self.enter_directory(directory)

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        self.directories[directory].notes.append(f"[{timestamp}] {note}")

    def get_recent_commands(
        self,
        limit: int = 10,
        directory: Optional[str] = None
    ) -> List[str]:
        """
        Get recent commands for a directory.

        Args:
            limit: Maximum commands to return
            directory: Directory (defaults to current)

        Returns:
            List of recent commands
        """
        directory = directory or self.current_directory
        if not directory:
            return []

        directory = str(Path(directory).resolve())

        if directory not in self.directories:
            return []

        return self.directories[directory].last_commands[-limit:]

    def get_entry(self, directory: Optional[str] = None) -> Optional[DirectoryEntry]:
        """
        Get the directory entry.

        Args:
            directory: Directory (defaults to current)

        Returns:
            DirectoryEntry or None
        """
        directory = directory or self.current_directory
        if not directory:
            return None

        directory = str(Path(directory).resolve())
        return self.directories.get(directory)

    def get_frequent_directories(self, limit: int = 10) -> List[DirectoryEntry]:
        """
        Get most frequently accessed directories.

        Args:
            limit: Maximum directories to return

        Returns:
            List of DirectoryEntry sorted by access count
        """
        sorted_entries = sorted(
            self.directories.values(),
            key=lambda x: x.access_count,
            reverse=True
        )
        return sorted_entries[:limit]

    def to_dict(self) -> Dict[str, Any]:
        """Export to dictionary."""
        return {
            'current_directory': self.current_directory,
            'directories': {
                path: entry.to_dict()
                for path, entry in self.directories.items()
            }
        }
