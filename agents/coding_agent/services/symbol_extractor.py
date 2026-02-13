"""
Symbol Extractor Service
========================

Extracts and tracks symbols (functions, classes, constants) from project files.
Provides fuzzy matching to help resolve undefined symbol errors.

Key Features:
- AST-based extraction for accurate symbol detection
- Fuzzy matching using difflib (no external dependencies)
- Symbol table for project-wide lookup
- NameError analysis with suggested fixes
"""

import ast
import logging
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class SymbolInfo:
    """Information about a symbol in the codebase."""
    name: str                    # Symbol name: ASSETS_ROOT, GameWindow, load_asset
    kind: str                    # 'constant', 'function', 'class', 'variable', 'import'
    file: str                    # Relative file path: config.py
    line: int                    # Line number where defined
    signature: str = ""          # For functions: (path: str) -> Asset
    docstring: str = ""          # First line of docstring if available
    is_exported: bool = True     # Is this symbol part of public API
    
    def __hash__(self):
        return hash((self.name, self.file, self.line))
    
    def __eq__(self, other):
        if not isinstance(other, SymbolInfo):
            return False
        return self.name == other.name and self.file == other.file and self.line == other.line


@dataclass
class FuzzyMatch:
    """Result of a fuzzy symbol match."""
    query: str                   # What was searched for: _ASSETS_ROOT
    match: SymbolInfo            # The matching symbol
    score: float                 # Similarity score 0.0 - 1.0
    
    @property
    def suggestion(self) -> str:
        """Format as a user-friendly suggestion."""
        return f"'{self.query}' → '{self.match.name}' ({self.score:.0%}) from {self.match.file}:{self.match.line}"


@dataclass
class SymbolTable:
    """Project-wide symbol table."""
    symbols: Dict[str, List[SymbolInfo]] = field(default_factory=dict)
    files_indexed: Set[str] = field(default_factory=set)
    
    def add(self, symbol: SymbolInfo) -> None:
        """Add a symbol to the table."""
        if symbol.name not in self.symbols:
            self.symbols[symbol.name] = []
        # Avoid duplicates
        if symbol not in self.symbols[symbol.name]:
            self.symbols[symbol.name].append(symbol)
    
    def get(self, name: str) -> List[SymbolInfo]:
        """Get all definitions of a symbol."""
        return self.symbols.get(name, [])
    
    def all_names(self) -> Set[str]:
        """Get all symbol names in the table."""
        return set(self.symbols.keys())
    
    def by_file(self, file_path: str) -> List[SymbolInfo]:
        """Get all symbols from a specific file."""
        result = []
        for symbols in self.symbols.values():
            for s in symbols:
                if s.file == file_path:
                    result.append(s)
        return result

    def remove_file_symbols(self, file_path: str) -> None:
        """Remove all symbols associated with a file (for updates)."""
        if file_path not in self.files_indexed:
            return
            
        for name in list(self.symbols.keys()):
            self.symbols[name] = [s for s in self.symbols[name] if s.file != file_path]
            if not self.symbols[name]:
                del self.symbols[name]
        
        self.files_indexed.remove(file_path)


# =============================================================================
# SYMBOL EXTRACTOR
# =============================================================================

class SymbolExtractor:
    """
    Extracts symbols from Python source files using AST.
    """
    
    def __init__(self, project_dir: Path):
        self.project_dir = Path(project_dir)
        self.symbol_table = SymbolTable()
    
    def update_file(self, file_path:  Path) -> None:
        """
        Update symbols for a single file (incremental update).
        Remove old symbols for this file and re-extract.
        """
        if not file_path.exists():
            return

        rel_path = str(file_path.relative_to(self.project_dir))
        
        # Remove old entries
        self.symbol_table.remove_file_symbols(rel_path)
        
        # Re-extract
        try:
            self._extract_from_file(file_path)
            logger.debug(f"Updated symbols for {rel_path}")
        except Exception as e:
            logger.warning(f"Failed to update symbols for {file_path}: {e}")

    def build_symbol_table(self, file_paths: Optional[List[str]] = None) -> SymbolTable:
        """
        Build symbol table for the project.
        
        Args:
            file_paths: Optional list of specific files to index.
                       If None, indexes all .py files in project.
        
        Returns:
            Populated SymbolTable
        """
        if file_paths:
            files = [self.project_dir / f for f in file_paths]
        else:
            files = list(self.project_dir.rglob("*.py"))
        
        for file_path in files:
            if not file_path.exists():
                continue
            # Skip venv, __pycache__, etc.
            rel_path = str(file_path.relative_to(self.project_dir))
            if any(skip in rel_path for skip in ['venv/', '__pycache__', '.git/', 'node_modules/']):
                continue
            
            # Use update_file logic to ensure clean state even if called multiple times
            self.update_file(file_path)
        
        logger.info(f"Symbol table built: {len(self.symbol_table.symbols)} unique symbols from {len(self.symbol_table.files_indexed)} files")
        return self.symbol_table
    
    def _extract_from_file(self, file_path: Path) -> List[SymbolInfo]:
        """Extract all symbols from a single file."""
        symbols = []
        rel_path = str(file_path.relative_to(self.project_dir))
        
        try:
            content = file_path.read_text(encoding='utf-8', errors='replace')
            tree = ast.parse(content, filename=str(file_path))
        except SyntaxError as e:
            logger.debug(f"Syntax error in {file_path}: {e}")
            return symbols
        
        for node in ast.iter_child_nodes(tree):
            extracted = self._extract_node(node, rel_path)
            symbols.extend(extracted)
        
        # Mark file as indexed
        self.symbol_table.files_indexed.add(rel_path)
        
        # Add to symbol table
        for sym in symbols:
            self.symbol_table.add(sym)
        
        return symbols
    
    def _extract_node(self, node: ast.AST, file_path: str) -> List[SymbolInfo]:
        """Extract symbols from a single AST node."""
        symbols = []
        
        if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
            # Function definition
            sig = self._get_function_signature(node)
            doc = ast.get_docstring(node) or ""
            symbols.append(SymbolInfo(
                name=node.name,
                kind='function',
                file=file_path,
                line=node.lineno,
                signature=sig,
                docstring=doc.split('\n')[0] if doc else "",
                is_exported=not node.name.startswith('_')
            ))
        
        elif isinstance(node, ast.ClassDef):
            # Class definition
            doc = ast.get_docstring(node) or ""
            symbols.append(SymbolInfo(
                name=node.name,
                kind='class',
                file=file_path,
                line=node.lineno,
                docstring=doc.split('\n')[0] if doc else "",
                is_exported=not node.name.startswith('_')
            ))
            
            # Also extract class methods
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if not item.name.startswith('_') or item.name in ('__init__', '__call__'):
                        sig = self._get_function_signature(item)
                        symbols.append(SymbolInfo(
                            name=f"{node.name}.{item.name}",
                            kind='method',
                            file=file_path,
                            line=item.lineno,
                            signature=sig,
                            is_exported=True
                        ))
        
        elif isinstance(node, ast.Assign):
            # Variable/constant assignment at module level
            for target in node.targets:
                if isinstance(target, ast.Name):
                    name = target.id
                    # Determine if constant (UPPER_CASE) or variable
                    is_constant = name.isupper() or (name.startswith('_') and name[1:].isupper())
                    kind = 'constant' if is_constant else 'variable'
                    symbols.append(SymbolInfo(
                        name=name,
                        kind=kind,
                        file=file_path,
                        line=node.lineno,
                        is_exported=not name.startswith('_')
                    ))
        
        elif isinstance(node, ast.AnnAssign):
            # Annotated assignment: x: int = 5
            if isinstance(node.target, ast.Name):
                name = node.target.id
                is_constant = name.isupper()
                kind = 'constant' if is_constant else 'variable'
                symbols.append(SymbolInfo(
                    name=name,
                    kind=kind,
                    file=file_path,
                    line=node.lineno,
                    is_exported=not name.startswith('_')
                ))
        
        elif isinstance(node, ast.ImportFrom):
            # from x import y, z
            if node.module:
                for alias in node.names:
                    imported_name = alias.asname if alias.asname else alias.name
                    symbols.append(SymbolInfo(
                        name=imported_name,
                        kind='import',
                        file=file_path,
                        line=node.lineno,
                        signature=f"from {node.module}",
                        is_exported=not imported_name.startswith('_')
                    ))
        
        return symbols
    
    def _get_function_signature(self, node: ast.FunctionDef) -> str:
        """Extract function signature as string."""
        args = []
        for arg in node.args.args:
            arg_str = arg.arg
            if arg.annotation:
                try:
                    arg_str += f": {ast.unparse(arg.annotation)}"
                except Exception:
                    pass
            args.append(arg_str)
        
        sig = f"({', '.join(args)})"
        
        if node.returns:
            try:
                sig += f" -> {ast.unparse(node.returns)}"
            except Exception:
                pass
        
        return sig


# =============================================================================
# FUZZY SYMBOL MATCHER
# =============================================================================

class FuzzySymbolMatcher:
    """
    Matches undefined symbol names to similar existing symbols.
    
    Uses difflib.SequenceMatcher for:
    - No external dependencies
    - Good balance of speed and accuracy
    - Handles insertions, deletions, substitutions
    """
    
    def __init__(self, symbol_table: SymbolTable):
        self.symbol_table = symbol_table
    
    def find_similar(
        self, 
        undefined_name: str, 
        threshold: float = 0.6,
        max_results: int = 5
    ) -> List[FuzzyMatch]:
        """
        Find symbols similar to an undefined name.
        
        Args:
            undefined_name: The name that wasn't found (e.g., '_ASSETS_ROOT')
            threshold: Minimum similarity score (0.0 - 1.0)
            max_results: Maximum number of matches to return
        
        Returns:
            List of FuzzyMatch objects, sorted by score descending
        """
        matches = []
        
        # Normalize the query
        query_normalized = self._normalize(undefined_name)
        
        for name in self.symbol_table.all_names():
            # Skip exact match
            if name == undefined_name:
                continue
            
            # Calculate similarity
            name_normalized = self._normalize(name)
            score = self._similarity(query_normalized, name_normalized)
            
            # Boost score for prefix/suffix matches
            if name_normalized.endswith(query_normalized) or query_normalized.endswith(name_normalized):
                score = min(1.0, score + 0.15)
            if name_normalized.startswith(query_normalized) or query_normalized.startswith(name_normalized):
                score = min(1.0, score + 0.10)
            
            if score >= threshold:
                for symbol_info in self.symbol_table.get(name):
                    matches.append(FuzzyMatch(
                        query=undefined_name,
                        match=symbol_info,
                        score=score
                    ))
        
        # Sort by score, highest first
        matches.sort(key=lambda m: m.score, reverse=True)
        
        # Deduplicate by name (keep highest score)
        seen_names = set()
        unique_matches = []
        for m in matches:
            if m.match.name not in seen_names:
                seen_names.add(m.match.name)
                unique_matches.append(m)
        
        return unique_matches[:max_results]
    
    def _normalize(self, name: str) -> str:
        """Normalize symbol name for comparison."""
        # Remove leading underscores
        normalized = name.lstrip('_')
        # Convert to lowercase
        normalized = normalized.lower()
        return normalized
    
    def _similarity(self, s1: str, s2: str) -> float:
        """Calculate similarity ratio between two strings."""
        return SequenceMatcher(None, s1, s2).ratio()
    
    def suggest_for_error(self, error_message: str) -> Optional[str]:
        """
        Parse a NameError and suggest the correct symbol.
        
        Args:
            error_message: Error message like "NameError: name '_ASSETS_ROOT' is not defined"
        
        Returns:
            Suggestion string or None if no good match
        """
        # Extract the undefined name from NameError
        patterns = [
            r"NameError: name ['\"]([^'\"]+)['\"] is not defined",
            r"undefined: ([A-Za-z_][A-Za-z0-9_]*)",
            r"cannot find name '([^']+)'",
        ]
        
        undefined_name = None
        for pattern in patterns:
            match = re.search(pattern, error_message)
            if match:
                undefined_name = match.group(1)
                break
        
        if not undefined_name:
            return None
        
        matches = self.find_similar(undefined_name, threshold=0.5, max_results=3)
        
        if not matches:
            return None
        
        if len(matches) == 1 or matches[0].score > 0.85:
            # High confidence single match
            m = matches[0]
            return f"Did you mean '{m.match.name}'? (defined in {m.match.file}:{m.match.line})"
        else:
            # Multiple possibilities
            suggestions = [f"'{m.match.name}' ({m.match.file})" for m in matches[:3]]
            return f"Similar symbols: {', '.join(suggestions)}"


# =============================================================================
# CONTEXT GENERATOR
# =============================================================================

class SymbolContextGenerator:
    """
    Generates LLM-friendly context about available symbols.
    
    Helps the LLM use correct symbol names by providing a summary
    of what's available in the project.
    """
    
    def __init__(self, symbol_table: SymbolTable):
        self.symbol_table = symbol_table
    
    def generate_context(
        self, 
        relevant_files: Optional[List[str]] = None,
        include_imports: bool = False,
        max_symbols_per_file: int = 20
    ) -> str:
        """
        Generate context string for LLM prompt.
        
        Args:
            relevant_files: Only include symbols from these files (None = all)
            include_imports: Include imported symbols
            max_symbols_per_file: Limit symbols per file to avoid token bloat
        
        Returns:
            Formatted context string
        """
        lines = ["AVAILABLE SYMBOLS IN PROJECT:"]
        lines.append("")
        
        # Group by file
        files_to_process = relevant_files or list(self.symbol_table.files_indexed)
        
        for file_path in sorted(files_to_process):
            symbols = self.symbol_table.by_file(file_path)
            
            # Filter if not including imports
            if not include_imports:
                symbols = [s for s in symbols if s.kind != 'import']
            
            # Only show exported symbols
            symbols = [s for s in symbols if s.is_exported]
            
            if not symbols:
                continue
            
            lines.append(f"From {file_path}:")
            
            # Sort by kind for readability
            kind_order = {'constant': 0, 'class': 1, 'function': 2, 'method': 3, 'variable': 4, 'import': 5}
            symbols.sort(key=lambda s: (kind_order.get(s.kind, 99), s.name))
            
            for sym in symbols[:max_symbols_per_file]:
                if sym.kind == 'function':
                    lines.append(f"  - {sym.name}{sym.signature} (function, line {sym.line})")
                elif sym.kind == 'method':
                    lines.append(f"  - {sym.name}{sym.signature} (method, line {sym.line})")
                elif sym.kind == 'class':
                    doc_part = f" - {sym.docstring[:40]}..." if sym.docstring else ""
                    lines.append(f"  - {sym.name} (class, line {sym.line}){doc_part}")
                else:
                    lines.append(f"  - {sym.name} ({sym.kind}, line {sym.line})")
            
            if len(symbols) > max_symbols_per_file:
                lines.append(f"  ... and {len(symbols) - max_symbols_per_file} more")
            
            lines.append("")
        
        return "\n".join(lines)


# =============================================================================
# CONVENIENCE FUNCTION
# =============================================================================

def analyze_undefined_symbol(
    project_dir: Path, 
    error_message: str,
    relevant_files: Optional[List[str]] = None
) -> Tuple[Optional[str], str]:
    """
    Convenience function to analyze an undefined symbol error.
    
    Args:
        project_dir: Path to project
        error_message: The error message containing NameError
        relevant_files: Optional list of files to search
    
    Returns:
        Tuple of (suggestion, context_string)
    """
    extractor = SymbolExtractor(project_dir)
    table = extractor.build_symbol_table(relevant_files)
    
    matcher = FuzzySymbolMatcher(table)
    suggestion = matcher.suggest_for_error(error_message)
    
    context_gen = SymbolContextGenerator(table)
    context = context_gen.generate_context(relevant_files)
    
    return suggestion, context
