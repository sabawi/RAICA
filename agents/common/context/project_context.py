"""
Project Context
===============

Project-specific context including goals, patterns, and conventions.
Stored in .raica/ directory within each project.

Storage: .raica/project_context.yaml

Enhanced with File Structure Tracking (v2.3):
- FileEntry: Tracks individual files with type, size, and symbols
- DirectoryTree: Visual tree representation for LLM prompts
- scan_file_structure(): Scans project and extracts Python symbols via AST
"""

import ast
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import yaml

logger = logging.getLogger(__name__)


@dataclass
class ProjectGoal:
    """A project goal or objective."""
    description: str
    priority: str = "medium"  # low, medium, high, critical
    status: str = "active"  # active, completed, paused, abandoned
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    completed_at: Optional[str] = None
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'description': self.description,
            'priority': self.priority,
            'status': self.status,
            'created_at': self.created_at,
            'completed_at': self.completed_at,
            'notes': self.notes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ProjectGoal':
        return cls(
            description=data.get('description', ''),
            priority=data.get('priority', 'medium'),
            status=data.get('status', 'active'),
            created_at=data.get('created_at', datetime.now().isoformat()),
            completed_at=data.get('completed_at'),
            notes=data.get('notes', []),
        )


@dataclass
class ProjectConvention:
    """A project coding convention or pattern."""
    name: str
    description: str
    examples: List[str] = field(default_factory=list)
    anti_patterns: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'name': self.name,
            'description': self.description,
            'examples': self.examples,
            'anti_patterns': self.anti_patterns,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ProjectConvention':
        return cls(
            name=data.get('name', ''),
            description=data.get('description', ''),
            examples=data.get('examples', []),
            anti_patterns=data.get('anti_patterns', []),
        )


@dataclass
class KeyDecision:
    """A key decision made for the project."""
    description: str
    rationale: str
    alternatives_considered: List[str] = field(default_factory=list)
    decided_at: str = field(default_factory=lambda: datetime.now().isoformat())
    decided_by: str = "user"

    def to_dict(self) -> Dict[str, Any]:
        return {
            'description': self.description,
            'rationale': self.rationale,
            'alternatives_considered': self.alternatives_considered,
            'decided_at': self.decided_at,
            'decided_by': self.decided_by,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'KeyDecision':
        return cls(
            description=data.get('description', ''),
            rationale=data.get('rationale', ''),
            alternatives_considered=data.get('alternatives_considered', []),
            decided_at=data.get('decided_at', datetime.now().isoformat()),
            decided_by=data.get('decided_by', 'user'),
        )


@dataclass
class FileEntry:
    """
    Represents a file in the project structure.

    Used to track files and their key attributes for LLM context injection.
    Prevents hallucination by giving the LLM accurate file information.
    """
    path: str                           # Relative path from project root
    file_type: str = "unknown"          # python, javascript, html, config, etc.
    size: int = 0                       # File size in bytes
    symbols: List[str] = field(default_factory=list)   # Exported classes/functions
    imports: List[str] = field(default_factory=list)   # Import statements
    last_modified: Optional[float] = None  # Timestamp

    def to_dict(self) -> Dict[str, Any]:
        return {
            'path': self.path,
            'file_type': self.file_type,
            'size': self.size,
            'symbols': self.symbols,
            'imports': self.imports,
            'last_modified': self.last_modified,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'FileEntry':
        return cls(
            path=data.get('path', ''),
            file_type=data.get('file_type', 'unknown'),
            size=data.get('size', 0),
            symbols=data.get('symbols', []),
            imports=data.get('imports', []),
            last_modified=data.get('last_modified'),
        )


@dataclass
class DirectoryTree:
    """
    Represents the project directory structure as a visual tree.

    Provides a formatted string representation that can be injected
    into LLM prompts to give accurate project structure context.
    """
    root_name: str
    tree_string: str = ""
    file_count: int = 0
    directory_count: int = 0
    total_size: int = 0
    scanned_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'root_name': self.root_name,
            'tree_string': self.tree_string,
            'file_count': self.file_count,
            'directory_count': self.directory_count,
            'total_size': self.total_size,
            'scanned_at': self.scanned_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DirectoryTree':
        return cls(
            root_name=data.get('root_name', ''),
            tree_string=data.get('tree_string', ''),
            file_count=data.get('file_count', 0),
            directory_count=data.get('directory_count', 0),
            total_size=data.get('total_size', 0),
            scanned_at=data.get('scanned_at'),
        )

    @staticmethod
    def generate_tree(
        root_dir: Path,
        max_depth: int = 4,
        exclude_patterns: Optional[Set[str]] = None
    ) -> 'DirectoryTree':
        """
        Generate a visual tree representation of a directory.

        Args:
            root_dir: Root directory to scan
            max_depth: Maximum depth to traverse
            exclude_patterns: Set of directory/file names to exclude

        Returns:
            DirectoryTree with visual representation
        """
        if exclude_patterns is None:
            exclude_patterns = {
                '.git', '__pycache__', 'node_modules', '.venv', 'venv',
                '.tox', '.pytest_cache', '.mypy_cache', 'dist', 'build',
                '.eggs', '*.egg-info', '.raica'
            }

        lines = [f"{root_dir.name}/"]
        file_count = 0
        dir_count = 0
        total_size = 0

        def _add_entries(path: Path, prefix: str, depth: int):
            nonlocal file_count, dir_count, total_size

            if depth > max_depth:
                return

            try:
                entries = sorted(path.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
            except PermissionError:
                return

            # Filter out excluded patterns
            filtered = []
            for entry in entries:
                skip = False
                for pattern in exclude_patterns:
                    if pattern.startswith('*'):
                        if entry.name.endswith(pattern[1:]):
                            skip = True
                            break
                    elif entry.name == pattern:
                        skip = True
                        break
                if not skip:
                    filtered.append(entry)

            for i, entry in enumerate(filtered):
                is_last = (i == len(filtered) - 1)
                connector = "└── " if is_last else "├── "

                if entry.is_dir():
                    dir_count += 1
                    lines.append(f"{prefix}{connector}{entry.name}/")
                    new_prefix = prefix + ("    " if is_last else "│   ")
                    _add_entries(entry, new_prefix, depth + 1)
                else:
                    file_count += 1
                    try:
                        size = entry.stat().st_size
                        total_size += size
                    except (OSError, PermissionError):
                        size = 0
                    lines.append(f"{prefix}{connector}{entry.name}")

        _add_entries(root_dir, "", 1)

        return DirectoryTree(
            root_name=root_dir.name,
            tree_string="\n".join(lines),
            file_count=file_count,
            directory_count=dir_count,
            total_size=total_size,
            scanned_at=datetime.now().isoformat()
        )


class ProjectContext:
    """
    Manages project-specific context.
    Stored in .raica/project_context.yaml within each project.
    """

    CONTEXT_DIR = ".raica"
    CONTEXT_FILE = "project_context.yaml"

    def __init__(self, project_dir: Optional[Path] = None):
        """
        Initialize ProjectContext.

        Args:
            project_dir: Root directory of the project
        """
        self.project_dir = project_dir or Path.cwd()
        self.context_dir = self.project_dir / self.CONTEXT_DIR
        self.context_file = self.context_dir / self.CONTEXT_FILE

        # Project metadata
        self.project_name: str = self.project_dir.name
        self.project_description: str = ""
        self.project_type: Optional[str] = None  # python, node, etc.
        self.created_at: Optional[str] = None
        self.last_updated: Optional[str] = None

        # Goals and planning
        self.goals: List[ProjectGoal] = []
        self.milestones: List[str] = []

        # Conventions and patterns
        self.conventions: List[ProjectConvention] = []
        self.tech_stack: List[str] = []
        self.dependencies_notes: Dict[str, str] = {}

        # Key decisions
        self.decisions: List[KeyDecision] = []

        # Documentation notes
        self.architecture_notes: str = ""
        self.setup_notes: str = ""
        self.known_issues: List[str] = []

        # Custom metadata
        self.custom_metadata: Dict[str, Any] = {}

        # File structure tracking (v2.3)
        self.file_entries: Dict[str, FileEntry] = {}  # path -> FileEntry
        self.directory_tree: Optional[DirectoryTree] = None
        self.key_file_contents: Dict[str, str] = {}  # path -> content (README, requirements.txt, etc.)
        self.last_scan_time: Optional[float] = None
        self._scan_stale_seconds: int = 300  # 5 minutes default

        # Recent changes history (v2.4) - tracks last 10 changes for context
        self.recent_changes: List[Dict[str, Any]] = []

        # Auto-approve settings for step categories
        # These control which step types skip approval prompts
        self.auto_approve_settings: Dict[str, bool] = {
            # Passive/read-only steps - auto-approve by default
            'investigate': True,     # INVESTIGATE steps (read-only queries)
            'verify': True,          # VERIFY steps (checking results)
            'inform_user': True,     # INFORM_USER steps (just displaying info)
            # Active steps - require approval by default
            'execute': False,        # EXECUTE steps (running commands)
            'install': False,        # INSTALL steps (installing packages)
            'configure': False,      # CONFIGURE steps (changing configs)
            'code_generate': False,  # CODE_GENERATE steps (creating files)
        }

        # Command categories that can be auto-approved
        self.auto_approve_commands: Dict[str, bool] = {
            'read_only': True,       # ls, cat, grep, find, etc.
            'file_create': False,    # touch, mkdir, etc.
            'file_modify': False,    # sed, awk, edit, etc.
            'file_delete': False,    # rm, rmdir, etc.
            'package_install': False,# pip, npm, apt install, etc.
            'git_operations': False, # git commit, push, etc.
        }

    def load(self) -> bool:
        """Load project context from disk."""
        if not self.context_file.exists():
            logger.debug(f"No project context found at {self.context_file}")
            return False

        try:
            with open(self.context_file, 'r') as f:
                data = yaml.safe_load(f)

            if not data:
                return False

            self._from_dict(data)
            logger.info(f"Loaded project context for: {self.project_name}")
            return True

        except Exception as e:
            logger.warning(f"Failed to load project context: {e}")
            return False

    def save(self) -> bool:
        """Save project context to disk."""
        try:
            self.context_dir.mkdir(parents=True, exist_ok=True)
            self.last_updated = datetime.now().isoformat()

            with open(self.context_file, 'w') as f:
                yaml.dump(self.to_dict(), f, default_flow_style=False, sort_keys=False)

            logger.debug(f"Saved project context to {self.context_file}")
            return True

        except Exception as e:
            logger.warning(f"Failed to save project context: {e}")
            return False

    def initialize(
        self,
        name: Optional[str] = None,
        description: str = "",
        project_type: Optional[str] = None
    ) -> None:
        """
        Initialize a new project context.

        Args:
            name: Project name (defaults to directory name)
            description: Project description
            project_type: Type of project (python, node, etc.)
        """
        self.project_name = name or self.project_dir.name
        self.project_description = description
        self.project_type = project_type
        self.created_at = datetime.now().isoformat()
        self.save()

    def add_goal(
        self,
        description: str,
        priority: str = "medium"
    ) -> ProjectGoal:
        """
        Add a project goal.

        Args:
            description: Goal description
            priority: Priority level (low, medium, high, critical)

        Returns:
            Created ProjectGoal
        """
        goal = ProjectGoal(description=description, priority=priority)
        self.goals.append(goal)
        return goal

    def complete_goal(self, index: int) -> bool:
        """
        Mark a goal as completed.

        Args:
            index: Index of the goal to complete

        Returns:
            True if successful
        """
        if 0 <= index < len(self.goals):
            self.goals[index].status = "completed"
            self.goals[index].completed_at = datetime.now().isoformat()
            return True
        return False

    def add_convention(
        self,
        name: str,
        description: str,
        examples: Optional[List[str]] = None
    ) -> ProjectConvention:
        """
        Add a coding convention.

        Args:
            name: Convention name
            description: What the convention means
            examples: Example code snippets

        Returns:
            Created ProjectConvention
        """
        convention = ProjectConvention(
            name=name,
            description=description,
            examples=examples or []
        )
        self.conventions.append(convention)
        return convention

    def add_decision(
        self,
        description: str,
        rationale: str,
        alternatives: Optional[List[str]] = None
    ) -> KeyDecision:
        """
        Record a key decision.

        Args:
            description: What was decided
            rationale: Why it was decided
            alternatives: Other options considered

        Returns:
            Created KeyDecision
        """
        decision = KeyDecision(
            description=description,
            rationale=rationale,
            alternatives_considered=alternatives or []
        )
        self.decisions.append(decision)
        return decision

    def add_known_issue(self, issue: str) -> None:
        """Add a known issue."""
        timestamp = datetime.now().strftime("%Y-%m-%d")
        self.known_issues.append(f"[{timestamp}] {issue}")

    def should_auto_approve_step(self, step_type: str) -> bool:
        """
        Check if a step type should be auto-approved.

        Args:
            step_type: Step type name (e.g., 'investigate', 'execute')

        Returns:
            True if this step type should skip approval
        """
        step_type_lower = step_type.lower()
        return self.auto_approve_settings.get(step_type_lower, False)

    def should_auto_approve_command(self, command_category: str) -> bool:
        """
        Check if a command category should be auto-approved.

        Args:
            command_category: Category name (e.g., 'read_only', 'file_create')

        Returns:
            True if this command category should skip approval
        """
        return self.auto_approve_commands.get(command_category, False)

    def set_auto_approve_step(self, step_type: str, auto_approve: bool) -> None:
        """
        Set auto-approve setting for a step type.

        Args:
            step_type: Step type name
            auto_approve: Whether to auto-approve
        """
        self.auto_approve_settings[step_type.lower()] = auto_approve
        self.save()

    def set_auto_approve_command(self, command_category: str, auto_approve: bool) -> None:
        """
        Set auto-approve setting for a command category.

        Args:
            command_category: Category name
            auto_approve: Whether to auto-approve
        """
        self.auto_approve_commands[command_category] = auto_approve
        self.save()

    def get_active_goals(self) -> List[ProjectGoal]:
        """Get all active goals."""
        return [g for g in self.goals if g.status == "active"]

    def get_summary(self) -> str:
        """Get a summary for LLM prompts."""
        lines = []

        if self.project_description:
            lines.append(f"Project: {self.project_name}")
            lines.append(f"Description: {self.project_description}")

        if self.project_type:
            lines.append(f"Type: {self.project_type}")

        if self.tech_stack:
            lines.append(f"Stack: {', '.join(self.tech_stack)}")

        active_goals = self.get_active_goals()
        if active_goals:
            goals_str = "; ".join([g.description for g in active_goals[:3]])
            lines.append(f"Active goals: {goals_str}")

        if self.conventions:
            conv_names = [c.name for c in self.conventions[:5]]
            lines.append(f"Conventions: {', '.join(conv_names)}")

        if self.known_issues:
            lines.append(f"Known issues: {len(self.known_issues)}")

        return '\n'.join(lines) if lines else ""

    # =========================================================================
    # FILE STRUCTURE TRACKING (v2.3)
    # =========================================================================

    def scan_file_structure(
        self,
        max_depth: int = 4,
        extract_symbols: bool = True,
        force: bool = False
    ) -> bool:
        """
        Scan the project file structure and extract symbols.

        Args:
            max_depth: Maximum directory depth to scan
            extract_symbols: If True, extract Python symbols via AST
            force: If True, rescan even if not stale

        Returns:
            True if scan was performed, False if skipped
        """
        if not force and not self.needs_rescan():
            logger.debug("File structure scan skipped (not stale)")
            return False

        logger.info(f"Scanning file structure: {self.project_dir}")

        # Generate directory tree
        self.directory_tree = DirectoryTree.generate_tree(
            self.project_dir,
            max_depth=max_depth
        )

        # Scan files and extract information
        self.file_entries = {}
        exclude_dirs = {
            '.git', '__pycache__', 'node_modules', '.venv', 'venv',
            '.tox', '.pytest_cache', '.mypy_cache', 'dist', 'build',
            '.eggs', '.raica'
        }

        # Safety limits to prevent hanging on huge projects
        max_files_to_scan = 5000
        files_scanned = 0

        try:
            # Use rglob but be careful about symlinks and large projects
            for file_path in self.project_dir.rglob('*'):
                # Check file limit
                if files_scanned >= max_files_to_scan:
                    logger.warning(f"Reached scan limit of {max_files_to_scan} files - stopping scan")
                    break

                # Skip if not a regular file (avoid symlinks, devices, etc)
                try:
                    if not file_path.is_file() or file_path.is_symlink():
                        continue
                except (OSError, PermissionError):
                    continue

                # Skip excluded directories
                if any(excluded in file_path.parts for excluded in exclude_dirs):
                    continue

                files_scanned += 1

                try:
                    relative_path = str(file_path.relative_to(self.project_dir))
                except ValueError:
                    # File is not relative to project_dir (shouldn't happen but be safe)
                    continue

                file_type = self._detect_file_type(file_path)

                try:
                    stat = file_path.stat()
                    size = stat.st_size
                    mtime = stat.st_mtime
                except (OSError, PermissionError):
                    size = 0
                    mtime = None

                entry = FileEntry(
                    path=relative_path,
                    file_type=file_type,
                    size=size,
                    last_modified=mtime
                )

                # Extract symbols for Python files
                if extract_symbols and file_type == 'python' and size < 500000:
                    try:
                        symbols, imports = self._extract_python_symbols(file_path)
                        entry.symbols = symbols
                        entry.imports = imports
                    except Exception as e:
                        logger.debug(f"Failed to extract symbols from {relative_path}: {e}")

                self.file_entries[relative_path] = entry

        except Exception as e:
            logger.error(f"Error during file structure scan: {e}")
            # Continue with whatever we scanned so far

        # Load key file contents
        self._load_key_file_contents()

        self.last_scan_time = time.time()
        logger.info(f"Scanned {len(self.file_entries)} files")
        return True

    def _detect_file_type(self, file_path: Path) -> str:
        """Detect file type from extension."""
        ext_map = {
            '.py': 'python',
            '.js': 'javascript',
            '.ts': 'typescript',
            '.jsx': 'javascript',
            '.tsx': 'typescript',
            '.html': 'html',
            '.htm': 'html',
            '.css': 'css',
            '.scss': 'css',
            '.json': 'json',
            '.yaml': 'config',
            '.yml': 'config',
            '.toml': 'config',
            '.ini': 'config',
            '.cfg': 'config',
            '.md': 'markdown',
            '.txt': 'text',
            '.sh': 'shell',
            '.bash': 'shell',
            '.sql': 'sql',
            '.go': 'go',
            '.rs': 'rust',
            '.java': 'java',
            '.rb': 'ruby',
            '.php': 'php',
        }
        suffix = file_path.suffix.lower()
        return ext_map.get(suffix, 'unknown')

    def _extract_python_symbols(self, file_path: Path) -> tuple:
        """
        Extract exported symbols and imports from a Python file using AST.

        Args:
            file_path: Path to Python file

        Returns:
            Tuple of (symbols list, imports list)
        """
        symbols = []
        imports = []

        try:
            content = file_path.read_text(encoding='utf-8', errors='ignore')
            tree = ast.parse(content, filename=str(file_path))
        except (SyntaxError, UnicodeDecodeError) as e:
            logger.debug(f"Could not parse {file_path}: {e}")
            return symbols, imports

        for node in ast.walk(tree):
            # Extract class definitions
            if isinstance(node, ast.ClassDef):
                # Only include top-level classes (not nested)
                symbols.append(f"class {node.name}")

            # Extract function definitions
            elif isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                # Skip private functions (start with _)
                if not node.name.startswith('_'):
                    symbols.append(f"def {node.name}")

            # Extract imports
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)

            elif isinstance(node, ast.ImportFrom):
                module = node.module or ''
                for alias in node.names:
                    imports.append(f"{module}.{alias.name}" if module else alias.name)

        # Limit to prevent context bloat
        return symbols[:50], imports[:30]

    def _load_key_file_contents(self) -> None:
        """Load contents of key configuration files."""
        key_files = [
            'README.md',
            'readme.md',
            'requirements.txt',
            'pyproject.toml',
            'package.json',
            'setup.py',
            'setup.cfg',
            '.env.example',
            'Makefile',
            'Dockerfile',
            'docker-compose.yml',
        ]

        self.key_file_contents = {}

        for filename in key_files:
            file_path = self.project_dir / filename
            if file_path.exists() and file_path.is_file():
                try:
                    # Limit content size to prevent context bloat
                    content = file_path.read_text(encoding='utf-8', errors='ignore')
                    if len(content) > 5000:
                        content = content[:5000] + "\n... (truncated)"
                    self.key_file_contents[filename] = content
                except Exception as e:
                    logger.debug(f"Could not read {filename}: {e}")

    def needs_rescan(self) -> bool:
        """
        Check if the file structure needs to be rescanned.

        Returns:
            True if scan is stale or never performed
        """
        if self.last_scan_time is None:
            return True

        elapsed = time.time() - self.last_scan_time
        return elapsed > self._scan_stale_seconds

    def get_file_structure_context(self, include_symbols: bool = True) -> str:
        """
        Get formatted file structure context for LLM prompts.

        Args:
            include_symbols: Whether to include extracted symbols

        Returns:
            Formatted string for LLM context injection
        """
        lines = []

        # Directory tree
        if self.directory_tree and self.directory_tree.tree_string:
            lines.append("=== PROJECT FILE STRUCTURE ===")
            lines.append(self.directory_tree.tree_string)
            lines.append(f"\nTotal: {self.directory_tree.file_count} files, "
                        f"{self.directory_tree.directory_count} directories")
            lines.append("")

        # Key files summary
        if self.file_entries:
            # Group by type
            by_type: Dict[str, List[str]] = {}
            for path, entry in self.file_entries.items():
                file_type = entry.file_type
                if file_type not in by_type:
                    by_type[file_type] = []
                by_type[file_type].append(path)

            lines.append("=== FILES BY TYPE ===")
            for file_type in sorted(by_type.keys()):
                paths = by_type[file_type]
                lines.append(f"{file_type}: {len(paths)} files")
                # Show first few files of each type
                for path in sorted(paths)[:5]:
                    lines.append(f"  - {path}")
                if len(paths) > 5:
                    lines.append(f"  ... and {len(paths) - 5} more")
            lines.append("")

        # Symbols for Python files
        if include_symbols and self.file_entries:
            python_files = [
                (path, entry) for path, entry in self.file_entries.items()
                if entry.file_type == 'python' and entry.symbols
            ]
            if python_files:
                lines.append("=== PYTHON SYMBOLS ===")
                for path, entry in sorted(python_files, key=lambda x: x[0])[:10]:
                    lines.append(f"{path}:")
                    for symbol in entry.symbols[:10]:
                        lines.append(f"  {symbol}")
                    if len(entry.symbols) > 10:
                        lines.append(f"  ... and {len(entry.symbols) - 10} more")
                lines.append("")

        return "\n".join(lines)

    def get_files_by_type(self, file_type: str) -> List[str]:
        """Get all file paths of a specific type."""
        return [
            path for path, entry in self.file_entries.items()
            if entry.file_type == file_type
        ]

    def get_file_entry(self, path: str) -> Optional[FileEntry]:
        """Get a specific file entry by path."""
        return self.file_entries.get(path)

    def to_dict(self) -> Dict[str, Any]:
        """Export to dictionary."""
        return {
            'project_name': self.project_name,
            'project_description': self.project_description,
            'project_type': self.project_type,
            'created_at': self.created_at,
            'last_updated': self.last_updated,
            'goals': [g.to_dict() for g in self.goals],
            'milestones': self.milestones,
            'conventions': [c.to_dict() for c in self.conventions],
            'tech_stack': self.tech_stack,
            'dependencies_notes': self.dependencies_notes,
            'decisions': [d.to_dict() for d in self.decisions],
            'architecture_notes': self.architecture_notes,
            'setup_notes': self.setup_notes,
            'known_issues': self.known_issues,
            'custom_metadata': self.custom_metadata,
            'auto_approve_settings': self.auto_approve_settings,
            'auto_approve_commands': self.auto_approve_commands,
            # File structure tracking (v2.3)
            'file_entries': {
                path: entry.to_dict() for path, entry in self.file_entries.items()
            },
            'directory_tree': self.directory_tree.to_dict() if self.directory_tree else None,
            'key_file_contents': self.key_file_contents,
            'last_scan_time': self.last_scan_time,
            # Recent changes history (v2.4)
            'recent_changes': self.recent_changes,
        }

    def _from_dict(self, data: Dict[str, Any]) -> None:
        """Restore from dictionary."""
        self.project_name = data.get('project_name', self.project_dir.name)
        self.project_description = data.get('project_description', '')
        self.project_type = data.get('project_type')
        self.created_at = data.get('created_at')
        self.last_updated = data.get('last_updated')

        self.goals = [
            ProjectGoal.from_dict(g) for g in data.get('goals', [])
        ]
        self.milestones = data.get('milestones', [])

        self.conventions = [
            ProjectConvention.from_dict(c) for c in data.get('conventions', [])
        ]
        self.tech_stack = data.get('tech_stack', [])
        self.dependencies_notes = data.get('dependencies_notes', {})

        self.decisions = [
            KeyDecision.from_dict(d) for d in data.get('decisions', [])
        ]

        self.architecture_notes = data.get('architecture_notes', '')
        self.setup_notes = data.get('setup_notes', '')
        self.known_issues = data.get('known_issues', [])
        self.custom_metadata = data.get('custom_metadata', {})

        # Load auto-approve settings (merge with defaults to handle new settings)
        saved_step_settings = data.get('auto_approve_settings', {})
        self.auto_approve_settings.update(saved_step_settings)

        saved_cmd_settings = data.get('auto_approve_commands', {})
        self.auto_approve_commands.update(saved_cmd_settings)

        # Load file structure tracking (v2.3)
        file_entries_data = data.get('file_entries', {})
        self.file_entries = {
            path: FileEntry.from_dict(entry_data)
            for path, entry_data in file_entries_data.items()
        }

        tree_data = data.get('directory_tree')
        if tree_data:
            self.directory_tree = DirectoryTree.from_dict(tree_data)

        self.key_file_contents = data.get('key_file_contents', {})
        self.last_scan_time = data.get('last_scan_time')

        # Load recent changes history (v2.4)
        self.recent_changes = data.get('recent_changes', [])
