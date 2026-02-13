"""
System Profile
==============

Detects and caches system capabilities including:
- Operating system and distribution
- Available package managers
- Development tools (git, docker, python, node, etc.)
- Shell environment

Persisted to ~/.raica/profiles/system_profile.yaml
"""

import logging
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)


@dataclass
class ToolCapability:
    """A detected tool capability."""
    name: str
    path: Optional[str] = None
    version: Optional[str] = None
    available: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            'name': self.name,
            'path': self.path,
            'version': self.version,
            'available': self.available
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ToolCapability':
        return cls(
            name=data.get('name', ''),
            path=data.get('path'),
            version=data.get('version'),
            available=data.get('available', False)
        )


class SystemProfile:
    """
    Detects and caches system capabilities.
    Persists to ~/.raica/profiles/system_profile.yaml
    """

    PROFILE_FILE = "system_profile.yaml"
    CACHE_TTL_HOURS = 24

    # Tools to detect
    TOOLS_TO_DETECT = [
        'git', 'docker', 'docker-compose', 'python', 'python3', 'pip', 'pip3',
        'node', 'npm', 'npx', 'yarn', 'pnpm',
        'java', 'javac', 'mvn', 'gradle',
        'go', 'rust', 'cargo', 'rustc',
        'ruby', 'gem', 'bundle',
        'php', 'composer',
        'make', 'cmake', 'gcc', 'g++', 'clang',
        'curl', 'wget', 'ssh', 'scp',
        'vim', 'nano', 'code', 'subl',
        'tmux', 'screen',
        'jq', 'yq', 'htop', 'tree'
    ]

    # Package managers by OS
    PACKAGE_MANAGERS = {
        'Linux': ['apt', 'apt-get', 'yum', 'dnf', 'pacman', 'zypper', 'apk', 'snap', 'flatpak'],
        'Darwin': ['brew', 'port'],
        'Windows': ['choco', 'scoop', 'winget']
    }

    def __init__(self, profiles_dir: Optional[Path] = None):
        """
        Initialize SystemProfile.

        Args:
            profiles_dir: Directory for profile storage. Defaults to ~/.raica/profiles/
        """
        self.profiles_dir = profiles_dir or (Path.home() / ".raica" / "profiles")
        self.profile_file = self.profiles_dir / self.PROFILE_FILE

        # Detected properties
        self.os_name: str = ""
        self.os_version: str = ""
        self.os_release: str = ""
        self.distro: Optional[str] = None
        self.distro_version: Optional[str] = None
        self.architecture: str = ""
        self.hostname: str = ""
        self.username: str = ""
        self.package_managers: List[str] = []
        self.tools: Dict[str, ToolCapability] = {}
        self.shell: str = ""
        self.home_dir: str = ""
        self.python_version: str = ""
        self.node_version: Optional[str] = None
        self.detected_at: Optional[str] = None

    def detect(self, force: bool = False) -> None:
        """
        Detect system capabilities.

        Args:
            force: If True, bypass cache and re-detect
        """
        # Check cache first
        if not force and self._load_from_cache():
            logger.info("Loaded system profile from cache")
            return

        logger.info("Detecting system capabilities...")

        # Detect all properties
        self._detect_os()
        self._detect_user_info()
        self._detect_shell()
        self._detect_package_managers()
        self._detect_tools()
        self._detect_language_versions()

        self.detected_at = datetime.now().isoformat()

        # Save to cache
        self._save_to_cache()
        logger.info(f"System profile detected and cached: {self.os_name} {self.distro or ''}")

    def _load_from_cache(self) -> bool:
        """Load profile from cache if valid."""
        if not self.profile_file.exists():
            return False

        try:
            with open(self.profile_file, 'r') as f:
                data = yaml.safe_load(f)

            if not data:
                return False

            # Check TTL
            detected_at = data.get('detected_at')
            if detected_at:
                detected_time = datetime.fromisoformat(detected_at)
                if datetime.now() - detected_time > timedelta(hours=self.CACHE_TTL_HOURS):
                    logger.info("System profile cache expired")
                    return False

            # Restore from cache
            self._from_dict(data)
            return True

        except Exception as e:
            logger.warning(f"Failed to load system profile cache: {e}")
            return False

    def _save_to_cache(self) -> None:
        """Save profile to cache."""
        try:
            self.profiles_dir.mkdir(parents=True, exist_ok=True)
            with open(self.profile_file, 'w') as f:
                yaml.dump(self.to_dict(), f, default_flow_style=False)
        except Exception as e:
            logger.warning(f"Failed to save system profile cache: {e}")

    def _detect_os(self) -> None:
        """Detect operating system details."""
        self.os_name = platform.system()  # 'Linux', 'Darwin', 'Windows'
        self.os_version = platform.version()
        self.os_release = platform.release()
        self.architecture = platform.machine()

        # Detect Linux distribution
        if self.os_name == 'Linux':
            self._detect_linux_distro()

    def _detect_linux_distro(self) -> None:
        """Detect Linux distribution."""
        try:
            # Try /etc/os-release first (most modern distros)
            if Path('/etc/os-release').exists():
                with open('/etc/os-release', 'r') as f:
                    for line in f:
                        if line.startswith('NAME='):
                            self.distro = line.split('=')[1].strip().strip('"')
                        elif line.startswith('VERSION_ID='):
                            self.distro_version = line.split('=')[1].strip().strip('"')
                return

            # Fallback: try lsb_release
            result = subprocess.run(
                ['lsb_release', '-d'],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                self.distro = result.stdout.split(':')[1].strip()

        except Exception as e:
            logger.debug(f"Could not detect Linux distro: {e}")

    def _detect_user_info(self) -> None:
        """Detect user information."""
        self.hostname = platform.node()
        self.username = os.getenv('USER') or os.getenv('USERNAME') or 'unknown'
        self.home_dir = str(Path.home())

    def _detect_shell(self) -> None:
        """Detect current shell."""
        self.shell = os.getenv('SHELL', '')
        if self.shell:
            self.shell = Path(self.shell).name  # Just the shell name, not path

    def _detect_package_managers(self) -> None:
        """Detect available package managers."""
        self.package_managers = []

        pm_list = self.PACKAGE_MANAGERS.get(self.os_name, [])
        for pm in pm_list:
            if shutil.which(pm):
                self.package_managers.append(pm)
                logger.debug(f"Found package manager: {pm}")

    def _detect_tools(self) -> None:
        """Detect available development tools."""
        self.tools = {}

        for tool_name in self.TOOLS_TO_DETECT:
            tool_path = shutil.which(tool_name)
            if tool_path:
                version = self._get_tool_version(tool_name)
                self.tools[tool_name] = ToolCapability(
                    name=tool_name,
                    path=tool_path,
                    version=version,
                    available=True
                )
            else:
                self.tools[tool_name] = ToolCapability(
                    name=tool_name,
                    available=False
                )

    def _get_tool_version(self, tool_name: str) -> Optional[str]:
        """Get version of a tool."""
        version_flags = {
            'git': ['--version'],
            'docker': ['--version'],
            'python': ['--version'],
            'python3': ['--version'],
            'node': ['--version'],
            'npm': ['--version'],
            'java': ['-version'],  # Outputs to stderr
            'go': ['version'],
            'rustc': ['--version'],
            'cargo': ['--version'],
        }

        flags = version_flags.get(tool_name, ['--version'])

        try:
            result = subprocess.run(
                [tool_name] + flags,
                capture_output=True, text=True, timeout=5
            )
            output = result.stdout or result.stderr
            if output:
                # Extract first line and clean up
                version_line = output.strip().split('\n')[0]
                return version_line[:100]  # Limit length
        except Exception:
            pass

        return None

    def _detect_language_versions(self) -> None:
        """Detect specific language runtime versions."""
        # Python
        if 'python3' in self.tools and self.tools['python3'].available:
            self.python_version = self.tools['python3'].version or ''
        elif 'python' in self.tools and self.tools['python'].available:
            self.python_version = self.tools['python'].version or ''

        # Node.js
        if 'node' in self.tools and self.tools['node'].available:
            self.node_version = self.tools['node'].version

    def get_install_command(self, package: str) -> Optional[str]:
        """
        Get the appropriate install command for this system.

        Args:
            package: Package name to install

        Returns:
            Install command string or None if no package manager available
        """
        if not self.package_managers:
            return None

        pm = self.package_managers[0]  # Use first available

        install_commands = {
            'apt': f'sudo apt install -y {package}',
            'apt-get': f'sudo apt-get install -y {package}',
            'yum': f'sudo yum install -y {package}',
            'dnf': f'sudo dnf install -y {package}',
            'pacman': f'sudo pacman -S --noconfirm {package}',
            'zypper': f'sudo zypper install -y {package}',
            'apk': f'sudo apk add {package}',
            'brew': f'brew install {package}',
            'port': f'sudo port install {package}',
            'choco': f'choco install -y {package}',
            'scoop': f'scoop install {package}',
            'winget': f'winget install {package}',
            'snap': f'sudo snap install {package}',
        }

        return install_commands.get(pm)

    def is_tool_available(self, tool_name: str) -> bool:
        """Check if a tool is available."""
        if tool_name in self.tools:
            return self.tools[tool_name].available
        # Check dynamically if not in our detected list
        return shutil.which(tool_name) is not None

    def get_summary(self) -> str:
        """Get a human-readable summary for LLM prompts."""
        lines = [
            f"OS: {self.os_name} {self.os_release}",
        ]

        if self.distro:
            lines.append(f"Distribution: {self.distro} {self.distro_version or ''}")

        lines.append(f"Architecture: {self.architecture}")
        lines.append(f"Shell: {self.shell}")

        if self.package_managers:
            lines.append(f"Package Managers: {', '.join(self.package_managers)}")

        if self.python_version:
            lines.append(f"Python: {self.python_version}")

        if self.node_version:
            lines.append(f"Node.js: {self.node_version}")

        # List key available tools
        key_tools = ['git', 'docker', 'npm', 'pip3', 'make']
        available_key = [t for t in key_tools if self.is_tool_available(t)]
        if available_key:
            lines.append(f"Key Tools: {', '.join(available_key)}")

        return '\n'.join(lines)

    def to_dict(self) -> Dict[str, Any]:
        """Export to dictionary."""
        return {
            'os_name': self.os_name,
            'os_version': self.os_version,
            'os_release': self.os_release,
            'distro': self.distro,
            'distro_version': self.distro_version,
            'architecture': self.architecture,
            'hostname': self.hostname,
            'username': self.username,
            'package_managers': self.package_managers,
            'tools': {name: tool.to_dict() for name, tool in self.tools.items()},
            'shell': self.shell,
            'home_dir': self.home_dir,
            'python_version': self.python_version,
            'node_version': self.node_version,
            'detected_at': self.detected_at,
        }

    def _from_dict(self, data: Dict[str, Any]) -> None:
        """Restore from dictionary."""
        self.os_name = data.get('os_name', '')
        self.os_version = data.get('os_version', '')
        self.os_release = data.get('os_release', '')
        self.distro = data.get('distro')
        self.distro_version = data.get('distro_version')
        self.architecture = data.get('architecture', '')
        self.hostname = data.get('hostname', '')
        self.username = data.get('username', '')
        self.package_managers = data.get('package_managers', [])
        self.shell = data.get('shell', '')
        self.home_dir = data.get('home_dir', '')
        self.python_version = data.get('python_version', '')
        self.node_version = data.get('node_version')
        self.detected_at = data.get('detected_at')

        # Restore tools
        self.tools = {}
        for name, tool_data in data.get('tools', {}).items():
            self.tools[name] = ToolCapability.from_dict(tool_data)
