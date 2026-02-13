#!/usr/bin/env python3
"""
Context Builder - Prepares rich, focused context BEFORE first LLM contact

Architecture Philosophy:
- MINIMAL SCAFFOLDING: RAICA gathers, LLM interprets
- Build context once, use many times
- Measure token usage at every step
- Start minimal, expand only when needed

Key Principle: "Could this be an LLM prompt instead?"
- If YES → Don't parse it, give raw data to LLM
- If NO → Build minimal scaffolding only
"""

import os
import sys
import subprocess
import json
from pathlib import Path
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field, asdict
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# DATA STRUCTURES - Pure data containers, no complex logic
# =============================================================================

@dataclass
class ToolInfo:
    """Information about an available system tool."""
    name: str
    path: str
    exists: bool
    category: Optional[str] = None

    def to_compact_string(self) -> str:
        """Compact representation for context (save tokens)."""
        return f"{self.name}: {self.path}" if self.exists else f"{self.name}: NOT_FOUND"


@dataclass
class SystemProfile:
    """System profile - cached, rarely changes."""
    os_info: str                          # "Linux Ubuntu 22.04 (x86_64)"
    shell: str                            # "bash"
    python_version: str                   # "3.12.0"
    working_directory: str                # Current working directory
    tools: Dict[str, ToolInfo] = field(default_factory=dict)

    # Token usage tracking
    estimated_tokens: int = 0

    def to_compact_dict(self) -> Dict[str, Any]:
        """Compact representation to save tokens."""
        return {
            'os': self.os_info,
            'shell': self.shell,
            'python': self.python_version,
            'cwd': self.working_directory,
            'tools': {name: tool.to_compact_string() for name, tool in self.tools.items() if tool.exists}
        }

    def estimate_tokens(self) -> int:
        """Rough estimate: 1 token ≈ 4 characters."""
        text = json.dumps(self.to_compact_dict())
        self.estimated_tokens = len(text) // 4
        return self.estimated_tokens


@dataclass
class UserProfile:
    """User profile - cached, updates occasionally."""
    name: Optional[str] = None
    email: Optional[str] = None
    working_directory: str = os.getcwd()

    # Token usage tracking
    estimated_tokens: int = 0

    def to_compact_dict(self) -> Dict[str, Any]:
        """Compact representation."""
        return {
            'name': self.name or 'Unknown',
            'email': self.email or 'Unknown',
            'cwd': self.working_directory
        }

    def estimate_tokens(self) -> int:
        """Rough estimate: 1 token ≈ 4 characters."""
        text = json.dumps(self.to_compact_dict())
        self.estimated_tokens = len(text) // 4
        return self.estimated_tokens


@dataclass
class ProjectProfile:
    """Project profile - per-request, context-heavy."""
    project_dir: Optional[Path] = None

    # Core docs (raw text - let LLM parse!)
    claude_md: Optional[str] = None       # Project directives
    readme: Optional[str] = None          # Project overview
    architecture: Optional[str] = None    # Architecture docs

    # Structure (simple tree - let LLM understand!)
    file_tree: Optional[str] = None       # Output of `tree` command

    # Metadata
    has_project: bool = False

    # Token usage tracking
    estimated_tokens: int = 0

    def to_compact_dict(self) -> Dict[str, Any]:
        """Compact representation - WARNING: Can be token-heavy!"""
        result = {
            'has_project': self.has_project
        }

        if not self.has_project:
            return result

        result['project_dir'] = str(self.project_dir)

        # Include docs but truncate if too long
        if self.claude_md:
            result['claude_md'] = self._truncate(self.claude_md, max_chars=2000)
        if self.readme:
            result['readme'] = self._truncate(self.readme, max_chars=1000)
        if self.architecture:
            result['architecture'] = self._truncate(self.architecture, max_chars=1500)
        if self.file_tree:
            result['file_tree'] = self._truncate(self.file_tree, max_chars=800)

        return result

    def _truncate(self, text: str, max_chars: int) -> str:
        """Truncate text if too long, add indicator."""
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + f"\n\n[... truncated, {len(text) - max_chars} chars omitted]"

    def estimate_tokens(self) -> int:
        """Rough estimate: 1 token ≈ 4 characters."""
        if not self.has_project:
            self.estimated_tokens = 10
            return self.estimated_tokens

        total_chars = 0
        if self.claude_md:
            total_chars += min(len(self.claude_md), 2000)
        if self.readme:
            total_chars += min(len(self.readme), 1000)
        if self.architecture:
            total_chars += min(len(self.architecture), 1500)
        if self.file_tree:
            total_chars += min(len(self.file_tree), 800)

        self.estimated_tokens = total_chars // 4
        return self.estimated_tokens


@dataclass
class UserToolsProfile:
    """
    User-defined tools available on RAICA server.

    Strategy: Catalog only (name + description), not full schemas.
    LLM can request details via INVESTIGATE when it wants to use a tool.
    """
    tools: Dict[str, Dict[str, str]] = field(default_factory=dict)  # name → {category, description}
    communication_tools: List[str] = field(default_factory=list)  # Highlighted tools

    # Token usage tracking
    estimated_tokens: int = 0

    def to_compact_dict(self) -> Dict[str, Any]:
        """Compact representation (catalog only, no schemas)."""
        return {
            'available': len(self.tools),
            'catalog': self.tools,
            'communication_hub': self.communication_tools  # Highlight these
        }

    def estimate_tokens(self) -> int:
        """Estimate token usage for tool catalog."""
        # Each tool: ~30-40 tokens (name + category + short description)
        self.estimated_tokens = len(self.tools) * 35
        return self.estimated_tokens


@dataclass
class Context:
    """Complete context for first LLM contact."""
    system: Optional[SystemProfile] = None
    user: Optional[UserProfile] = None
    user_tools: Optional[UserToolsProfile] = None  # NEW: User-defined tools
    project: Optional[ProjectProfile] = None
    request: str = ""

    def total_estimated_tokens(self) -> int:
        """Total estimated tokens for this context."""
        total = 0
        if self.system:
            total += self.system.estimate_tokens()
        if self.user:
            total += self.user.estimate_tokens()
        if self.user_tools:
            total += self.user_tools.estimate_tokens()
        if self.project:
            total += self.project.estimate_tokens()
        total += len(self.request) // 4  # Request itself
        return total

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'system': self.system.to_compact_dict() if self.system else None,
            'user': self.user.to_compact_dict() if self.user else None,
            'user_tools': self.user_tools.to_compact_dict() if self.user_tools else None,
            'project': self.project.to_compact_dict() if self.project else None,
            'request': self.request,
            'estimated_tokens': self.total_estimated_tokens()
        }


# =============================================================================
# CONTEXT BUILDER - Minimal implementation
# =============================================================================

class ContextBuilder:
    """
    Builds rich, focused context BEFORE first LLM contact.

    Philosophy:
    1. Gather raw data (don't parse complex structures - let LLM do it)
    2. Cache what doesn't change (system, user)
    3. Rebuild what does (project context per-request)
    4. Measure token usage at every step
    5. Truncate if getting too heavy

    Token Budget (rough):
    - System Profile: ~100-200 tokens
    - User Profile: ~50 tokens
    - Project Profile: ~500-1500 tokens (varies!)
    - Total target: < 2000 tokens for context
    """

    def __init__(self):
        self._system_profile_cache: Optional[SystemProfile] = None
        self._user_profile_cache: Optional[UserProfile] = None
        self._user_tools_cache: Optional[UserToolsProfile] = None

    # =========================================================================
    # PUBLIC API
    # =========================================================================

    async def build_context(
        self,
        request: str,
        project_dir: Optional[Path] = None
    ) -> Context:
        """
        Build complete context before first LLM contact.

        Args:
            request: User's request
            project_dir: Project directory (if working in a project)

        Returns:
            Context object with all profiles
        """
        logger.info("Building context...")

        context = Context(request=request)

        # 1. System Profile (cached)
        context.system = self._build_system_profile()
        logger.info(f"  System profile: {context.system.estimated_tokens} tokens")

        # 2. User Profile (cached)
        context.user = self._build_user_profile()
        logger.info(f"  User profile: {context.user.estimated_tokens} tokens")

        # 3. User Tools Profile (cached)
        context.user_tools = await self._build_user_tools_profile()
        logger.info(f"  User tools: {context.user_tools.estimated_tokens} tokens ({len(context.user_tools.tools)} tools)")

        # 4. Project Profile (per-request)
        if project_dir and project_dir.exists():
            context.project = self._build_project_profile(project_dir)
            logger.info(f"  Project profile: {context.project.estimated_tokens} tokens")
        else:
            context.project = ProjectProfile(has_project=False)
            logger.info("  No project context")

        total_tokens = context.total_estimated_tokens()
        logger.info(f"  TOTAL estimated tokens: {total_tokens}")

        if total_tokens > 3000:
            logger.warning(f"  ⚠️  Context is heavy ({total_tokens} tokens) - may need pruning")

        return context

    # =========================================================================
    # SYSTEM PROFILE - Cached
    # =========================================================================

    def _build_system_profile(self) -> SystemProfile:
        """
        Build system profile - cached, rarely changes.

        Strategy: Keep it MINIMAL
        - OS info: one line
        - Shell: one word
        - Python: version string
        - Tools: only check critical categories, discovery is DYNAMIC not hardcoded
        """
        if self._system_profile_cache:
            logger.debug("Using cached system profile")
            return self._system_profile_cache

        profile = SystemProfile(
            os_info=self._detect_os(),
            shell=self._detect_shell(),
            python_version=self._get_python_version(),
            working_directory=os.getcwd(),
            tools=self._discover_critical_tools()
        )

        profile.estimate_tokens()
        self._system_profile_cache = profile

        return profile

    def _detect_os(self) -> str:
        """Detect OS - one line."""
        try:
            # Use uname for Linux/Unix
            result = subprocess.run(
                ['uname', '-s', '-r', '-m'],
                capture_output=True,
                text=True,
                timeout=2
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except:
            pass

        # Fallback to platform module
        import platform
        return f"{platform.system()} {platform.release()} ({platform.machine()})"

    def _detect_shell(self) -> str:
        """Detect shell - one word."""
        shell = os.environ.get('SHELL', '/bin/bash')
        return Path(shell).name

    def _get_python_version(self) -> str:
        """Get Python version."""
        return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

    def _discover_critical_tools(self) -> Dict[str, ToolInfo]:
        """
        Discover CRITICAL system tools dynamically.

        CRITICAL: This is NOT a hardcoded list of all possible tools!
        This checks for COMMONLY NEEDED tools in categories.

        The LLM can still request ANY command - this just gives it a
        quick reference of what's definitely available.

        Categories checked:
        - Email tools (for sending emails)
        - Web tools (for downloading, API calls)
        - Archive tools (for compression)
        - VCS tools (for version control)
        - Container tools (for Docker operations)

        If a tool isn't in this list, the LLM can still try it!
        This is just a convenience, not a limitation.
        """
        # Categories to check (NOT exhaustive, NOT limiting!)
        tools_to_check = {
            # Email
            'mail': 'email',
            'sendmail': 'email',
            'msmtp': 'email',

            # Web
            'curl': 'web',
            'wget': 'web',

            # Archive
            'tar': 'archive',
            'zip': 'archive',
            'gzip': 'archive',

            # VCS
            'git': 'vcs',

            # Container
            'docker': 'container',
        }

        discovered = {}

        for tool_name, category in tools_to_check.items():
            tool_info = self._check_tool(tool_name, category)
            discovered[tool_name] = tool_info

        # Log what we found
        found_tools = [name for name, info in discovered.items() if info.exists]
        logger.debug(f"Discovered tools: {', '.join(found_tools)}")

        return discovered

    def _check_tool(self, tool_name: str, category: str) -> ToolInfo:
        """
        Check if a tool exists using `which` command.

        This is DISCOVERY, not hardcoding. We check if the tool exists,
        but we don't dictate its usage or parameters.
        """
        try:
            result = subprocess.run(
                ['which', tool_name],
                capture_output=True,
                text=True,
                timeout=1
            )

            if result.returncode == 0:
                path = result.stdout.strip()
                return ToolInfo(
                    name=tool_name,
                    path=path,
                    exists=True,
                    category=category
                )
        except:
            pass

        return ToolInfo(
            name=tool_name,
            path='',
            exists=False,
            category=category
        )

    # =========================================================================
    # USER PROFILE - Cached
    # =========================================================================

    def _build_user_profile(self) -> UserProfile:
        """
        Build user profile - cached, updates occasionally.

        Strategy: Keep it MINIMAL
        - Name/email: from git config or env
        - Working directory: current
        - That's it for now!
        """
        if self._user_profile_cache:
            logger.debug("Using cached user profile")
            return self._user_profile_cache

        profile = UserProfile(
            name=self._get_user_name(),
            email=self._get_user_email(),
            working_directory=os.getcwd()
        )

        profile.estimate_tokens()
        self._user_profile_cache = profile

        return profile

    def _get_user_name(self) -> Optional[str]:
        """Get user name from git config or environment."""
        # Try git config first
        try:
            result = subprocess.run(
                ['git', 'config', 'user.name'],
                capture_output=True,
                text=True,
                timeout=2
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except:
            pass

        # Fallback to USER environment variable
        return os.environ.get('USER') or os.environ.get('USERNAME')

    def _get_user_email(self) -> Optional[str]:
        """Get user email from git config or environment."""
        # Try git config first
        try:
            result = subprocess.run(
                ['git', 'config', 'user.email'],
                capture_output=True,
                text=True,
                timeout=2
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except:
            pass

        # Could check .env files here in future
        return None

    # =========================================================================
    # USER TOOLS PROFILE - Cached
    # =========================================================================

    async def _build_user_tools_profile(self) -> UserToolsProfile:
        """
        Build user tools profile - catalog only, not full schemas.

        Strategy: Give LLM AWARENESS of available tools, not full details.
        LLM can request details via INVESTIGATE if it wants to use a tool.

        Categories for highlighting:
        - Communication Hub: email, social media, calendar (PRIORITY)
        - Documents: PDF, search, OCR
        - Finance: Stock analysis, SEC data
        - Research: Papers, academic search
        - Development: Code execution, process management
        """
        if self._user_tools_cache:
            logger.debug("Using cached user tools profile")
            return self._user_tools_cache

        profile = UserToolsProfile()

        try:
            # Add user_tools directory to path
            import sys
            raica_root = Path(__file__).parent.parent.parent.parent
            sys.path.insert(0, str(raica_root))

            # Discover all user tools
            from user_tools.tool_discovery import discover_user_tools

            tools = await discover_user_tools()

            # Categorize tools
            # Communication Hub tools (HIGHLIGHT THESE!)
            communication_keywords = ['email', 'mail', 'calendar', 'social', 'message', 'twitter', 'facebook']
            document_keywords = ['pdf', 'document', 'search', 'image', 'text', 'ocr']
            finance_keywords = ['stock', 'sec', 'edgar', 'financial', 'market']
            research_keywords = ['paper', 'research', 'publish', 'academic']
            dev_keywords = ['executor', 'process', 'sandbox', 'code']

            # Extract name + description + category for each tool
            for tool in tools:
                # Get short description (first line/sentence)
                desc = tool.description
                if '\n' in desc:
                    desc = desc.split('\n')[0].strip()
                if '.' in desc and len(desc) > 100:
                    # Take first sentence
                    desc = desc.split('.')[0].strip() + '.'
                if len(desc) > 120:
                    desc = desc[:117] + "..."

                # Categorize
                tool_name_lower = tool.name.lower()
                desc_lower = desc.lower()

                category = 'utility'  # Default
                if any(kw in tool_name_lower or kw in desc_lower for kw in communication_keywords):
                    category = 'communication'
                    profile.communication_tools.append(tool.name)
                elif any(kw in tool_name_lower or kw in desc_lower for kw in document_keywords):
                    category = 'document'
                elif any(kw in tool_name_lower or kw in desc_lower for kw in finance_keywords):
                    category = 'finance'
                elif any(kw in tool_name_lower or kw in desc_lower for kw in research_keywords):
                    category = 'research'
                elif any(kw in tool_name_lower or kw in desc_lower for kw in dev_keywords):
                    category = 'development'

                profile.tools[tool.name] = {
                    'category': category,
                    'description': desc
                }

            logger.info(f"Discovered {len(profile.tools)} user tools")
            logger.info(f"Communication hub tools: {len(profile.communication_tools)}")

        except Exception as e:
            logger.warning(f"Failed to discover user tools: {e}")
            # Graceful fallback - continue without user tools

        profile.estimate_tokens()
        self._user_tools_cache = profile

        return profile

    # =========================================================================
    # PROJECT PROFILE - Per-request
    # =========================================================================

    def _build_project_profile(self, project_dir: Path) -> ProjectProfile:
        """
        Build project profile - per-request.

        Strategy: RAW DATA, let LLM parse
        - CLAUDE.md: raw text (LLM understands markdown)
        - README.md: raw text (LLM understands markdown)
        - Architecture: raw text if found
        - File tree: raw tree output (LLM understands tree structure)

        NO PARSING! Just give LLM the raw data.
        """
        profile = ProjectProfile(
            project_dir=project_dir,
            has_project=True
        )

        # 1. Read CLAUDE.md (project directives)
        claude_md_path = project_dir / "CLAUDE.md"
        if claude_md_path.exists():
            try:
                profile.claude_md = claude_md_path.read_text()
                logger.debug(f"  Read CLAUDE.md: {len(profile.claude_md)} chars")
            except Exception as e:
                logger.warning(f"  Failed to read CLAUDE.md: {e}")

        # 2. Read README.md (project overview)
        readme_path = project_dir / "README.md"
        if readme_path.exists():
            try:
                profile.readme = readme_path.read_text()
                logger.debug(f"  Read README.md: {len(profile.readme)} chars")
            except Exception as e:
                logger.warning(f"  Failed to read README.md: {e}")

        # 3. Read architecture docs (if they exist)
        arch_paths = [
            project_dir / "docs" / "ARCHITECTURE.md",
            project_dir / "docs" / "architecture.md",
            project_dir / "ARCHITECTURE.md"
        ]

        for arch_path in arch_paths:
            if arch_path.exists():
                try:
                    profile.architecture = arch_path.read_text()
                    logger.debug(f"  Read {arch_path.name}: {len(profile.architecture)} chars")
                    break
                except Exception as e:
                    logger.warning(f"  Failed to read {arch_path}: {e}")

        # 4. Get file tree (use tree command or fallback to ls)
        profile.file_tree = self._get_file_tree(project_dir)

        profile.estimate_tokens()

        return profile

    def _get_file_tree(self, project_dir: Path) -> Optional[str]:
        """
        Get file tree using `tree` command or fallback to `ls`.

        Strategy: Give LLM visual structure, let it understand
        """
        # Try tree command first (limited depth to save tokens)
        try:
            result = subprocess.run(
                ['tree', '-L', '2', '-I', '__pycache__|*.pyc|.git|node_modules|venv|.venv', str(project_dir)],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                return result.stdout
        except:
            pass

        # Fallback to ls -R (limited)
        try:
            result = subprocess.run(
                ['ls', '-R', str(project_dir)],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                # Truncate if too long
                output = result.stdout
                if len(output) > 3000:
                    output = output[:3000] + "\n[... truncated]"
                return output
        except:
            pass

        return None


# =============================================================================
# TESTING UTILITIES
# =============================================================================

async def test_context_builder():
    """Test context builder and measure token usage."""
    print("\n" + "="*70)
    print("CONTEXT BUILDER TEST")
    print("="*70)

    builder = ContextBuilder()

    # Test 1: Build context WITHOUT project
    print("\n1. Building context WITHOUT project...")
    context1 = await builder.build_context(
        request="Send an email to user@example.com",
        project_dir=None
    )
    print(f"   Total tokens: {context1.total_estimated_tokens()}")
    print(f"   Context: {json.dumps(context1.to_dict(), indent=2)}")

    # Test 2: Build context WITH project
    print("\n2. Building context WITH project (current dir)...")
    context2 = await builder.build_context(
        request="Fix the bug in validation.py",
        project_dir=Path.cwd()
    )
    print(f"   Total tokens: {context2.total_estimated_tokens()}")
    print(f"   Has CLAUDE.md: {context2.project.claude_md is not None}")
    print(f"   Has README: {context2.project.readme is not None}")
    print(f"   Has file tree: {context2.project.file_tree is not None}")

    # Test 3: Check caching
    print("\n3. Testing cache (should be instant)...")
    import time
    start = time.time()
    context3 = await builder.build_context(
        request="Another request",
        project_dir=None
    )
    elapsed = time.time() - start
    print(f"   Elapsed: {elapsed*1000:.1f}ms (should be < 5ms if cached)")

    print("\n" + "="*70)
    print("TEST COMPLETE")
    print("="*70)


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_context_builder())
