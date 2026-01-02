"""
Baseline Manager for CODE_DEBUG
================================

Manages backup, restore, and comparison of project state for the
"DO NO HARM" debugging principle.

Features:
- Git stash integration (if available)
- File copy backup fallback
- Symbol table extraction
- Before/after comparison

Author: RAICA Development Team
Version: 1.0.0
"""

import asyncio
import hashlib
import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid

logger = logging.getLogger(__name__)


class BackupMethod(Enum):
    """Method used for backup."""
    GIT_STASH = auto()
    GIT_BRANCH = auto()
    FILE_COPY = auto()


@dataclass
class FileState:
    """State of a single file."""
    path: str
    content_hash: str
    size_bytes: int
    last_modified: str
    language: str

    @classmethod
    def from_path(cls, file_path: Path, project_root: Path) -> 'FileState':
        """Create FileState from a file path."""
        relative_path = str(file_path.relative_to(project_root))
        content = file_path.read_bytes()
        content_hash = hashlib.sha256(content).hexdigest()
        stat = file_path.stat()

        # Detect language from extension
        ext = file_path.suffix.lower()
        lang_map = {
            '.py': 'python',
            '.js': 'javascript',
            '.ts': 'typescript',
            '.jsx': 'javascript',
            '.tsx': 'typescript',
            '.html': 'html',
            '.css': 'css',
            '.json': 'json',
            '.yaml': 'yaml',
            '.yml': 'yaml',
            '.md': 'markdown',
        }
        language = lang_map.get(ext, 'unknown')

        return cls(
            path=relative_path,
            content_hash=content_hash,
            size_bytes=stat.st_size,
            last_modified=datetime.fromtimestamp(stat.st_mtime).isoformat(),
            language=language
        )


@dataclass
class SymbolInfo:
    """Information about an exported symbol."""
    name: str
    symbol_type: str  # 'function', 'class', 'variable', 'constant'
    file_path: str
    line_number: int
    signature: Optional[str] = None


@dataclass
class BaselineSnapshot:
    """Complete baseline state of a project."""
    id: str
    timestamp: str
    project_path: str
    files: Dict[str, FileState] = field(default_factory=dict)
    file_contents: Dict[str, str] = field(default_factory=dict)  # For files < max_size
    symbol_table: Dict[str, List[SymbolInfo]] = field(default_factory=dict)  # file -> symbols
    test_results: Optional[Dict[str, Any]] = None
    git_info: Optional[Dict[str, str]] = None  # commit, branch, has_changes
    backup_location: str = ""
    backup_method: str = ""  # 'git_stash', 'git_branch', 'file_copy'

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'id': self.id,
            'timestamp': self.timestamp,
            'project_path': self.project_path,
            'files': {k: v.__dict__ for k, v in self.files.items()},
            'file_contents': self.file_contents,
            'symbol_table': {
                k: [s.__dict__ for s in v]
                for k, v in self.symbol_table.items()
            },
            'test_results': self.test_results,
            'git_info': self.git_info,
            'backup_location': self.backup_location,
            'backup_method': self.backup_method,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'BaselineSnapshot':
        """Create from dictionary."""
        snapshot = cls(
            id=data['id'],
            timestamp=data['timestamp'],
            project_path=data['project_path'],
            backup_location=data.get('backup_location', ''),
            backup_method=data.get('backup_method', ''),
            test_results=data.get('test_results'),
            git_info=data.get('git_info'),
        )

        # Restore files
        for path, file_data in data.get('files', {}).items():
            snapshot.files[path] = FileState(**file_data)

        # Restore file contents
        snapshot.file_contents = data.get('file_contents', {})

        # Restore symbol table
        for path, symbols in data.get('symbol_table', {}).items():
            snapshot.symbol_table[path] = [SymbolInfo(**s) for s in symbols]

        return snapshot


@dataclass
class FileDiff:
    """Difference for a single file."""
    path: str
    change_type: str  # 'added', 'removed', 'modified'
    old_hash: Optional[str] = None
    new_hash: Optional[str] = None


@dataclass
class SymbolDiff:
    """Difference in symbols."""
    file_path: str
    added: List[str] = field(default_factory=list)
    removed: List[str] = field(default_factory=list)
    changed: List[str] = field(default_factory=list)


@dataclass
class DiffReport:
    """Comparison between two states."""
    files_added: List[str] = field(default_factory=list)
    files_removed: List[str] = field(default_factory=list)
    files_modified: List[str] = field(default_factory=list)
    file_diffs: List[FileDiff] = field(default_factory=list)
    symbol_diffs: List[SymbolDiff] = field(default_factory=list)
    symbols_added: Dict[str, List[str]] = field(default_factory=dict)
    symbols_removed: Dict[str, List[str]] = field(default_factory=dict)
    symbols_changed: Dict[str, List[str]] = field(default_factory=dict)

    @property
    def has_changes(self) -> bool:
        """Check if there are any changes."""
        return bool(
            self.files_added or
            self.files_removed or
            self.files_modified
        )

    @property
    def has_symbol_changes(self) -> bool:
        """Check if there are symbol changes."""
        return bool(
            self.symbols_added or
            self.symbols_removed or
            self.symbols_changed
        )


class BaselineManager:
    """
    Manages baseline capture, restore, and comparison.

    Supports:
    - Git stash (preferred if git available)
    - File copy backup (fallback)
    """

    # File extensions to include in baseline
    SOURCE_EXTENSIONS = {
        '.py', '.js', '.ts', '.jsx', '.tsx',
        '.html', '.css', '.json', '.yaml', '.yml',
        '.md', '.txt', '.sh', '.bat', '.sql'
    }

    # Directories to exclude
    EXCLUDE_DIRS = {
        '__pycache__', 'node_modules', '.git', '.venv', 'venv',
        'env', '.env', 'dist', 'build', '.pytest_cache',
        '.mypy_cache', '.tox', 'eggs', '*.egg-info',
        '.raica_backup'  # Our own backup directory
    }

    def __init__(
        self,
        project_dir: Path,
        max_file_size_kb: int = 500,
        backup_dir_name: str = '.raica_backup'
    ):
        """
        Initialize BaselineManager.

        Args:
            project_dir: Project directory to manage
            max_file_size_kb: Maximum file size to store contents (KB)
            backup_dir_name: Name of backup directory
        """
        self.project_dir = Path(project_dir).resolve()
        self.max_file_size = max_file_size_kb * 1024  # Convert to bytes
        self.backup_dir_name = backup_dir_name
        self.backup_dir = self.project_dir / backup_dir_name
        self._git_available: Optional[bool] = None

    def has_git(self) -> bool:
        """Check if project is a git repository."""
        if self._git_available is not None:
            return self._git_available

        try:
            result = subprocess.run(
                ['git', 'rev-parse', '--git-dir'],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                timeout=5
            )
            self._git_available = result.returncode == 0
        except (subprocess.SubprocessError, FileNotFoundError):
            self._git_available = False

        return self._git_available

    def _get_git_info(self) -> Optional[Dict[str, str]]:
        """Get current git information."""
        if not self.has_git():
            return None

        try:
            # Get current commit
            commit_result = subprocess.run(
                ['git', 'rev-parse', 'HEAD'],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                timeout=5
            )
            commit = commit_result.stdout.strip() if commit_result.returncode == 0 else None

            # Get current branch
            branch_result = subprocess.run(
                ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                timeout=5
            )
            branch = branch_result.stdout.strip() if branch_result.returncode == 0 else None

            # Check for uncommitted changes
            status_result = subprocess.run(
                ['git', 'status', '--porcelain'],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                timeout=5
            )
            has_changes = bool(status_result.stdout.strip())

            return {
                'commit': commit,
                'branch': branch,
                'has_uncommitted_changes': str(has_changes)
            }
        except subprocess.SubprocessError:
            return None

    def _should_include_file(self, file_path: Path) -> bool:
        """Check if file should be included in baseline."""
        # Check extension
        if file_path.suffix.lower() not in self.SOURCE_EXTENSIONS:
            return False

        # Check if in excluded directory
        for part in file_path.parts:
            if part in self.EXCLUDE_DIRS:
                return False
            # Handle glob patterns
            for exclude in self.EXCLUDE_DIRS:
                if '*' in exclude and part.endswith(exclude.replace('*', '')):
                    return False

        return True

    def _get_source_files(self) -> List[Path]:
        """Get all source files in project."""
        source_files = []

        for file_path in self.project_dir.rglob('*'):
            if file_path.is_file() and self._should_include_file(file_path):
                source_files.append(file_path)

        return source_files

    def _extract_symbols_python(self, content: str, file_path: str) -> List[SymbolInfo]:
        """Extract symbols from Python code."""
        import ast
        symbols = []

        try:
            tree = ast.parse(content)

            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    # Get function signature
                    args = [a.arg for a in node.args.args]
                    sig = f"({', '.join(args)})"
                    symbols.append(SymbolInfo(
                        name=node.name,
                        symbol_type='function',
                        file_path=file_path,
                        line_number=node.lineno,
                        signature=sig
                    ))
                elif isinstance(node, ast.AsyncFunctionDef):
                    args = [a.arg for a in node.args.args]
                    sig = f"async ({', '.join(args)})"
                    symbols.append(SymbolInfo(
                        name=node.name,
                        symbol_type='async_function',
                        file_path=file_path,
                        line_number=node.lineno,
                        signature=sig
                    ))
                elif isinstance(node, ast.ClassDef):
                    symbols.append(SymbolInfo(
                        name=node.name,
                        symbol_type='class',
                        file_path=file_path,
                        line_number=node.lineno
                    ))
        except SyntaxError:
            logger.warning(f"Could not parse Python file: {file_path}")

        return symbols

    def _extract_symbols_js(self, content: str, file_path: str) -> List[SymbolInfo]:
        """Extract symbols from JavaScript/TypeScript code."""
        import re
        symbols = []

        # Function declarations
        func_pattern = r'(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\('
        for match in re.finditer(func_pattern, content):
            line_num = content[:match.start()].count('\n') + 1
            symbols.append(SymbolInfo(
                name=match.group(1),
                symbol_type='function',
                file_path=file_path,
                line_number=line_num
            ))

        # Arrow functions (const name = () => {})
        arrow_pattern = r'(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\([^)]*\)\s*=>'
        for match in re.finditer(arrow_pattern, content):
            line_num = content[:match.start()].count('\n') + 1
            symbols.append(SymbolInfo(
                name=match.group(1),
                symbol_type='function',
                file_path=file_path,
                line_number=line_num
            ))

        # Class declarations
        class_pattern = r'(?:export\s+)?class\s+(\w+)'
        for match in re.finditer(class_pattern, content):
            line_num = content[:match.start()].count('\n') + 1
            symbols.append(SymbolInfo(
                name=match.group(1),
                symbol_type='class',
                file_path=file_path,
                line_number=line_num
            ))

        return symbols

    def _extract_symbols(self, content: str, file_path: str, language: str) -> List[SymbolInfo]:
        """Extract symbols from source code."""
        if language == 'python':
            return self._extract_symbols_python(content, file_path)
        elif language in ('javascript', 'typescript'):
            return self._extract_symbols_js(content, file_path)
        return []

    async def capture_baseline(self) -> BaselineSnapshot:
        """
        Capture full project baseline before changes.

        Returns:
            BaselineSnapshot with complete project state
        """
        logger.info(f"Capturing baseline for: {self.project_dir}")

        snapshot = BaselineSnapshot(
            id=str(uuid.uuid4())[:8],
            timestamp=datetime.now().isoformat(),
            project_path=str(self.project_dir)
        )

        # Get git info
        snapshot.git_info = self._get_git_info()

        # Capture all source files
        source_files = self._get_source_files()
        logger.info(f"Found {len(source_files)} source files")

        for file_path in source_files:
            try:
                # Create FileState
                file_state = FileState.from_path(file_path, self.project_dir)
                snapshot.files[file_state.path] = file_state

                # Store content if small enough
                if file_state.size_bytes <= self.max_file_size:
                    content = file_path.read_text(errors='replace')
                    snapshot.file_contents[file_state.path] = content

                    # Extract symbols
                    symbols = self._extract_symbols(
                        content,
                        file_state.path,
                        file_state.language
                    )
                    if symbols:
                        snapshot.symbol_table[file_state.path] = symbols

            except Exception as e:
                logger.warning(f"Could not process file {file_path}: {e}")

        # Create backup
        if self.has_git():
            # Use git stash
            backup_id = await self._git_stash()
            if backup_id:
                snapshot.backup_method = 'git_stash'
                snapshot.backup_location = backup_id
                logger.info(f"Created git stash: {backup_id}")
            else:
                # Fallback to file copy
                backup_path = await self._copy_files_to_backup(snapshot.id)
                snapshot.backup_method = 'file_copy'
                snapshot.backup_location = backup_path
        else:
            # Use file copy
            backup_path = await self._copy_files_to_backup(snapshot.id)
            snapshot.backup_method = 'file_copy'
            snapshot.backup_location = backup_path
            logger.info(f"Created file backup: {backup_path}")

        # Save snapshot metadata
        snapshot_path = self.backup_dir / f"snapshot_{snapshot.id}.json"
        self.backup_dir.mkdir(exist_ok=True)
        snapshot_path.write_text(json.dumps(snapshot.to_dict(), indent=2))

        logger.info(f"Baseline captured: {len(snapshot.files)} files, "
                   f"{sum(len(s) for s in snapshot.symbol_table.values())} symbols")

        return snapshot

    async def _git_stash(self) -> Optional[str]:
        """Create a git stash. Returns stash reference or None."""
        try:
            # Create stash with message
            stash_msg = f"raica_baseline_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            result = subprocess.run(
                ['git', 'stash', 'push', '-m', stash_msg, '--include-untracked'],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                # Get stash reference
                list_result = subprocess.run(
                    ['git', 'stash', 'list'],
                    cwd=self.project_dir,
                    capture_output=True,
                    text=True,
                    timeout=5
                )

                for line in list_result.stdout.split('\n'):
                    if stash_msg in line:
                        # Extract stash reference (stash@{0})
                        return line.split(':')[0]

                return 'stash@{0}'  # Default to most recent

            return None
        except subprocess.SubprocessError as e:
            logger.warning(f"Git stash failed: {e}")
            return None

    async def _copy_files_to_backup(self, backup_id: str) -> str:
        """Copy files to backup directory. Returns backup path."""
        backup_path = self.backup_dir / backup_id
        backup_path.mkdir(parents=True, exist_ok=True)

        source_files = self._get_source_files()

        for file_path in source_files:
            try:
                relative_path = file_path.relative_to(self.project_dir)
                dest_path = backup_path / relative_path
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(file_path, dest_path)
            except Exception as e:
                logger.warning(f"Could not backup {file_path}: {e}")

        return str(backup_path)

    async def restore_baseline(self, snapshot: BaselineSnapshot) -> bool:
        """
        Restore project to baseline state (rollback).

        Args:
            snapshot: Baseline snapshot to restore

        Returns:
            True if restoration successful
        """
        logger.info(f"Restoring baseline: {snapshot.id}")

        try:
            if snapshot.backup_method == 'git_stash':
                return await self._restore_git_stash(snapshot.backup_location)
            elif snapshot.backup_method == 'file_copy':
                return await self._restore_from_backup(snapshot.backup_location)
            else:
                logger.error(f"Unknown backup method: {snapshot.backup_method}")
                return False
        except Exception as e:
            logger.error(f"Restoration failed: {e}")
            return False

    async def _restore_git_stash(self, stash_ref: str) -> bool:
        """Restore from git stash."""
        try:
            # First, reset any changes
            subprocess.run(
                ['git', 'checkout', '.'],
                cwd=self.project_dir,
                capture_output=True,
                timeout=30
            )

            # Clean untracked files
            subprocess.run(
                ['git', 'clean', '-fd'],
                cwd=self.project_dir,
                capture_output=True,
                timeout=30
            )

            # Pop the stash
            result = subprocess.run(
                ['git', 'stash', 'pop', stash_ref],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                timeout=30
            )

            return result.returncode == 0
        except subprocess.SubprocessError as e:
            logger.error(f"Git stash restore failed: {e}")
            return False

    async def _restore_from_backup(self, backup_path: str) -> bool:
        """Restore from file backup."""
        backup_dir = Path(backup_path)

        if not backup_dir.exists():
            logger.error(f"Backup directory not found: {backup_path}")
            return False

        try:
            # Copy all files back
            for file_path in backup_dir.rglob('*'):
                if file_path.is_file():
                    relative_path = file_path.relative_to(backup_dir)
                    dest_path = self.project_dir / relative_path
                    dest_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(file_path, dest_path)

            return True
        except Exception as e:
            logger.error(f"File restore failed: {e}")
            return False

    def compare_with_baseline(self, snapshot: BaselineSnapshot) -> DiffReport:
        """
        Compare current state with baseline.

        Args:
            snapshot: Baseline to compare against

        Returns:
            DiffReport with all changes
        """
        report = DiffReport()

        # Get current files
        current_files = {}
        for file_path in self._get_source_files():
            try:
                file_state = FileState.from_path(file_path, self.project_dir)
                current_files[file_state.path] = file_state
            except Exception as e:
                logger.warning(f"Could not process {file_path}: {e}")

        baseline_paths = set(snapshot.files.keys())
        current_paths = set(current_files.keys())

        # Files added
        report.files_added = list(current_paths - baseline_paths)

        # Files removed
        report.files_removed = list(baseline_paths - current_paths)

        # Files modified
        for path in baseline_paths & current_paths:
            baseline_file = snapshot.files[path]
            current_file = current_files[path]

            if baseline_file.content_hash != current_file.content_hash:
                report.files_modified.append(path)
                report.file_diffs.append(FileDiff(
                    path=path,
                    change_type='modified',
                    old_hash=baseline_file.content_hash,
                    new_hash=current_file.content_hash
                ))

        # Compare symbols
        for path in report.files_modified:
            if path in snapshot.symbol_table:
                baseline_symbols = {s.name for s in snapshot.symbol_table[path]}

                # Extract current symbols
                if path in current_files:
                    file_path = self.project_dir / path
                    if file_path.exists():
                        content = file_path.read_text(errors='replace')
                        current_symbol_list = self._extract_symbols(
                            content, path, current_files[path].language
                        )
                        current_symbols = {s.name for s in current_symbol_list}

                        added = list(current_symbols - baseline_symbols)
                        removed = list(baseline_symbols - current_symbols)

                        if added:
                            report.symbols_added[path] = added
                        if removed:
                            report.symbols_removed[path] = removed

        return report

    def get_modified_files(self, snapshot: BaselineSnapshot) -> List[str]:
        """Get list of files modified since baseline."""
        diff = self.compare_with_baseline(snapshot)
        return diff.files_modified + diff.files_added

    def cleanup_backup(self, snapshot: BaselineSnapshot) -> None:
        """Clean up backup files after successful completion."""
        try:
            if snapshot.backup_method == 'git_stash':
                # Drop the stash
                subprocess.run(
                    ['git', 'stash', 'drop', snapshot.backup_location],
                    cwd=self.project_dir,
                    capture_output=True,
                    timeout=10
                )
            elif snapshot.backup_method == 'file_copy':
                # Remove backup directory
                backup_path = Path(snapshot.backup_location)
                if backup_path.exists():
                    shutil.rmtree(backup_path)

            # Remove snapshot file
            snapshot_path = self.backup_dir / f"snapshot_{snapshot.id}.json"
            if snapshot_path.exists():
                snapshot_path.unlink()

            logger.info(f"Cleaned up backup: {snapshot.id}")
        except Exception as e:
            logger.warning(f"Cleanup failed: {e}")
