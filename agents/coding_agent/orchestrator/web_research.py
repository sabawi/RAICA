"""
Web Research Module
====================

Provides web search and documentation lookup capabilities for the orchestrator.
Used to research commands, libraries, and APIs before execution.

Features:
- DuckDuckGo web search (no API key required)
- Command/tool documentation lookup
- Library API documentation search
- Man page style help extraction
"""

import asyncio
import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)

# Default RAICA server URL - can be overridden via environment or parameter
DEFAULT_RAICA_SERVER_URL = os.environ.get('RAICA_SERVER_URL', 'http://localhost:5000')

# RAICA search timeout in seconds - generous for deep research
# Can be overridden via environment variable
RAICA_SEARCH_TIMEOUT = float(os.environ.get('RAICA_SEARCH_TIMEOUT', '120'))  # 2 minutes default


@dataclass
class SearchResult:
    """A single search result."""
    title: str
    url: str
    snippet: str
    source: str = "web"  # 'web', 'man', 'help', 'docs'

    def to_dict(self) -> Dict[str, Any]:
        return {
            'title': self.title,
            'url': self.url,
            'snippet': self.snippet,
            'source': self.source,
        }


@dataclass
class ResearchResult:
    """Result of a research query."""
    query: str
    success: bool
    results: List[SearchResult] = field(default_factory=list)
    summary: str = ""
    error: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            'query': self.query,
            'success': self.success,
            'results': [r.to_dict() for r in self.results],
            'summary': self.summary,
            'error': self.error,
            'timestamp': self.timestamp,
        }

    def get_context_for_llm(self, max_results: int = 5) -> str:
        """Format research results for LLM consumption."""
        if not self.success or not self.results:
            return f"Research for '{self.query}' returned no results."

        lines = [f"Research results for: {self.query}\n"]
        for i, result in enumerate(self.results[:max_results], 1):
            lines.append(f"{i}. {result.title}")
            lines.append(f"   Source: {result.source}")
            if result.snippet:
                # Truncate long snippets
                snippet = result.snippet[:300] + "..." if len(result.snippet) > 300 else result.snippet
                lines.append(f"   {snippet}")
            lines.append("")

        if self.summary:
            lines.append(f"Summary: {self.summary}")

        return "\n".join(lines)


class WebResearcher:
    """
    Web research capabilities for the orchestrator.

    Provides multiple research methods:
    1. RAICA server web search (preferred if available)
    2. Web search via DuckDuckGo (fallback)
    3. Local command help (--help, man pages)
    4. Python library documentation
    """

    # Common command flags that provide help
    HELP_FLAGS = ['--help', '-h', 'help', '--version']

    # Commands known to be interactive (should use specific flags)
    COMMAND_RESEARCH_NOTES = {
        'ddgr': {
            'flags': ['--noprompt', '-n'],
            'note': 'Use --noprompt (-n) to avoid interactive mode',
        },
        'fzf': {
            'flags': ['--filter'],
            'note': 'Use --filter for non-interactive mode',
        },
        'less': {
            'flags': [],
            'note': 'Interactive pager - avoid, use cat or head instead',
        },
        'vim': {
            'flags': [],
            'note': 'Interactive editor - avoid in automated scripts',
        },
        'nano': {
            'flags': [],
            'note': 'Interactive editor - avoid in automated scripts',
        },
    }

    def __init__(self, llm_client: Optional[Any] = None, raica_server_url: Optional[str] = None):
        """
        Initialize the web researcher.

        Args:
            llm_client: Optional LLM client for summarization
            raica_server_url: Optional RAICA server URL for web search (default: env RAICA_SERVER_URL or localhost:5000)
        """
        self.llm_client = llm_client
        self._duckduckgo_available: Optional[bool] = None
        self._raica_server_url = raica_server_url or DEFAULT_RAICA_SERVER_URL
        self._raica_available: Optional[bool] = None
        self._raica_client = None
        logger.info(f"WebResearcher initialized with RAICA server: {self._raica_server_url}")

    def _check_raica_server(self) -> bool:
        """Check if RAICA server is available for web search."""
        if self._raica_available is not None:
            return self._raica_available

        try:
            import urllib.request
            health_url = f"{self._raica_server_url}/health"
            req = urllib.request.Request(health_url, method='GET')
            with urllib.request.urlopen(req, timeout=3) as response:
                self._raica_available = response.status == 200
                if self._raica_available:
                    logger.info(f"RAICA server available at {self._raica_server_url}")
                return self._raica_available
        except Exception as e:
            logger.debug(f"RAICA server not available: {e}")
            self._raica_available = False
            return False

    def _get_raica_client(self):
        """Get or create RAICA client."""
        if self._raica_client is None and self._check_raica_server():
            try:
                from ..knowledge.raica_client import RAICAKnowledgeClient
                self._raica_client = RAICAKnowledgeClient(base_url=self._raica_server_url)
                logger.info(f"RAICA client created for {self._raica_server_url}")
            except ImportError as e:
                logger.debug(f"RAICAKnowledgeClient not available: {e}")
                self._raica_available = False
        return self._raica_client

    async def research(
        self,
        query: str,
        research_type: str = "auto",
        max_results: int = 5
    ) -> ResearchResult:
        """
        Perform research on a topic.

        Args:
            query: What to research
            research_type: Type of research ('web', 'command', 'library', 'auto')
            max_results: Maximum number of results

        Returns:
            ResearchResult with findings
        """
        logger.info(f"Researching: {query} (type: {research_type})")

        if research_type == "auto":
            research_type = self._detect_research_type(query)

        try:
            if research_type == "command":
                return await self._research_command(query, max_results)
            elif research_type == "library":
                return await self._research_library(query, max_results)
            else:
                return await self._research_web(query, max_results)
        except Exception as e:
            logger.exception(f"Research failed: {e}")
            return ResearchResult(
                query=query,
                success=False,
                error=str(e)
            )

    def _detect_research_type(self, query: str) -> str:
        """Detect the type of research needed based on query."""
        query_lower = query.lower()

        # Command patterns
        command_patterns = [
            r'how to use (\w+) command',
            r'(\w+) command options',
            r'(\w+) flags',
            r'(\w+) --help',
            r'man (\w+)',
        ]
        for pattern in command_patterns:
            if re.search(pattern, query_lower):
                return "command"

        # Library patterns
        library_patterns = [
            r'(\w+) library',
            r'(\w+) module',
            r'(\w+) package',
            r'pip install',
            r'npm install',
            r'import (\w+)',
            r'from (\w+) import',
        ]
        for pattern in library_patterns:
            if re.search(pattern, query_lower):
                return "library"

        return "web"

    async def _research_web(self, query: str, max_results: int) -> ResearchResult:
        """Perform web search using RAICA server (preferred) or DuckDuckGo (fallback)."""
        results = []

        # Try RAICA server first if available
        raica_results = await self._search_with_raica(query, max_results)
        if raica_results:
            logger.info(f"RAICA server search returned {len(raica_results)} results")
            return ResearchResult(
                query=query,
                success=True,
                results=raica_results,
                error=None
            )

        # Fallback to DuckDuckGo
        logger.info("Falling back to DuckDuckGo search")

        # Try ddgs (or duckduckgo_search) Python library first
        try:
            # Try the new package name first
            try:
                from ddgs import DDGS
            except ImportError:
                # Fall back to old package name
                from duckduckgo_search import DDGS

            import warnings
            warnings.filterwarnings('ignore', message='.*renamed.*')

            def do_search():
                with DDGS() as ddgs:
                    return list(ddgs.text(query, max_results=max_results))

            search_results = await asyncio.to_thread(do_search)

            for item in search_results:
                results.append(SearchResult(
                    title=item.get('title', ''),
                    url=item.get('href', item.get('link', '')),
                    snippet=item.get('body', item.get('snippet', '')),
                    source='duckduckgo'
                ))

            logger.info(f"DuckDuckGo search returned {len(results)} results")

        except ImportError:
            logger.warning("ddgs/duckduckgo_search not installed, trying ddgr CLI")
            # Fallback to ddgr CLI with proper flags
            results = await self._search_with_ddgr(query, max_results)

        except Exception as e:
            logger.warning(f"DuckDuckGo search failed: {e}, trying ddgr CLI")
            results = await self._search_with_ddgr(query, max_results)

        return ResearchResult(
            query=query,
            success=len(results) > 0,
            results=results,
            error=None if results else "No results found"
        )

    async def _search_with_raica(self, query: str, max_results: int) -> List[SearchResult]:
        """
        Search using RAICA server if available.

        Uses a generous timeout (default 120s) since RAICA performs deep research
        including LLM queries, web searches, and content analysis.
        """
        if not self._check_raica_server():
            logger.debug("RAICA server not available for search")
            return []

        client = self._get_raica_client()
        if not client:
            logger.debug("RAICA client not available")
            return []

        try:
            logger.info(f"Searching via RAICA server: {query}")
            logger.info(f"   (timeout: {RAICA_SEARCH_TIMEOUT}s for deep research)")

            # Use RAICA client's async search_web method with generous timeout
            # RAICA performs deep research: LLM queries, web searches, content analysis
            import time
            start_time = time.time()

            try:
                raica_result = await asyncio.wait_for(
                    client.search_web(query, max_results=max_results),
                    timeout=RAICA_SEARCH_TIMEOUT
                )
            except asyncio.TimeoutError:
                elapsed = time.time() - start_time
                logger.warning(f"RAICA search timed out after {elapsed:.1f}s, falling back to DuckDuckGo")
                return []

            elapsed = time.time() - start_time
            logger.info(f"RAICA search completed in {elapsed:.1f}s")

            # raica_result is a KnowledgeQueryResult object with .success, .results attributes
            if raica_result and raica_result.success and raica_result.results:
                # Check for fallback results (single result with source "RAICA" = parsing failed)
                first_result = raica_result.results[0]
                if (len(raica_result.results) == 1 and
                    first_result.source == "RAICA" and
                    first_result.title == "Search Result"):
                    # This is the fallback from _parse_search_results - JSON extraction failed
                    logger.warning("RAICA returned fallback text (JSON parsing failed) - falling back to DuckDuckGo")
                    return []

                results = []
                for item in raica_result.results:
                    # item is a SearchResult from raica_client with .title, .content, .source attributes
                    results.append(SearchResult(
                        title=item.title,
                        url=item.source,  # source contains URL
                        snippet=item.content,
                        source='raica_server'
                    ))
                logger.info(f"RAICA search returned {len(results)} valid results")
                return results
            else:
                error_msg = raica_result.error if raica_result else "No result"
                logger.warning(f"RAICA search unsuccessful: {error_msg}")

        except Exception as e:
            logger.warning(f"RAICA server search failed: {e}")

        return []

    async def _search_with_ddgr(self, query: str, max_results: int) -> List[SearchResult]:
        """Search using ddgr CLI tool with proper non-interactive flags."""
        results = []

        try:
            # Check if ddgr is available
            which_result = await asyncio.to_thread(
                subprocess.run,
                ['which', 'ddgr'],
                capture_output=True,
                text=True,
                timeout=5
            )

            if which_result.returncode != 0:
                logger.warning("ddgr not installed")
                return results

            # Run ddgr with non-interactive flags
            # CRITICAL: --noprompt (-n) prevents interactive mode
            # --json gives parseable output
            cmd = [
                'ddgr',
                '--noprompt',      # Non-interactive mode
                '--num', str(max_results),
                '--json',          # JSON output
                query
            ]

            process = await asyncio.to_thread(
                subprocess.run,
                cmd,
                capture_output=True,
                text=True,
                timeout=30  # Timeout to prevent hanging
            )

            if process.returncode == 0 and process.stdout:
                import json
                try:
                    data = json.loads(process.stdout)
                    for item in data:
                        results.append(SearchResult(
                            title=item.get('title', ''),
                            url=item.get('url', ''),
                            snippet=item.get('abstract', ''),
                            source='ddgr'
                        ))
                except json.JSONDecodeError:
                    # Parse non-JSON output
                    lines = process.stdout.strip().split('\n')
                    for line in lines[:max_results]:
                        if line.strip():
                            results.append(SearchResult(
                                title=line[:100],
                                url='',
                                snippet=line,
                                source='ddgr'
                            ))

        except subprocess.TimeoutExpired:
            logger.warning("ddgr search timed out")
        except Exception as e:
            logger.warning(f"ddgr search failed: {e}")

        return results

    async def _research_command(self, query: str, max_results: int) -> ResearchResult:
        """Research a command-line tool."""
        results = []

        # Extract command name from query
        command = self._extract_command_name(query)
        if not command:
            return await self._research_web(query, max_results)

        # Check for known command notes
        if command in self.COMMAND_RESEARCH_NOTES:
            notes = self.COMMAND_RESEARCH_NOTES[command]
            results.append(SearchResult(
                title=f"Important notes for '{command}'",
                url='',
                snippet=notes['note'] + (f" Required flags: {', '.join(notes['flags'])}" if notes['flags'] else ""),
                source='known_commands'
            ))

        # Try to get --help output
        help_result = await self._get_command_help(command)
        if help_result:
            results.append(help_result)

        # Try man page summary
        man_result = await self._get_man_summary(command)
        if man_result:
            results.append(man_result)

        # Also do web search for more context
        web_results = await self._research_web(f"{command} command line options usage", max_results - len(results))
        results.extend(web_results.results)

        return ResearchResult(
            query=query,
            success=len(results) > 0,
            results=results[:max_results],
            error=None if results else f"No documentation found for '{command}'"
        )

    async def _research_library(self, query: str, max_results: int) -> ResearchResult:
        """Research a programming library."""
        results = []

        # Extract library name
        library = self._extract_library_name(query)

        if library:
            # Try pydoc for Python libraries
            pydoc_result = await self._get_pydoc_summary(library)
            if pydoc_result:
                results.append(pydoc_result)

            # Try pip show
            pip_result = await self._get_pip_info(library)
            if pip_result:
                results.append(pip_result)

        # Web search for library documentation
        search_query = f"{library or query} documentation API reference"
        web_results = await self._research_web(search_query, max_results - len(results))
        results.extend(web_results.results)

        return ResearchResult(
            query=query,
            success=len(results) > 0,
            results=results[:max_results],
            error=None if results else "No library documentation found"
        )

    async def _get_command_help(self, command: str) -> Optional[SearchResult]:
        """Get --help output for a command."""
        try:
            # First check if command exists
            which_result = await asyncio.to_thread(
                subprocess.run,
                ['which', command],
                capture_output=True,
                text=True,
                timeout=5
            )

            if which_result.returncode != 0:
                return None

            # Try --help
            result = await asyncio.to_thread(
                subprocess.run,
                [command, '--help'],
                capture_output=True,
                text=True,
                timeout=10
            )

            output = result.stdout or result.stderr
            if output:
                # Truncate to reasonable size
                output = output[:2000]
                return SearchResult(
                    title=f"{command} --help",
                    url='',
                    snippet=output,
                    source='help'
                )

        except subprocess.TimeoutExpired:
            logger.debug(f"--help for {command} timed out")
        except Exception as e:
            logger.debug(f"Failed to get help for {command}: {e}")

        return None

    async def _get_man_summary(self, command: str) -> Optional[SearchResult]:
        """Get man page summary for a command."""
        try:
            # Get just the NAME and SYNOPSIS sections
            result = await asyncio.to_thread(
                subprocess.run,
                ['man', '-f', command],  # whatis - one line description
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode == 0 and result.stdout:
                return SearchResult(
                    title=f"man {command}",
                    url='',
                    snippet=result.stdout.strip(),
                    source='man'
                )

        except Exception as e:
            logger.debug(f"Failed to get man page for {command}: {e}")

        return None

    async def _get_pydoc_summary(self, module: str) -> Optional[SearchResult]:
        """Get Python documentation for a module."""
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                ['python', '-c', f'import {module}; help({module})'],
                capture_output=True,
                text=True,
                timeout=10,
                env={'PAGER': 'cat'}  # Avoid interactive pager
            )

            if result.returncode == 0 and result.stdout:
                # Truncate to first section
                output = result.stdout[:1500]
                return SearchResult(
                    title=f"Python: {module}",
                    url='',
                    snippet=output,
                    source='pydoc'
                )

        except Exception as e:
            logger.debug(f"Failed to get pydoc for {module}: {e}")

        return None

    async def _get_pip_info(self, package: str) -> Optional[SearchResult]:
        """Get pip package info."""
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                ['pip', 'show', package],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode == 0 and result.stdout:
                return SearchResult(
                    title=f"pip: {package}",
                    url='',
                    snippet=result.stdout.strip(),
                    source='pip'
                )

        except Exception as e:
            logger.debug(f"Failed to get pip info for {package}: {e}")

        return None

    def _extract_command_name(self, query: str) -> Optional[str]:
        """Extract command name from a research query."""
        patterns = [
            r'how to use (\w+)',
            r'(\w+) command',
            r'(\w+) options',
            r'(\w+) flags',
            r'(\w+) parameters',
            r'man (\w+)',
            r'^(\w+)$',  # Just the command name
        ]

        query_lower = query.lower().strip()
        for pattern in patterns:
            match = re.search(pattern, query_lower)
            if match:
                return match.group(1)

        # If query is a single word, treat it as command name
        if ' ' not in query_lower and len(query_lower) < 30:
            return query_lower

        return None

    def _extract_library_name(self, query: str) -> Optional[str]:
        """Extract library/module name from a research query."""
        patterns = [
            r'import (\w+)',
            r'from (\w+)',
            r'(\w+) library',
            r'(\w+) module',
            r'(\w+) package',
            r'pip install (\w+)',
            r'npm install (\w+)',
        ]

        query_lower = query.lower()
        for pattern in patterns:
            match = re.search(pattern, query_lower)
            if match:
                return match.group(1)

        return None

    async def research_before_command(
        self,
        command: str,
        context: str = ""
    ) -> ResearchResult:
        """
        Research a command before executing it.

        This is called automatically by the orchestrator before
        executing unfamiliar commands.

        Args:
            command: The command to research
            context: Additional context about intended use

        Returns:
            ResearchResult with usage information
        """
        # Extract base command
        parts = command.split()
        base_cmd = parts[0] if parts else command

        # Remove path if present
        if '/' in base_cmd:
            base_cmd = base_cmd.split('/')[-1]

        # Research the command
        query = f"{base_cmd} command usage options flags"
        result = await self._research_command(query, max_results=5)

        # Check for known interactive commands
        if base_cmd in self.COMMAND_RESEARCH_NOTES:
            notes = self.COMMAND_RESEARCH_NOTES[base_cmd]
            warning = SearchResult(
                title=f"WARNING: {base_cmd} usage notes",
                url='',
                snippet=f"IMPORTANT: {notes['note']}",
                source='safety'
            )
            result.results.insert(0, warning)

        return result


# Singleton instance for easy access
_researcher: Optional[WebResearcher] = None


def get_researcher(
    llm_client: Optional[Any] = None,
    raica_server_url: Optional[str] = None
) -> WebResearcher:
    """Get or create the web researcher singleton."""
    global _researcher
    if _researcher is None:
        _researcher = WebResearcher(llm_client, raica_server_url)
    elif raica_server_url and _researcher._raica_server_url != raica_server_url:
        # Update RAICA URL if changed
        _researcher._raica_server_url = raica_server_url
        _researcher._raica_available = None  # Reset availability check
        _researcher._raica_client = None
    return _researcher
