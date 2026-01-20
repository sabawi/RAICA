"""
Code Path Tracer Service
========================

Builds and maintains a dependency graph of the codebase starting from entry points.
This is CRITICAL for debugging - you cannot find root causes without tracing code paths.

The tracer:
1. Detects entry points (HTML script tags, package.json main, Python __main__)
2. Parses imports/requires/includes to build a dependency graph
3. Traces paths from entry point to any target file/function
4. Maintains the graph in context for the debugging session
5. Identifies orphaned files that look relevant but aren't in the execution path

EXTENSIBLE ARCHITECTURE:
- Import parsers are registered via ImportParserRegistry
- Add support for new languages by implementing ImportParser and registering it
- Built-in parsers: HTML, JavaScript/TypeScript, Python, CSS, Go, Java, Ruby, PHP, C/C++

Usage:
    tracer = CodePathTracer(project_dir)
    await tracer.build_graph()

    # Get files actually in execution path
    active_files = tracer.get_active_files()

    # Find path from entry to a specific file
    path = tracer.find_path_to("ui/Tooltip.js")

    # Register custom parser for a new language
    ImportParserRegistry.register('rust', RustImportParser())
"""

import ast
import asyncio
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Callable
from collections import defaultdict

logger = logging.getLogger(__name__)


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class DependencyNode:
    """A node in the dependency graph."""
    path: str  # Relative path from project root
    absolute_path: Path
    file_type: str  # 'html', 'js', 'ts', 'py', 'css', etc.
    is_entry_point: bool = False
    is_module: bool = False  # ES module vs regular script
    imports: List[str] = field(default_factory=list)  # What this file imports
    imported_by: List[str] = field(default_factory=list)  # What imports this file
    symbols: Dict[str, int] = field(default_factory=dict)  # Exported symbols -> line numbers


@dataclass
class CodePath:
    """A traced path through the codebase."""
    start: str  # Entry point
    end: str  # Target file
    path: List[str]  # Files in order from start to end
    exists: bool  # Whether a path was found


@dataclass
class ExecutionContext:
    """Maintains the dependency graph and tracing state for a debug session."""
    entry_points: List[str] = field(default_factory=list)
    graph: Dict[str, DependencyNode] = field(default_factory=dict)
    active_files: Set[str] = field(default_factory=set)  # Files reachable from entry points
    orphaned_files: Set[str] = field(default_factory=set)  # Files that exist but aren't loaded
    traced_paths: List[CodePath] = field(default_factory=list)  # Paths we've traced
    warnings: List[str] = field(default_factory=list)


@dataclass
class ParseResult:
    """Result from an import parser."""
    imports: List[str]
    is_module: bool = False  # For languages that distinguish (e.g., ES modules)


@dataclass
class LogPoint:
    """Represents an inserted debug log point."""
    file_path: str
    line_number: int
    original_line: str
    log_statement: str
    marker: str  # Unique marker to identify this logpoint for removal
    purpose: str  # Why this logpoint was inserted (e.g., "function_entry", "conditional")


@dataclass
class LogInsertResult:
    """Result of inserting log points into a file."""
    success: bool
    file_path: str
    logpoints_inserted: List[LogPoint]
    modified_content: str
    error: Optional[str] = None


# =============================================================================
# IMPORT PARSER INTERFACE (Extensible)
# =============================================================================

class ImportParser(ABC):
    """
    Abstract base class for language-specific import parsers.

    Implement this interface to add support for new languages.
    Each parser handles:
    1. Import/dependency parsing
    2. Log statement generation for debugging
    """

    # Unique marker prefix for logpoints (used for identification and removal)
    LOGPOINT_MARKER = "RAICA_LOGPOINT"

    @property
    @abstractmethod
    def supported_extensions(self) -> List[str]:
        """Return list of file extensions this parser handles (e.g., ['.py', '.pyw'])."""
        pass

    @abstractmethod
    async def parse_imports(
        self,
        content: str,
        file_path: str,
        base_dir: str,
        resolve_path: Callable[[str, str], Optional[str]]
    ) -> ParseResult:
        """
        Parse imports from file content.

        Args:
            content: File content as string
            file_path: Path to the file being parsed
            base_dir: Directory containing the file
            resolve_path: Function to resolve relative imports to project paths

        Returns:
            ParseResult with list of imported file paths
        """
        pass

    @abstractmethod
    def generate_log_statement(
        self,
        message: str,
        variables: Optional[List[str]] = None,
        level: str = 'debug',
        marker_id: str = ''
    ) -> str:
        """
        Generate a log/debug statement for this language.

        Args:
            message: The log message
            variables: Optional list of variable names to log
            level: Log level ('debug', 'info', 'warn', 'error')
            marker_id: Unique marker for later identification/removal

        Returns:
            Language-specific log statement string
        """
        pass

    @abstractmethod
    def get_log_import(self) -> Optional[str]:
        """
        Return the import statement needed for logging, if any.

        Returns:
            Import statement string, or None if no import needed
        """
        pass

    @property
    @abstractmethod
    def comment_prefix(self) -> str:
        """Return the single-line comment prefix for this language."""
        pass

    def generate_function_entry_log(self, function_name: str, params: List[str], marker_id: str) -> str:
        """Generate log for function entry with parameters."""
        if params:
            return self.generate_log_statement(
                f"ENTER {function_name}",
                variables=params,
                level='debug',
                marker_id=marker_id
            )
        return self.generate_log_statement(f"ENTER {function_name}", marker_id=marker_id)

    def generate_function_exit_log(self, function_name: str, marker_id: str) -> str:
        """Generate log for function exit."""
        return self.generate_log_statement(f"EXIT {function_name}", marker_id=marker_id)

    def generate_checkpoint_log(self, checkpoint_name: str, marker_id: str) -> str:
        """Generate log for a checkpoint (e.g., before/after important code)."""
        return self.generate_log_statement(f"CHECKPOINT: {checkpoint_name}", marker_id=marker_id)

    def generate_variable_log(self, var_name: str, marker_id: str) -> str:
        """Generate log to dump a variable's value."""
        return self.generate_log_statement(f"VAR {var_name}", variables=[var_name], marker_id=marker_id)

    def wrap_with_marker(self, statement: str, marker_id: str) -> str:
        """Wrap a log statement with markers for later identification."""
        return f"{statement}  {self.comment_prefix} {self.LOGPOINT_MARKER}:{marker_id}"


class ImportParserRegistry:
    """
    Registry for language-specific import parsers.

    This allows the tracer to be extended with new languages without
    modifying the core tracing logic.
    """
    _parsers: Dict[str, ImportParser] = {}
    _extension_map: Dict[str, str] = {}  # Maps extension -> parser key

    @classmethod
    def register(cls, key: str, parser: ImportParser) -> None:
        """Register a parser for a language."""
        cls._parsers[key] = parser
        for ext in parser.supported_extensions:
            cls._extension_map[ext.lower()] = key

    @classmethod
    def get_parser(cls, file_path: str) -> Optional[ImportParser]:
        """Get parser for a file based on its extension."""
        ext = Path(file_path).suffix.lower()
        key = cls._extension_map.get(ext)
        return cls._parsers.get(key) if key else None

    @classmethod
    def get_file_type(cls, file_path: str) -> str:
        """Get the file type key for a file."""
        ext = Path(file_path).suffix.lower()
        return cls._extension_map.get(ext, 'other')

    @classmethod
    def list_supported(cls) -> List[str]:
        """List all supported file extensions."""
        return list(cls._extension_map.keys())


# =============================================================================
# BUILT-IN PARSERS
# =============================================================================

class HTMLImportParser(ImportParser):
    """Parser for HTML files - extracts script and link tags."""

    SCRIPT_PATTERN = re.compile(
        r'''<script[^>]*\ssrc\s*=\s*['"]([^'"]+)['"][^>]*>''',
        re.IGNORECASE
    )
    MODULE_CHECK = re.compile(r'''type\s*=\s*['"]module['"]''', re.IGNORECASE)
    CSS_LINK_PATTERN = re.compile(
        r'''<link[^>]*href\s*=\s*['"]([^'"]+\.css)['"][^>]*>''',
        re.IGNORECASE
    )

    @property
    def supported_extensions(self) -> List[str]:
        return ['.html', '.htm', '.xhtml']

    @property
    def comment_prefix(self) -> str:
        return '<!--'  # HTML uses <!-- --> for comments

    def generate_log_statement(
        self,
        message: str,
        variables: Optional[List[str]] = None,
        level: str = 'debug',
        marker_id: str = ''
    ) -> str:
        """HTML doesn't have runtime logging - inject inline script with console.log."""
        marker_comment = f" /* {self.LOGPOINT_MARKER}:{marker_id} */" if marker_id else ""
        if variables:
            var_str = ', '.join(variables)
            return f'<script>console.log("[{level.upper()}] {message}:", {var_str});{marker_comment}</script>'
        return f'<script>console.log("[{level.upper()}] {message}");{marker_comment}</script>'

    def get_log_import(self) -> Optional[str]:
        """No import needed for HTML console.log."""
        return None

    async def parse_imports(self, content, file_path, base_dir, resolve_path) -> ParseResult:
        imports = []

        # Find script tags
        for match in self.SCRIPT_PATTERN.finditer(content):
            src = match.group(1)
            if src.startswith(('http://', 'https://', '//')):
                continue
            resolved = resolve_path(src, base_dir)
            if resolved:
                imports.append(resolved)

        # Find CSS links
        for match in self.CSS_LINK_PATTERN.finditer(content):
            href = match.group(1)
            if not href.startswith(('http://', 'https://', '//')):
                resolved = resolve_path(href, base_dir)
                if resolved:
                    imports.append(resolved)

        return ParseResult(imports=imports)


class JavaScriptImportParser(ImportParser):
    """Parser for JavaScript/TypeScript - ES6 imports, CommonJS require."""

    PATTERNS = [
        # ES6: import x from 'y', import 'y', import { x } from 'y'
        re.compile(r'''import\s+(?:(?:\*\s+as\s+\w+|\{[^}]*\}|\w+)\s+from\s+)?['"]([^'"]+)['"]'''),
        # CommonJS: require('x')
        re.compile(r'''require\s*\(\s*['"]([^'"]+)['"]\s*\)'''),
        # Dynamic: import('x')
        re.compile(r'''import\s*\(\s*['"]([^'"]+)['"]\s*\)'''),
    ]

    @property
    def supported_extensions(self) -> List[str]:
        return ['.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs']

    @property
    def comment_prefix(self) -> str:
        return '//'

    def generate_log_statement(
        self,
        message: str,
        variables: Optional[List[str]] = None,
        level: str = 'debug',
        marker_id: str = ''
    ) -> str:
        """Generate console.log/debug/warn/error statement."""
        method_map = {
            'debug': 'debug',
            'info': 'info',
            'warn': 'warn',
            'error': 'error'
        }
        method = method_map.get(level, 'log')
        marker = f" // {self.LOGPOINT_MARKER}:{marker_id}" if marker_id else ""

        if variables:
            var_str = ', '.join(variables)
            return f'console.{method}("[RAICA] {message}:", {var_str});{marker}'
        return f'console.{method}("[RAICA] {message}");{marker}'

    def get_log_import(self) -> Optional[str]:
        """No import needed for JavaScript console."""
        return None

    async def parse_imports(self, content, file_path, base_dir, resolve_path) -> ParseResult:
        imports = []
        is_module = False

        for pattern in self.PATTERNS:
            for match in pattern.finditer(content):
                is_module = True
                import_path = match.group(1)
                # Skip node_modules and bare specifiers
                if not import_path.startswith(('.', '/')):
                    continue
                resolved = resolve_path(import_path, base_dir)
                if resolved and resolved not in imports:
                    imports.append(resolved)

        return ParseResult(imports=imports, is_module=is_module)


class PythonImportParser(ImportParser):
    """Parser for Python - uses AST for accurate parsing."""

    @property
    def supported_extensions(self) -> List[str]:
        return ['.py', '.pyw', '.pyi']

    @property
    def comment_prefix(self) -> str:
        return '#'

    def generate_log_statement(
        self,
        message: str,
        variables: Optional[List[str]] = None,
        level: str = 'debug',
        marker_id: str = ''
    ) -> str:
        """Generate Python logging statement using the logging module."""
        method_map = {
            'debug': 'debug',
            'info': 'info',
            'warn': 'warning',
            'error': 'error'
        }
        method = method_map.get(level, 'debug')
        marker = f"  # {self.LOGPOINT_MARKER}:{marker_id}" if marker_id else ""

        if variables:
            # Use f-string formatting for variable logging
            var_parts = ', '.join([f'{v}={{repr({v})}}' for v in variables])
            return f'logger.{method}(f"[RAICA] {message}: {var_parts}"){marker}'
        return f'logger.{method}("[RAICA] {message}"){marker}'

    def get_log_import(self) -> Optional[str]:
        """Return Python logging import."""
        return 'import logging\nlogger = logging.getLogger(__name__)'

    async def parse_imports(self, content, file_path, base_dir, resolve_path) -> ParseResult:
        """Parse Python imports using AST, handling both relative and absolute imports."""
        imports = []

        try:
            tree = ast.parse(content)
        except SyntaxError:
            return ParseResult(imports=[])

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                # import module
                for alias in node.names:
                    module_path = alias.name.replace('.', '/') + '.py'
                    # Try both project root and current directory
                    resolved = resolve_path(module_path, '')
                    if not resolved:
                        resolved = resolve_path(module_path, base_dir)
                    if resolved:
                        imports.append(resolved)

            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    module_name = node.module.replace('.', '/')
                    
                    if node.level > 0:
                        # Relative import (from .module or from ..module)
                        # level=1: same directory, level=2: parent directory, etc.
                        
                        # Start from base_dir and go up (level - 1) directories
                        parts = base_dir.split('/') if base_dir else []
                        
                        # Go up (level - 1) directories for ..module style
                        # level=1 (.module) stays in same dir
                        # level=2 (..module) goes up 1 dir
                        levels_up = node.level - 1
                        if levels_up > 0 and levels_up <= len(parts):
                            parts = parts[:-levels_up]
                        
                        # Build the import path
                        if parts:
                            module_path = '/'.join(parts) + '/' + module_name + '.py'
                        else:
                            module_path = module_name + '.py'
                        
                        resolved = resolve_path(module_path, '')
                        if not resolved:
                            # Also try just the module name in the base_dir
                            resolved = resolve_path(module_name + '.py', base_dir)
                        if resolved:
                            imports.append(resolved)
                    else:
                        # Absolute import (from module import X)
                        module_path = module_name + '.py'
                        
                        # Try project root first
                        resolved = resolve_path(module_path, '')
                        if not resolved:
                            # Try relative to current file's directory
                            resolved = resolve_path(module_path, base_dir)
                        if resolved:
                            imports.append(resolved)
                            
                elif node.level > 0:
                    # from . import something (no module, just level)
                    # This imports from __init__.py in parent dirs
                    # For now, skip these as they're typically package inits
                    pass

        return ParseResult(imports=imports)


class CSSImportParser(ImportParser):
    """Parser for CSS - @import statements."""

    PATTERN = re.compile(r'''@import\s+(?:url\s*\()?\s*['"]([^'"]+)['"]''')

    @property
    def supported_extensions(self) -> List[str]:
        return ['.css', '.scss', '.sass', '.less']

    @property
    def comment_prefix(self) -> str:
        return '/*'  # CSS uses /* */ for comments

    def generate_log_statement(
        self,
        message: str,
        variables: Optional[List[str]] = None,
        level: str = 'debug',
        marker_id: str = ''
    ) -> str:
        """CSS has no runtime logging - return a CSS comment as placeholder."""
        marker = f" {self.LOGPOINT_MARKER}:{marker_id}" if marker_id else ""
        return f'/* [RAICA LOG] {message}{marker} */'

    def get_log_import(self) -> Optional[str]:
        """CSS has no imports for logging."""
        return None

    async def parse_imports(self, content, file_path, base_dir, resolve_path) -> ParseResult:
        imports = []

        for match in self.PATTERN.finditer(content):
            import_path = match.group(1)
            if not import_path.startswith(('http://', 'https://', '//')):
                resolved = resolve_path(import_path, base_dir)
                if resolved:
                    imports.append(resolved)

        return ParseResult(imports=imports)


class GoImportParser(ImportParser):
    """Parser for Go - import statements."""

    SINGLE_PATTERN = re.compile(r'''import\s+['"]([^'"]+)['"]''')
    BLOCK_PATTERN = re.compile(r'''import\s*\(([\s\S]*?)\)''')
    STRING_PATTERN = re.compile(r'''['"]([^'"]+)['"]''')

    @property
    def supported_extensions(self) -> List[str]:
        return ['.go']

    @property
    def comment_prefix(self) -> str:
        return '//'

    def generate_log_statement(
        self,
        message: str,
        variables: Optional[List[str]] = None,
        level: str = 'debug',
        marker_id: str = ''
    ) -> str:
        """Generate Go log.Printf statement."""
        marker = f" // {self.LOGPOINT_MARKER}:{marker_id}" if marker_id else ""
        level_prefix = level.upper()

        if variables:
            # Build format string and args
            format_parts = [f'%+v' for _ in variables]
            format_str = f'[RAICA][{level_prefix}] {message}: ' + ', '.join([f'{v}=' + format_parts[i] for i, v in enumerate(variables)])
            var_args = ', '.join(variables)
            return f'log.Printf("{format_str}\\n", {var_args}){marker}'
        return f'log.Printf("[RAICA][{level_prefix}] {message}\\n"){marker}'

    def get_log_import(self) -> Optional[str]:
        """Return Go log import."""
        return '"log"'

    async def parse_imports(self, content, file_path, base_dir, resolve_path) -> ParseResult:
        imports = []

        # Single imports
        for match in self.SINGLE_PATTERN.finditer(content):
            import_path = match.group(1)
            # Only track local imports (starting with ./ or no domain)
            if import_path.startswith('./') or '.' not in import_path.split('/')[0]:
                resolved = resolve_path(import_path, base_dir)
                if resolved:
                    imports.append(resolved)

        # Block imports
        for block_match in self.BLOCK_PATTERN.finditer(content):
            block = block_match.group(1)
            for match in self.STRING_PATTERN.finditer(block):
                import_path = match.group(1)
                if import_path.startswith('./') or '.' not in import_path.split('/')[0]:
                    resolved = resolve_path(import_path, base_dir)
                    if resolved:
                        imports.append(resolved)

        return ParseResult(imports=imports)


class JavaImportParser(ImportParser):
    """Parser for Java - import statements."""

    PATTERN = re.compile(r'''import\s+(?:static\s+)?([a-zA-Z_][\w.]*);''')

    @property
    def supported_extensions(self) -> List[str]:
        return ['.java']

    @property
    def comment_prefix(self) -> str:
        return '//'

    def generate_log_statement(
        self,
        message: str,
        variables: Optional[List[str]] = None,
        level: str = 'debug',
        marker_id: str = ''
    ) -> str:
        """Generate Java System.out.println or System.err.println statement."""
        marker = f" // {self.LOGPOINT_MARKER}:{marker_id}" if marker_id else ""
        level_prefix = level.upper()
        stream = 'err' if level in ('error', 'warn') else 'out'

        if variables:
            # Use String.format for variables
            var_str = ' + ", " + '.join([f'"{v}=" + {v}' for v in variables])
            return f'System.{stream}.println("[RAICA][{level_prefix}] {message}: " + {var_str});{marker}'
        return f'System.{stream}.println("[RAICA][{level_prefix}] {message}");{marker}'

    def get_log_import(self) -> Optional[str]:
        """No import needed for System.out in Java."""
        return None

    async def parse_imports(self, content, file_path, base_dir, resolve_path) -> ParseResult:
        imports = []

        for match in self.PATTERN.finditer(content):
            import_path = match.group(1)
            # Convert package.Class to path
            # Skip standard library (java.*, javax.*, etc.)
            if not import_path.startswith(('java.', 'javax.', 'sun.', 'com.sun.')):
                file_path_guess = import_path.replace('.', '/') + '.java'
                resolved = resolve_path(file_path_guess, '')
                if resolved:
                    imports.append(resolved)

        return ParseResult(imports=imports)


class RubyImportParser(ImportParser):
    """Parser for Ruby - require and require_relative."""

    REQUIRE_PATTERN = re.compile(r'''require\s+['"]([^'"]+)['"]''')
    REQUIRE_RELATIVE_PATTERN = re.compile(r'''require_relative\s+['"]([^'"]+)['"]''')

    @property
    def supported_extensions(self) -> List[str]:
        return ['.rb', '.rake']

    @property
    def comment_prefix(self) -> str:
        return '#'

    def generate_log_statement(
        self,
        message: str,
        variables: Optional[List[str]] = None,
        level: str = 'debug',
        marker_id: str = ''
    ) -> str:
        """Generate Ruby puts/warn statement."""
        marker = f"  # {self.LOGPOINT_MARKER}:{marker_id}" if marker_id else ""
        level_prefix = level.upper()

        # Use warn for error/warn levels, puts otherwise
        method = 'warn' if level in ('error', 'warn') else 'puts'

        if variables:
            # Use string interpolation for variables
            var_str = ', '.join([f'{v}=#{{{v}.inspect}}' for v in variables])
            return f'{method} "[RAICA][{level_prefix}] {message}: {var_str}"{marker}'
        return f'{method} "[RAICA][{level_prefix}] {message}"{marker}'

    def get_log_import(self) -> Optional[str]:
        """No import needed for puts in Ruby."""
        return None

    async def parse_imports(self, content, file_path, base_dir, resolve_path) -> ParseResult:
        imports = []

        # require_relative (always local)
        for match in self.REQUIRE_RELATIVE_PATTERN.finditer(content):
            import_path = match.group(1)
            if not import_path.endswith('.rb'):
                import_path += '.rb'
            resolved = resolve_path(import_path, base_dir)
            if resolved:
                imports.append(resolved)

        # require (could be gem or local)
        for match in self.REQUIRE_PATTERN.finditer(content):
            import_path = match.group(1)
            # Only track if it looks like a local path
            if import_path.startswith('./') or import_path.startswith('../'):
                if not import_path.endswith('.rb'):
                    import_path += '.rb'
                resolved = resolve_path(import_path, base_dir)
                if resolved:
                    imports.append(resolved)

        return ParseResult(imports=imports)


class PHPImportParser(ImportParser):
    """Parser for PHP - require, include, use statements."""

    REQUIRE_PATTERN = re.compile(
        r'''(?:require|include)(?:_once)?\s*\(?\s*['"]([^'"]+)['"]\s*\)?;''',
        re.IGNORECASE
    )

    @property
    def supported_extensions(self) -> List[str]:
        return ['.php', '.phtml', '.php3', '.php4', '.php5', '.phps']

    @property
    def comment_prefix(self) -> str:
        return '//'

    def generate_log_statement(
        self,
        message: str,
        variables: Optional[List[str]] = None,
        level: str = 'debug',
        marker_id: str = ''
    ) -> str:
        """Generate PHP error_log statement."""
        marker = f" // {self.LOGPOINT_MARKER}:{marker_id}" if marker_id else ""
        level_prefix = level.upper()

        if variables:
            # Use var_export for variable dumping
            var_parts = ', '.join([f'"{v}=" . var_export(${v}, true)' for v in variables])
            return f'error_log("[RAICA][{level_prefix}] {message}: " . {var_parts});{marker}'
        return f'error_log("[RAICA][{level_prefix}] {message}");{marker}'

    def get_log_import(self) -> Optional[str]:
        """No import needed for error_log in PHP."""
        return None

    async def parse_imports(self, content, file_path, base_dir, resolve_path) -> ParseResult:
        imports = []

        for match in self.REQUIRE_PATTERN.finditer(content):
            import_path = match.group(1)
            # Skip URLs and absolute paths with variables
            if not import_path.startswith(('http://', 'https://')) and '$' not in import_path:
                resolved = resolve_path(import_path, base_dir)
                if resolved:
                    imports.append(resolved)

        return ParseResult(imports=imports)


class CppImportParser(ImportParser):
    """Parser for C/C++ - #include statements."""

    PATTERN = re.compile(r'''#include\s*["<]([^">]+)[">]''')

    @property
    def supported_extensions(self) -> List[str]:
        return ['.c', '.cpp', '.cxx', '.cc', '.h', '.hpp', '.hxx', '.hh']

    @property
    def comment_prefix(self) -> str:
        return '//'

    def generate_log_statement(
        self,
        message: str,
        variables: Optional[List[str]] = None,
        level: str = 'debug',
        marker_id: str = ''
    ) -> str:
        """Generate C/C++ printf or fprintf(stderr) statement."""
        marker = f" // {self.LOGPOINT_MARKER}:{marker_id}" if marker_id else ""
        level_prefix = level.upper()

        # Use stderr for error/warn levels
        stream = 'stderr' if level in ('error', 'warn') else 'stdout'

        if variables:
            # Build format specifiers (default to generic %p for pointers, can be improved)
            format_parts = []
            var_args = []
            for v in variables:
                format_parts.append(f'{v}=%p')  # Use %p as generic pointer format
                var_args.append(f'(void*){v}')  # Cast to void* for safety
            format_str = ', '.join(format_parts)
            var_str = ', '.join(var_args)
            return f'fprintf({stream}, "[RAICA][{level_prefix}] {message}: {format_str}\\n", {var_str});{marker}'
        return f'fprintf({stream}, "[RAICA][{level_prefix}] {message}\\n");{marker}'

    def get_log_import(self) -> Optional[str]:
        """Return C stdio.h include."""
        return '#include <stdio.h>'

    async def parse_imports(self, content, file_path, base_dir, resolve_path) -> ParseResult:
        imports = []

        for match in self.PATTERN.finditer(content):
            include_path = match.group(1)
            # Skip system headers (usually in angle brackets, but we check both)
            # Only track local includes
            if '/' in include_path or include_path.endswith(('.h', '.hpp', '.c', '.cpp')):
                resolved = resolve_path(include_path, base_dir)
                if resolved:
                    imports.append(resolved)

        return ParseResult(imports=imports)


# =============================================================================
# REGISTER BUILT-IN PARSERS
# =============================================================================

def _register_builtin_parsers():
    """Register all built-in parsers."""
    ImportParserRegistry.register('html', HTMLImportParser())
    ImportParserRegistry.register('javascript', JavaScriptImportParser())
    ImportParserRegistry.register('python', PythonImportParser())
    ImportParserRegistry.register('css', CSSImportParser())
    ImportParserRegistry.register('go', GoImportParser())
    ImportParserRegistry.register('java', JavaImportParser())
    ImportParserRegistry.register('ruby', RubyImportParser())
    ImportParserRegistry.register('php', PHPImportParser())
    ImportParserRegistry.register('cpp', CppImportParser())

# Register on module load
_register_builtin_parsers()


# =============================================================================
# MAIN TRACER CLASS
# =============================================================================

class CodePathTracer:
    """
    Traces code paths through a project to build a dependency graph.

    This is essential for debugging - modifications must target files
    that are actually in the execution path, not just files that look relevant.

    LANGUAGE AGNOSTIC: Uses ImportParserRegistry to support any language.
    Add new languages by implementing ImportParser and registering it.
    """

    def __init__(self, project_dir: Path):
        self.project_dir = Path(project_dir)
        self.context = ExecutionContext()
        self._file_cache: Dict[str, str] = {}  # Cache file contents

    async def build_graph(self) -> ExecutionContext:
        """
        Build the complete dependency graph starting from entry points.

        Returns:
            ExecutionContext with the built graph and analysis
        """
        logger.info(f"Building dependency graph for {self.project_dir}")
        logger.info(f"Supported languages: {ImportParserRegistry.list_supported()}")

        # Step 1: Find all entry points
        await self._find_entry_points()

        if not self.context.entry_points:
            self.context.warnings.append(
                "No entry points found! Cannot trace code paths. "
                "Looking for: index.html, main.*, app.*, package.json main field"
            )
            return self.context

        logger.info(f"Found entry points: {self.context.entry_points}")

        # Step 2: Trace dependencies from each entry point
        for entry in self.context.entry_points:
            await self._trace_from(entry, is_entry=True)

        # Step 3: Compute active files (reachable from entry points)
        self._compute_active_files()

        # Step 4: Find orphaned files
        await self._find_orphaned_files()

        logger.info(f"Graph built: {len(self.context.active_files)} active files, "
                   f"{len(self.context.orphaned_files)} orphaned files")

        return self.context

    async def _find_entry_points(self) -> None:
        """Detect entry points for the project (language-agnostic)."""
        entry_points = []

        # 1. HTML files (web projects)
        for html_file in ['index.html', 'main.html', 'app.html']:
            if (self.project_dir / html_file).exists():
                entry_points.append(html_file)

        # 2. Check package.json for Node.js projects
        package_json = self.project_dir / 'package.json'
        if package_json.exists():
            try:
                import json
                pkg = json.loads(package_json.read_text())
                for field in ['main', 'module', 'browser']:
                    if field in pkg and pkg[field]:
                        main_file = pkg[field]
                        if (self.project_dir / main_file).exists():
                            if main_file not in entry_points:
                                entry_points.append(main_file)
            except Exception as e:
                logger.warning(f"Failed to parse package.json: {e}")

        # 3. Common entry point patterns (language-agnostic)
        entry_patterns = [
            # Python
            'main.py', 'app.py', '__main__.py', 'run.py', 'server.py', 'manage.py',
            # JavaScript/TypeScript
            'main.js', 'app.js', 'index.js', 'server.js',
            'main.ts', 'app.ts', 'index.ts', 'server.ts',
            # Go
            'main.go', 'cmd/main.go',
            # Java
            'Main.java', 'App.java', 'Application.java',
            # Ruby
            'main.rb', 'app.rb', 'config.ru',
            # PHP
            'index.php', 'app.php', 'main.php',
            # C/C++
            'main.c', 'main.cpp', 'app.c', 'app.cpp',
        ]

        for pattern in entry_patterns:
            path = self.project_dir / pattern
            if path.exists() and pattern not in entry_points:
                entry_points.append(pattern)

        # 4. Check src/ directory
        src_dir = self.project_dir / 'src'
        if src_dir.exists():
            src_entries = [
                'index.js', 'index.ts', 'main.js', 'main.ts',
                'App.js', 'App.tsx', 'main.py', 'app.py',
                'main.go', 'Main.java', 'main.rb', 'index.php'
            ]
            for entry in src_entries:
                src_path = src_dir / entry
                if src_path.exists():
                    entry_points.append(f"src/{entry}")

        self.context.entry_points = entry_points

    async def _trace_from(self, file_path: str, is_entry: bool = False) -> None:
        """Recursively trace dependencies from a file."""
        file_path = file_path.replace('\\', '/')

        # Avoid cycles
        if file_path in self.context.graph:
            return

        abs_path = self._resolve_file_path(file_path)
        if not abs_path:
            logger.debug(f"File not found: {file_path}")
            return

        # Update file_path to resolved path
        try:
            file_path = str(abs_path.relative_to(self.project_dir))
        except ValueError:
            pass

        # Get parser for this file type
        parser = ImportParserRegistry.get_parser(file_path)
        file_type = ImportParserRegistry.get_file_type(file_path)

        # Create node
        node = DependencyNode(
            path=file_path,
            absolute_path=abs_path,
            file_type=file_type,
            is_entry_point=is_entry
        )
        self.context.graph[file_path] = node

        # Read file content
        try:
            content = abs_path.read_text(encoding='utf-8', errors='ignore')
            self._file_cache[file_path] = content
        except Exception as e:
            logger.warning(f"Failed to read {file_path}: {e}")
            return

        # Parse imports if we have a parser
        if parser:
            base_dir = str(Path(file_path).parent)
            if base_dir == '.':
                base_dir = ''

            result = await parser.parse_imports(
                content,
                file_path,
                base_dir,
                self._resolve_path
            )

            node.imports = result.imports
            node.is_module = result.is_module

        # Update reverse dependencies and trace recursively
        for imp in node.imports:
            if imp in self.context.graph:
                self.context.graph[imp].imported_by.append(file_path)

            await self._trace_from(imp, is_entry=False)

            if imp in self.context.graph:
                if file_path not in self.context.graph[imp].imported_by:
                    self.context.graph[imp].imported_by.append(file_path)

    def _resolve_file_path(self, file_path: str) -> Optional[Path]:
        """Resolve a file path, trying common extensions."""
        abs_path = self.project_dir / file_path

        if abs_path.exists():
            return abs_path

        # Try common extensions
        extensions = ['.js', '.ts', '.jsx', '.tsx', '.mjs', '.py', '.go', '.java', '.rb', '.php']
        for ext in extensions:
            test_path = self.project_dir / (file_path + ext)
            if test_path.exists():
                return test_path

        # Check for index file in directory
        if (self.project_dir / file_path).is_dir():
            index_files = ['index.js', 'index.ts', 'index.jsx', 'index.tsx', '__init__.py', 'index.php']
            for index in index_files:
                index_path = self.project_dir / file_path / index
                if index_path.exists():
                    return index_path

        return None

    def _resolve_path(self, import_path: str, base_dir: str) -> Optional[str]:
        """Resolve an import path to a relative path from project root."""
        # Remove leading ./
        if import_path.startswith('./'):
            import_path = import_path[2:]

        # Handle ../ paths
        if import_path.startswith('../'):
            parts = base_dir.split('/') if base_dir else []
            import_parts = import_path.split('/')

            while import_parts and import_parts[0] == '..':
                import_parts.pop(0)
                if parts:
                    parts.pop()

            resolved = '/'.join(parts + import_parts)
        elif import_path.startswith('/'):
            resolved = import_path[1:]
        else:
            if base_dir:
                resolved = f"{base_dir}/{import_path}"
            else:
                resolved = import_path

        resolved = resolved.replace('//', '/')

        # Verify file exists (with extension guessing)
        if self._resolve_file_path(resolved):
            return resolved

        return None

    def _compute_active_files(self) -> None:
        """Compute set of files reachable from entry points using BFS."""
        visited = set()
        queue = list(self.context.entry_points)

        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)

            if current in self.context.graph:
                for imp in self.context.graph[current].imports:
                    if imp not in visited:
                        queue.append(imp)

        self.context.active_files = visited

    async def _find_orphaned_files(self) -> None:
        """Find files that exist but aren't in the execution path."""
        # Get all supported extensions
        supported_exts = ImportParserRegistry.list_supported()

        all_files = set()
        for ext in supported_exts:
            pattern = f'**/*{ext}'
            for f in self.project_dir.glob(pattern):
                rel_path = str(f.relative_to(self.project_dir))
                # Skip common non-source directories
                if any(skip in rel_path for skip in [
                    'node_modules', '.git', '__pycache__', '.raica',
                    'venv', '.venv', 'vendor', 'target', 'build', 'dist'
                ]):
                    continue
                all_files.add(rel_path)

        self.context.orphaned_files = all_files - self.context.active_files

        # Generate warnings for suspicious orphaned files
        for orphan in self.context.orphaned_files:
            orphan_name = Path(orphan).stem.lower()
            for active in self.context.active_files:
                active_name = Path(active).stem.lower()
                if orphan_name == active_name and orphan != active:
                    self.context.warnings.append(
                        f"WARNING: '{orphan}' exists but is NOT loaded. "
                        f"Active file with similar name: '{active}'. "
                        f"Make sure you're modifying the correct file!"
                    )

    def find_path_to(self, target: str) -> CodePath:
        """Find the path from any entry point to the target file."""
        target = target.replace('\\', '/')

        for entry in self.context.entry_points:
            visited = {entry}
            queue = [(entry, [entry])]

            while queue:
                current, path = queue.pop(0)

                if current == target:
                    code_path = CodePath(
                        start=entry,
                        end=target,
                        path=path,
                        exists=True
                    )
                    self.context.traced_paths.append(code_path)
                    return code_path

                if current in self.context.graph:
                    for imp in self.context.graph[current].imports:
                        if imp not in visited:
                            visited.add(imp)
                            queue.append((imp, path + [imp]))

        return CodePath(
            start=self.context.entry_points[0] if self.context.entry_points else "",
            end=target,
            path=[],
            exists=False
        )

    def find_code_for_feature(self, feature_keywords: List[str]) -> Dict[str, List[Tuple[int, str]]]:
        """Search active files for code related to a feature."""
        results = {}

        for file_path in self.context.active_files:
            if file_path not in self._file_cache:
                continue

            content = self._file_cache[file_path]
            matches = []

            for i, line in enumerate(content.split('\n'), 1):
                line_lower = line.lower()
                if any(kw.lower() in line_lower for kw in feature_keywords):
                    matches.append((i, line.strip()))

            if matches:
                results[file_path] = matches

        return results

    def get_context_summary(self) -> str:
        """Generate a summary of the execution context for the LLM."""
        lines = [
            "=" * 60,
            "CODE PATH ANALYSIS",
            "=" * 60,
            "",
            f"Entry Points: {', '.join(self.context.entry_points)}",
            f"Active Files (in execution path): {len(self.context.active_files)}",
            f"Orphaned Files (exist but NOT loaded): {len(self.context.orphaned_files)}",
            f"Supported Languages: {', '.join(ImportParserRegistry.list_supported())}",
            "",
        ]

        # Show entry point -> immediate dependencies
        lines.append("Dependency Tree (from entry points):")
        for entry in self.context.entry_points:
            lines.append(f"  {entry}")
            if entry in self.context.graph:
                for imp in self.context.graph[entry].imports[:10]:
                    lines.append(f"    -> {imp}")
                    if imp in self.context.graph:
                        for sub_imp in self.context.graph[imp].imports[:5]:
                            lines.append(f"       -> {sub_imp}")

        # Show warnings prominently
        if self.context.warnings:
            lines.append("")
            lines.append("!" * 60)
            lines.append("WARNINGS - READ CAREFULLY:")
            for warning in self.context.warnings:
                lines.append(f"  {warning}")
            lines.append("!" * 60)

        # Show orphaned files
        if self.context.orphaned_files:
            lines.append("")
            lines.append("Orphaned files (NOT in execution path - do NOT modify these):")
            for orphan in sorted(self.context.orphaned_files)[:20]:
                lines.append(f"  [ORPHAN] {orphan}")

        lines.append("")
        lines.append("=" * 60)

        return '\n'.join(lines)

    def get_active_files_by_type(self, file_type: str) -> List[str]:
        """Get active files filtered by type."""
        return [
            f for f in self.context.active_files
            if f in self.context.graph and self.context.graph[f].file_type == file_type
        ]

    def is_file_active(self, file_path: str) -> bool:
        """Check if a file is in the execution path."""
        return file_path.replace('\\', '/') in self.context.active_files

    def get_file_content(self, file_path: str) -> Optional[str]:
        """Get cached content of a file."""
        return self._file_cache.get(file_path)


# =============================================================================
# LOG POINT INSERTER
# =============================================================================

class LogPointInserter:
    """
    Manages insertion and removal of debug log points in source files.

    Used by RAICA to:
    1. Insert temporary debug logs to trace unexpected code paths
    2. Remove logs after debugging is complete
    3. Track which logs were inserted where

    Usage:
        inserter = LogPointInserter(project_dir)

        # Insert log at function entry
        result = inserter.insert_function_entry_log("app.js", "handleClick", ["event"])

        # Insert checkpoint log
        result = inserter.insert_checkpoint("app.js", 42, "before API call")

        # Remove all RAICA logpoints
        inserter.remove_all_logpoints()
    """

    def __init__(self, project_dir: Path):
        self.project_dir = Path(project_dir)
        self._inserted_logpoints: Dict[str, List[LogPoint]] = defaultdict(list)
        self._marker_counter = 0

    def _generate_marker_id(self) -> str:
        """Generate a unique marker ID for a logpoint."""
        self._marker_counter += 1
        return f"LP{self._marker_counter:04d}"

    def insert_function_entry_log(
        self,
        file_path: str,
        function_name: str,
        param_names: List[str],
        line_number: int
    ) -> LogInsertResult:
        """
        Insert a log at function entry point.

        Args:
            file_path: Path to the file (relative to project_dir)
            function_name: Name of the function
            param_names: List of parameter names to log
            line_number: Line number where the log should be inserted (after the function def)

        Returns:
            LogInsertResult with success status and modified content
        """
        parser = ImportParserRegistry.get_parser(file_path)
        if not parser:
            return LogInsertResult(
                success=False,
                file_path=file_path,
                logpoints_inserted=[],
                modified_content="",
                error=f"No parser found for file type: {file_path}"
            )

        return self._insert_log_at_line(
            file_path=file_path,
            line_number=line_number,
            log_statement=parser.generate_function_entry_log(
                function_name, param_names, self._generate_marker_id()
            ),
            purpose=f"function_entry:{function_name}"
        )

    def insert_function_exit_log(
        self,
        file_path: str,
        function_name: str,
        line_number: int
    ) -> LogInsertResult:
        """Insert a log at function exit point."""
        parser = ImportParserRegistry.get_parser(file_path)
        if not parser:
            return LogInsertResult(
                success=False,
                file_path=file_path,
                logpoints_inserted=[],
                modified_content="",
                error=f"No parser found for file type: {file_path}"
            )

        return self._insert_log_at_line(
            file_path=file_path,
            line_number=line_number,
            log_statement=parser.generate_function_exit_log(
                function_name, self._generate_marker_id()
            ),
            purpose=f"function_exit:{function_name}"
        )

    def insert_checkpoint(
        self,
        file_path: str,
        line_number: int,
        checkpoint_name: str
    ) -> LogInsertResult:
        """Insert a checkpoint log at a specific line."""
        parser = ImportParserRegistry.get_parser(file_path)
        if not parser:
            return LogInsertResult(
                success=False,
                file_path=file_path,
                logpoints_inserted=[],
                modified_content="",
                error=f"No parser found for file type: {file_path}"
            )

        return self._insert_log_at_line(
            file_path=file_path,
            line_number=line_number,
            log_statement=parser.generate_checkpoint_log(
                checkpoint_name, self._generate_marker_id()
            ),
            purpose=f"checkpoint:{checkpoint_name}"
        )

    def insert_variable_log(
        self,
        file_path: str,
        line_number: int,
        variable_name: str
    ) -> LogInsertResult:
        """Insert a log to dump a variable's value."""
        parser = ImportParserRegistry.get_parser(file_path)
        if not parser:
            return LogInsertResult(
                success=False,
                file_path=file_path,
                logpoints_inserted=[],
                modified_content="",
                error=f"No parser found for file type: {file_path}"
            )

        return self._insert_log_at_line(
            file_path=file_path,
            line_number=line_number,
            log_statement=parser.generate_variable_log(
                variable_name, self._generate_marker_id()
            ),
            purpose=f"variable:{variable_name}"
        )

    def insert_custom_log(
        self,
        file_path: str,
        line_number: int,
        message: str,
        variables: Optional[List[str]] = None,
        level: str = 'debug'
    ) -> LogInsertResult:
        """Insert a custom log message."""
        parser = ImportParserRegistry.get_parser(file_path)
        if not parser:
            return LogInsertResult(
                success=False,
                file_path=file_path,
                logpoints_inserted=[],
                modified_content="",
                error=f"No parser found for file type: {file_path}"
            )

        marker_id = self._generate_marker_id()
        return self._insert_log_at_line(
            file_path=file_path,
            line_number=line_number,
            log_statement=parser.generate_log_statement(message, variables, level, marker_id),
            purpose=f"custom:{message[:30]}"
        )

    def _insert_log_at_line(
        self,
        file_path: str,
        line_number: int,
        log_statement: str,
        purpose: str
    ) -> LogInsertResult:
        """
        Insert a log statement at a specific line in a file.

        The log is inserted BEFORE the specified line number.
        """
        abs_path = self.project_dir / file_path

        try:
            content = abs_path.read_text(encoding='utf-8')
            lines = content.split('\n')

            if line_number < 1 or line_number > len(lines) + 1:
                return LogInsertResult(
                    success=False,
                    file_path=file_path,
                    logpoints_inserted=[],
                    modified_content=content,
                    error=f"Line number {line_number} out of range (file has {len(lines)} lines)"
                )

            # Detect indentation from the target line
            target_line = lines[line_number - 1] if line_number <= len(lines) else ""
            indent = ""
            for char in target_line:
                if char in (' ', '\t'):
                    indent += char
                else:
                    break

            # Create the logpoint record
            marker_id = log_statement.split(ImportParser.LOGPOINT_MARKER + ':')[-1].split()[0] if ImportParser.LOGPOINT_MARKER in log_statement else ""
            logpoint = LogPoint(
                file_path=file_path,
                line_number=line_number,
                original_line=target_line,
                log_statement=log_statement,
                marker=marker_id,
                purpose=purpose
            )

            # Insert the log statement with proper indentation
            indented_log = indent + log_statement
            lines.insert(line_number - 1, indented_log)

            modified_content = '\n'.join(lines)

            # Track the inserted logpoint
            self._inserted_logpoints[file_path].append(logpoint)

            return LogInsertResult(
                success=True,
                file_path=file_path,
                logpoints_inserted=[logpoint],
                modified_content=modified_content
            )

        except Exception as e:
            return LogInsertResult(
                success=False,
                file_path=file_path,
                logpoints_inserted=[],
                modified_content="",
                error=str(e)
            )

    def insert_log_import_if_needed(self, file_path: str, content: str) -> str:
        """
        Add the logging import statement to a file if needed.

        Returns the modified content with import added, or original if not needed.
        """
        parser = ImportParserRegistry.get_parser(file_path)
        if not parser:
            return content

        log_import = parser.get_log_import()
        if not log_import:
            return content

        # Check if import already exists
        if log_import in content:
            return content

        # For different languages, add import at appropriate location
        lines = content.split('\n')
        file_ext = Path(file_path).suffix.lower()

        # Find the right place to insert the import
        insert_idx = 0

        if file_ext in ('.py', '.pyw', '.pyi'):
            # Python: after docstrings and __future__ imports
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped.startswith('from __future__'):
                    insert_idx = i + 1
                elif stripped.startswith(('import ', 'from ')) and insert_idx == 0:
                    insert_idx = i
                    break
                elif stripped and not stripped.startswith(('#', '"""', "'''")):
                    if insert_idx == 0:
                        insert_idx = i
                    break

        elif file_ext in ('.c', '.cpp', '.h', '.hpp', '.cxx', '.cc', '.hxx', '.hh'):
            # C/C++: after other #includes
            for i, line in enumerate(lines):
                if line.strip().startswith('#include'):
                    insert_idx = i + 1

        elif file_ext == '.go':
            # Go: inside import block or after package declaration
            for i, line in enumerate(lines):
                if 'import (' in line:
                    # Insert inside import block
                    lines.insert(i + 1, f'\t{log_import}')
                    return '\n'.join(lines)
                elif line.strip().startswith('import "'):
                    insert_idx = i + 1
                elif line.strip().startswith('package '):
                    insert_idx = i + 1

        # Insert the import
        lines.insert(insert_idx, log_import)
        return '\n'.join(lines)

    def remove_logpoints_from_file(self, file_path: str) -> Tuple[str, int]:
        """
        Remove all RAICA logpoints from a specific file.

        Returns:
            Tuple of (modified_content, count_removed)
        """
        abs_path = self.project_dir / file_path

        try:
            content = abs_path.read_text(encoding='utf-8')
            lines = content.split('\n')

            # Remove lines containing RAICA logpoint markers
            new_lines = []
            removed_count = 0

            for line in lines:
                if ImportParser.LOGPOINT_MARKER in line:
                    removed_count += 1
                    logger.debug(f"Removing logpoint: {line.strip()}")
                else:
                    new_lines.append(line)

            # Clear tracked logpoints for this file
            if file_path in self._inserted_logpoints:
                del self._inserted_logpoints[file_path]

            return '\n'.join(new_lines), removed_count

        except Exception as e:
            logger.error(f"Failed to remove logpoints from {file_path}: {e}")
            return "", 0

    def remove_all_logpoints(self) -> Dict[str, int]:
        """
        Remove all RAICA logpoints from all tracked files.

        Returns:
            Dict mapping file_path to count of logpoints removed
        """
        results = {}

        # Get all files that might have logpoints
        files_to_check = set(self._inserted_logpoints.keys())

        # Also scan project for any missed logpoints
        supported_exts = ImportParserRegistry.list_supported()
        for ext in supported_exts:
            for f in self.project_dir.glob(f'**/*{ext}'):
                rel_path = str(f.relative_to(self.project_dir))
                # Skip non-source directories
                if any(skip in rel_path for skip in [
                    'node_modules', '.git', '__pycache__', '.raica',
                    'venv', '.venv', 'vendor', 'target', 'build', 'dist'
                ]):
                    continue
                files_to_check.add(rel_path)

        for file_path in files_to_check:
            modified_content, count = self.remove_logpoints_from_file(file_path)
            if count > 0:
                results[file_path] = count
                # Write the cleaned content back
                abs_path = self.project_dir / file_path
                try:
                    abs_path.write_text(modified_content, encoding='utf-8')
                    logger.info(f"Removed {count} logpoints from {file_path}")
                except Exception as e:
                    logger.error(f"Failed to write cleaned file {file_path}: {e}")

        # Clear all tracked logpoints
        self._inserted_logpoints.clear()

        return results

    def get_all_logpoints(self) -> Dict[str, List[LogPoint]]:
        """Get all currently tracked logpoints."""
        return dict(self._inserted_logpoints)

    def get_logpoint_summary(self) -> str:
        """Generate a summary of all inserted logpoints."""
        if not self._inserted_logpoints:
            return "No logpoints currently inserted."

        lines = ["Inserted Logpoints:"]
        total = 0

        for file_path, logpoints in sorted(self._inserted_logpoints.items()):
            lines.append(f"\n  {file_path}:")
            for lp in logpoints:
                lines.append(f"    Line {lp.line_number}: [{lp.purpose}] {lp.marker}")
                total += 1

        lines.append(f"\nTotal: {total} logpoints in {len(self._inserted_logpoints)} files")
        return '\n'.join(lines)
