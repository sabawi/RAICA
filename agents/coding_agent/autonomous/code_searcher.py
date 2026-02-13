"""
Code Searcher
=============

Provides robust code search capabilities for autonomous agents.
Uses `ripgrep` (rg) for high-performance search if available,
falling back to Python-based search.

Features:
- Text search with context
- File name search
- Smart exclusion handling (respects project exclusions)
"""

import asyncio
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Any, Optional, Set

# Import exclusions from BaselineManager to ensure consistency
# Using relative import based on project structure
try:
    from ..baseline_manager import BaselineManager
    DEFAULT_EXCLUDES = BaselineManager.EXCLUDE_DIRS
except ImportError:
    # Fallback if import fails (e.g. unit testing)
    DEFAULT_EXCLUDES = {
        '__pycache__', 'node_modules', '.git', '.venv', 'venv',
        'env', '.env', 'dist', 'build', '.pytest_cache',
        '.mypy_cache', '.tox', 'eggs', '*.egg-info',
        '.raica_backup', '.raica'
    }

logger = logging.getLogger(__name__)


@dataclass
class SearchMatch:
    """A single search match."""
    file_path: str
    line_number: int
    content: str
    context_before: List[str] = field(default_factory=list)
    context_after: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'file_path': self.file_path,
            'line_number': self.line_number,
            'content': self.content,
        }


@dataclass
class SearchResult:
    """Result of a code search."""
    query: str
    matches: List[SearchMatch] = field(default_factory=list)
    files_searched: int = 0
    duration_seconds: float = 0.0
    tool_used: str = "unknown"  # 'ripgrep' or 'python'
    error: Optional[str] = None

    @property
    def hit_count(self) -> int:
        return len(self.matches)

    def get_summary(self) -> str:
        """Get a human-readable summary of results."""
        if not self.matches:
            return f"No matches found for '{self.query}' (searched {self.files_searched} files using {self.tool_used})"
        
        # Group by file
        files = {}
        for match in self.matches:
            if match.file_path not in files:
                files[match.file_path] = 0
            files[match.file_path] += 1
            
        return (f"Found {len(self.matches)} matches in {len(files)} files "
                f"(searched {self.files_searched} files using {self.tool_used})")


class CodeSearcher:
    """
    Robust code search utility.
    """

    def __init__(self, project_dir: Path, excluded_dirs: Optional[Set[str]] = None):
        self.project_dir = project_dir
        self.excluded_dirs = excluded_dirs or DEFAULT_EXCLUDES
        self._rg_available: Optional[bool] = None

    async def _check_rg(self) -> bool:
        """Check if ripgrep (rg) is available on the system."""
        if self._rg_available is not None:
            return self._rg_available
            
        try:
            # Check for 'rg' command
            cmd = shutil.which('rg')
            self._rg_available = cmd is not None
        except Exception:
            self._rg_available = False
            
        return self._rg_available

    def _should_exclude(self, path: Path) -> bool:
        """Check if a path should be excluded."""
        # Check against exclusions
        for part in path.parts:
            if part in self.excluded_dirs:
                return True
            # Handle simple glob patterns in exclusion list
            for exclude in self.excluded_dirs:
                if '*' in exclude and part.endswith(exclude.replace('*', '')):
                    return True
        return False

    async def search_text(
        self, 
        query: str, 
        extensions: Optional[List[str]] = None,
        context_lines: int = 2,
        max_results: int = 100
    ) -> SearchResult:
        """
        Search for text in project files.
        
        Args:
            query: Text or regex to search for
            extensions: Optional list of file extensions to include (e.g. ['.py', '.js'])
            context_lines: Number of context lines to include
            max_results: Maximum number of matches to return
            
        Returns:
            SearchResult object
        """
        import time
        start_time = time.time()
        
        # Determine tool to use
        use_rg = await self._check_rg()
        
        if use_rg:
            result = await self._search_with_rg(query, extensions, context_lines, max_results)
        else:
            result = await self._search_with_python(query, extensions, context_lines, max_results)
            
        result.duration_seconds = time.time() - start_time
        return result

    async def find_files(self, pattern: str) -> List[Path]:
        """
        Find files by name pattern (e.g. "*.py", "*test*").
        
        Args:
            pattern: Glob pattern
            
        Returns:
            List of matching paths relative to project dir
        """
        matches = []
        
        # Use simple os.walk check - it's fast enough for file names usually
        # and more portable than 'find'/'fd' across minimal environments
        for root, dirs, files in os.walk(self.project_dir):
            root_path = Path(root)
            
            # Skip excluded dirs (modify dirs in-place to stop traversal)
            dirs[:] = [d for d in dirs if not self._should_exclude(root_path / d)]
            
            from fnmatch import fnmatch
            for filename in files:
                if fnmatch(filename, pattern):
                    file_path = root_path / filename
                    if not self._should_exclude(file_path):
                        matches.append(file_path)
                        
        return matches

    async def find_dependencies(self, file_path: str, recursive: bool = False) -> List[Path]:
        """
        Find dependencies for a file using AST analysis.
        Useful for expanding context (e.g. "Also include what this file imports").
        """
        from ..services.dependency_graph import DependencyGraphService
        
        # Use graph service
        graph = DependencyGraphService(self.project_dir)
        # Note: In a persistent agent, we would cache the graph. 
        # Rebuilding for each search is acceptable for now (< 1s for most projects).
        graph.build_graph()
        
        deps = graph.get_dependencies(str(file_path), recursive=recursive)
        
        paths = []
        for d in deps:
            p = self.project_dir / d
            if p.exists():
                paths.append(p)
                
        return paths

    async def _search_with_rg(
        self, 
        query: str, 
        extensions: Optional[List[str]], 
        context_lines: int,
        max_results: int
    ) -> SearchResult:
        """Perform search using ripgrep."""
        matches = []
        files_count = 0  # rg doesn't easily give us this, so we estimate or leave 0
        
        try:
            # Build rg command
            cmd = [
                'rg',
                '--json',  # Machine readable output
                '--max-count', str(max_results),
                '--context', str(context_lines),
                '--case-sensitive' if not query.islower() else '--smart-case',
            ]
            
            # Add extension filters
            if extensions:
                # rg uses -g *.py -g *.js syntax
                for ext in extensions:
                    if not ext.startswith('*'):
                        ext = f"*{ext}" if ext.startswith('.') else f"*.{ext}"
                    cmd.extend(['-g', ext])
            
            # Add exclusions
            for exclude in self.excluded_dirs:
                cmd.extend(['--glob', f'!{exclude}'])
                cmd.extend(['--glob', f'!**/{exclude}/**'])
                
            cmd.append(query)
            cmd.append(str(self.project_dir))
            
            # Execute
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                limit=1024*1024*10  # 10MB limit
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode not in (0, 1):  # 1 means no match, >1 means error
                err_msg = stderr.decode().strip()
                logger.error(f"rg failed: {err_msg}")
                return SearchResult(query=query, tool_used="ripgrep", error=err_msg)
                
            # Parse JSON output
            import json
            current_match = None
            
            for line in stdout.decode().splitlines():
                try:
                    data = json.loads(line)
                    type_key = data.get('type')
                    
                    if type_key == 'match':
                        # New match
                        match_data = data['data']
                        file_path = match_data['path']['text']
                        line_num = match_data['line_number']
                        content = match_data['lines']['text'].rstrip()
                        
                        # Make path relative
                        try:
                            file_path = str(Path(file_path).relative_to(self.project_dir))
                        except ValueError:
                            pass
                            
                        current_match = SearchMatch(
                            file_path=file_path,
                            line_number=line_num,
                            content=content
                        )
                        matches.append(current_match)
                        
                    elif type_key == 'context':
                        # Should be attached to a match? 
                        # rg json output stream can be tricky for context, 
                        # but simple matches are reliable. 
                        # Implementing full context parsing for rg is complex,
                        # for this version we might skip detailed context arrays
                        # or rely on basic match lines.
                        pass
                        
                except json.JSONDecodeError:
                    continue
                    
            return SearchResult(
                query=query,
                matches=matches,
                tool_used="ripgrep"
            )
            
        except Exception as e:
            logger.error(f"rg search failed: {e}")
            return SearchResult(query=query, tool_used="ripgrep", error=str(e))

    async def _search_with_python(
        self, 
        query: str, 
        extensions: Optional[List[str]], 
        context_lines: int,
        max_results: int
    ) -> SearchResult:
        """Perform search using pure Python fallback."""
        matches = []
        files_searched = 0
        compiled_query = re.compile(query, re.IGNORECASE if query.islower() else 0)
        
        for root, dirs, files in os.walk(self.project_dir):
            root_path = Path(root)
            
            # Handle exclusions
            dirs[:] = [d for d in dirs if not self._should_exclude(root_path / d)]
            
            for filename in files:
                file_path = root_path / filename
                
                # Check extension
                if extensions and not any(filename.endswith(ext) for ext in extensions):
                    continue
                
                if self._should_exclude(file_path):
                    continue
                    
                files_searched += 1
                if files_searched % 100 == 0:
                    await asyncio.sleep(0)  # Yield to event loop
                    
                try:
                    # Read file
                    try:
                        content = file_path.read_text(encoding='utf-8')
                    except UnicodeDecodeError:
                        continue  # Skip binary files
                        
                    lines = content.splitlines()
                    
                    for i, line in enumerate(lines):
                        if compiled_query.search(line):
                            # Found match
                            rel_path = str(file_path.relative_to(self.project_dir))
                            
                            # Get context
                            start_ctx = max(0, i - context_lines)
                            end_ctx = min(len(lines), i + 1 + context_lines)
                            
                            ctx_before = lines[start_ctx:i]
                            ctx_after = lines[i+1:end_ctx]
                            
                            matches.append(SearchMatch(
                                file_path=rel_path,
                                line_number=i + 1,
                                content=line,
                                context_before=ctx_before,
                                context_after=ctx_after
                            ))
                            
                            if len(matches) >= max_results:
                                return SearchResult(
                                    query=query,
                                    matches=matches,
                                    files_searched=files_searched,
                                    tool_used="python"
                                )
                                
                except Exception as e:
                    logger.warning(f"Failed to read/search {file_path}: {e}")
                    
        return SearchResult(
            query=query,
            matches=matches,
            files_searched=files_searched,
            tool_used="python"
        )
