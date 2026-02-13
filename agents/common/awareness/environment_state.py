"""
Environment State
=================

Tracks runtime environment state including:
- Current working directory
- Active project detection
- Git repository state
- Virtual environment detection
- Running processes relevant to development

Refreshed on-demand, not persisted.
"""

import logging
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class GitState:
    """Current git repository state."""
    is_repo: bool = False
    root_dir: Optional[str] = None
    current_branch: Optional[str] = None
    has_uncommitted_changes: bool = False
    has_untracked_files: bool = False
    remote_url: Optional[str] = None
    ahead_count: int = 0
    behind_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'is_repo': self.is_repo,
            'root_dir': self.root_dir,
            'current_branch': self.current_branch,
            'has_uncommitted_changes': self.has_uncommitted_changes,
            'has_untracked_files': self.has_untracked_files,
            'remote_url': self.remote_url,
            'ahead_count': self.ahead_count,
            'behind_count': self.behind_count,
        }


@dataclass
class VirtualEnvState:
    """Virtual environment state."""
    is_active: bool = False
    path: Optional[str] = None
    python_version: Optional[str] = None
    env_type: Optional[str] = None  # 'venv', 'conda', 'virtualenv', 'poetry'

    def to_dict(self) -> Dict[str, Any]:
        return {
            'is_active': self.is_active,
            'path': self.path,
            'python_version': self.python_version,
            'env_type': self.env_type,
        }


@dataclass
class ActiveProject:
    """Detected active project information."""
    name: str
    path: str
    project_type: Optional[str] = None  # 'python', 'node', 'rust', 'go', etc.
    has_git: bool = False
    has_readme: bool = False
    has_tests: bool = False
    config_files: List[str] = field(default_factory=list)
    detected_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'name': self.name,
            'path': self.path,
            'project_type': self.project_type,
            'has_git': self.has_git,
            'has_readme': self.has_readme,
            'has_tests': self.has_tests,
            'config_files': self.config_files,
            'detected_at': self.detected_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ActiveProject':
        return cls(
            name=data.get('name', ''),
            path=data.get('path', ''),
            project_type=data.get('project_type'),
            has_git=data.get('has_git', False),
            has_readme=data.get('has_readme', False),
            has_tests=data.get('has_tests', False),
            config_files=data.get('config_files', []),
            detected_at=data.get('detected_at'),
        )


class EnvironmentState:
    """
    Tracks runtime environment state.
    Refreshed on-demand, not persisted.
    """

    # Project type indicators
    PROJECT_INDICATORS = {
        'python': ['setup.py', 'pyproject.toml', 'requirements.txt', 'Pipfile', 'setup.cfg'],
        'node': ['package.json', 'yarn.lock', 'pnpm-lock.yaml'],
        'rust': ['Cargo.toml'],
        'go': ['go.mod', 'go.sum'],
        'java': ['pom.xml', 'build.gradle', 'build.gradle.kts'],
        'ruby': ['Gemfile', 'Rakefile'],
        'php': ['composer.json'],
        'dotnet': ['*.csproj', '*.fsproj', '*.sln'],
    }

    # Common config files to detect
    CONFIG_FILES = [
        '.env', '.env.example', '.env.local',
        'config.yaml', 'config.yml', 'config.json',
        '.editorconfig', '.prettierrc', '.eslintrc',
        'Makefile', 'Dockerfile', 'docker-compose.yml',
        '.github/workflows', '.gitlab-ci.yml',
        'pytest.ini', 'tox.ini', 'mypy.ini',
        'tsconfig.json', 'jsconfig.json',
    ]

    def __init__(self):
        """Initialize EnvironmentState."""
        self.cwd: str = ""
        self.git_state: GitState = GitState()
        self.venv_state: VirtualEnvState = VirtualEnvState()
        self.active_project: Optional[ActiveProject] = None
        self.environment_variables: Dict[str, str] = {}
        self.last_refreshed: Optional[str] = None

    def refresh(self, directory: Optional[str] = None) -> None:
        """
        Refresh all environment state.

        Args:
            directory: Directory to check. Defaults to current working directory.
        """
        self.cwd = directory or os.getcwd()
        logger.debug(f"Refreshing environment state for: {self.cwd}")

        self._detect_git_state()
        self._detect_virtual_env()
        self._detect_project()
        self._capture_env_vars()

        self.last_refreshed = datetime.now().isoformat()

    def _detect_git_state(self) -> None:
        """Detect git repository state."""
        self.git_state = GitState()

        try:
            # Check if in a git repo
            result = subprocess.run(
                ['git', 'rev-parse', '--git-dir'],
                capture_output=True, text=True, timeout=5,
                cwd=self.cwd
            )

            if result.returncode != 0:
                return

            self.git_state.is_repo = True

            # Get root directory
            result = subprocess.run(
                ['git', 'rev-parse', '--show-toplevel'],
                capture_output=True, text=True, timeout=5,
                cwd=self.cwd
            )
            if result.returncode == 0:
                self.git_state.root_dir = result.stdout.strip()

            # Get current branch
            result = subprocess.run(
                ['git', 'branch', '--show-current'],
                capture_output=True, text=True, timeout=5,
                cwd=self.cwd
            )
            if result.returncode == 0:
                self.git_state.current_branch = result.stdout.strip()

            # Check for uncommitted changes
            result = subprocess.run(
                ['git', 'status', '--porcelain'],
                capture_output=True, text=True, timeout=5,
                cwd=self.cwd
            )
            if result.returncode == 0 and result.stdout.strip():
                lines = result.stdout.strip().split('\n')
                self.git_state.has_uncommitted_changes = any(
                    not line.startswith('??') for line in lines if line
                )
                self.git_state.has_untracked_files = any(
                    line.startswith('??') for line in lines if line
                )

            # Get remote URL
            result = subprocess.run(
                ['git', 'remote', 'get-url', 'origin'],
                capture_output=True, text=True, timeout=5,
                cwd=self.cwd
            )
            if result.returncode == 0:
                self.git_state.remote_url = result.stdout.strip()

            # Get ahead/behind counts
            result = subprocess.run(
                ['git', 'rev-list', '--left-right', '--count', '@{upstream}...HEAD'],
                capture_output=True, text=True, timeout=5,
                cwd=self.cwd
            )
            if result.returncode == 0:
                parts = result.stdout.strip().split()
                if len(parts) == 2:
                    self.git_state.behind_count = int(parts[0])
                    self.git_state.ahead_count = int(parts[1])

        except Exception as e:
            logger.debug(f"Error detecting git state: {e}")

    def _detect_virtual_env(self) -> None:
        """Detect virtual environment state."""
        self.venv_state = VirtualEnvState()

        # Check for active virtual environment
        virtual_env = os.environ.get('VIRTUAL_ENV')
        conda_prefix = os.environ.get('CONDA_PREFIX')
        poetry_active = os.environ.get('POETRY_ACTIVE')

        if virtual_env:
            self.venv_state.is_active = True
            self.venv_state.path = virtual_env
            self.venv_state.env_type = 'venv'
        elif conda_prefix:
            self.venv_state.is_active = True
            self.venv_state.path = conda_prefix
            self.venv_state.env_type = 'conda'
        elif poetry_active:
            self.venv_state.is_active = True
            self.venv_state.env_type = 'poetry'

        # Get Python version if active
        if self.venv_state.is_active:
            try:
                result = subprocess.run(
                    ['python', '--version'],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    self.venv_state.python_version = result.stdout.strip()
            except Exception:
                pass

    def _detect_project(self) -> None:
        """Detect active project information."""
        self.active_project = None

        cwd_path = Path(self.cwd)

        # Find project root (walk up until we find project indicators or hit home/root)
        project_root = self._find_project_root(cwd_path)

        if not project_root:
            return

        # Detect project type
        project_type = self._detect_project_type(project_root)

        # Detect config files
        config_files = self._detect_config_files(project_root)

        # Check for tests
        has_tests = self._has_tests_dir(project_root)

        # Check for README
        has_readme = any(
            (project_root / name).exists()
            for name in ['README.md', 'README.rst', 'README.txt', 'README']
        )

        self.active_project = ActiveProject(
            name=project_root.name,
            path=str(project_root),
            project_type=project_type,
            has_git=self.git_state.is_repo,
            has_readme=has_readme,
            has_tests=has_tests,
            config_files=config_files,
            detected_at=datetime.now().isoformat()
        )

    def _find_project_root(self, start_path: Path) -> Optional[Path]:
        """Find project root by looking for project indicators."""
        current = start_path.resolve()
        home = Path.home()

        while current != current.parent:
            # Don't go above home directory
            if current == home.parent:
                break

            # Check for any project indicator
            for indicators in self.PROJECT_INDICATORS.values():
                for indicator in indicators:
                    if '*' in indicator:
                        # Glob pattern
                        if list(current.glob(indicator)):
                            return current
                    elif (current / indicator).exists():
                        return current

            # Check for .git directory
            if (current / '.git').exists():
                return current

            current = current.parent

        # Return start path if no root found
        if start_path.is_dir():
            return start_path
        return None

    def _detect_project_type(self, project_root: Path) -> Optional[str]:
        """Detect the primary project type."""
        for project_type, indicators in self.PROJECT_INDICATORS.items():
            for indicator in indicators:
                if '*' in indicator:
                    if list(project_root.glob(indicator)):
                        return project_type
                elif (project_root / indicator).exists():
                    return project_type
        return None

    def _detect_config_files(self, project_root: Path) -> List[str]:
        """Detect configuration files in project."""
        found = []
        for config in self.CONFIG_FILES:
            config_path = project_root / config
            if config_path.exists():
                found.append(config)
            elif '/' in config:
                # Check directory patterns
                parent = project_root / Path(config).parent
                if parent.exists():
                    found.append(config)
        return found

    def _has_tests_dir(self, project_root: Path) -> bool:
        """Check if project has a tests directory."""
        test_dirs = ['tests', 'test', 'spec', 'specs', '__tests__']
        return any((project_root / d).is_dir() for d in test_dirs)

    def _capture_env_vars(self) -> None:
        """Capture relevant environment variables."""
        relevant_vars = [
            'PATH', 'HOME', 'USER', 'SHELL',
            'VIRTUAL_ENV', 'CONDA_PREFIX', 'POETRY_ACTIVE',
            'PYTHONPATH', 'NODE_PATH', 'GOPATH',
            'EDITOR', 'VISUAL', 'TERM',
            'CI', 'GITHUB_ACTIONS', 'GITLAB_CI',
        ]

        self.environment_variables = {}
        for var in relevant_vars:
            value = os.environ.get(var)
            if value:
                # Truncate long values
                if len(value) > 200:
                    value = value[:200] + '...'
                self.environment_variables[var] = value

    def get_summary(self) -> str:
        """Get a human-readable summary for LLM prompts."""
        lines = [f"CWD: {self.cwd}"]

        # Git state
        if self.git_state.is_repo:
            git_info = f"Git: {self.git_state.current_branch or 'unknown branch'}"
            if self.git_state.has_uncommitted_changes:
                git_info += " (uncommitted changes)"
            if self.git_state.ahead_count > 0:
                git_info += f" (+{self.git_state.ahead_count} ahead)"
            lines.append(git_info)

        # Virtual env
        if self.venv_state.is_active:
            venv_info = f"Venv: {self.venv_state.env_type}"
            if self.venv_state.python_version:
                venv_info += f" ({self.venv_state.python_version})"
            lines.append(venv_info)

        # Project
        if self.active_project:
            proj_info = f"Project: {self.active_project.name}"
            if self.active_project.project_type:
                proj_info += f" ({self.active_project.project_type})"
            lines.append(proj_info)

        return '\n'.join(lines)

    def to_dict(self) -> Dict[str, Any]:
        """Export to dictionary."""
        return {
            'cwd': self.cwd,
            'git_state': self.git_state.to_dict(),
            'venv_state': self.venv_state.to_dict(),
            'active_project': self.active_project.to_dict() if self.active_project else None,
            'environment_variables': self.environment_variables,
            'last_refreshed': self.last_refreshed,
        }
