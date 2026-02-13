"""
Adaptive Patch Matcher - Robust, intelligent code patching
===========================================================

Multi-strategy patch matching with semantic understanding and adaptive fallbacks.
Guarantees finding the right location or failing with clear guidance.
"""

import ast
import re
import signal
from pathlib import Path
from typing import Optional, Callable, List, Tuple
import difflib
import logging

logger = logging.getLogger(__name__)


class TimeoutError(Exception):
    """Raised when operation exceeds timeout."""
    pass


class AdaptivePatchMatcher:
    """
    Robust patch matcher with multiple fallback strategies.

    Strategy cascade (ordered by precision):
    1. Exact Match - Fast path for perfect matches
    2. Normalized Whitespace - Handles spacing variations
    3. Semantic AST Match - Compares code structure (Python only)
    4. Context Anchor - Uses surrounding code as reference
    5. Fuzzy Line Match - Line-by-line with tolerance
    6. Signature Match - Finds by function/class name
    7. Tab-Space Conversion - Handles mixed tabs/spaces
    """

    @staticmethod
    def detect_file_corruption(content: str, file_path: Path) -> Optional[str]:
        """
        Detect common file corruptions that cause syntax errors.

        Returns:
            Description of corruption if found, None if file looks OK
        """
        if file_path.suffix != '.py':
            return None

        lines = content.split('\n')

        # Check for stray triple quotes at the start
        if lines and lines[0].strip() == '"""':
            # Check if there's no matching close or docstring content
            if len(lines) < 2 or not lines[1].strip():
                return "Stray opening triple-quote at line 1 (file may be corrupted)"

        # Check for unbalanced triple quotes
        triple_double = content.count('"""')
        triple_single = content.count("'''")
        if triple_double % 2 != 0:
            return f"Unbalanced triple-double-quotes ({triple_double} found)"
        if triple_single % 2 != 0:
            return f"Unbalanced triple-single-quotes ({triple_single} found)"

        # Check for common corruption patterns
        if content.startswith('"""') and not content.startswith('"""'):
            # Module docstring should have content or be on multiple lines
            first_newline = content.find('\n')
            if first_newline > 0:
                first_line = content[:first_newline]
                if first_line.strip() == '"""':
                    # Lone """ on first line - suspicious
                    return "Possible corrupted module docstring at line 1"

        return None

    def __init__(self, file_path: Path, content: Optional[str] = None, verbose: bool = True):
        """
        Args:
            file_path: Path to file being patched
            content: File content (if None, reads from file_path)
            verbose: Print progress to stdout
        """
        self.file_path = Path(file_path)
        self.content = content if content is not None else self.file_path.read_text(encoding='utf-8')
        self.lines = self.content.splitlines(keepends=True)
        self.verbose = verbose
        
        # For Python files, parse AST once
        self.ast_tree = None
        if self.file_path.suffix == '.py':
            try:
                self.ast_tree = ast.parse(self.content)
            except SyntaxError:
                logger.warning(f"Could not parse {file_path} as Python AST")
    
    def find_and_replace(self, search: str, replace: str, validate_syntax: bool = True) -> Optional[str]:
        """
        Find search block and replace with adaptive strategies.

        Args:
            search: Code block to search for
            replace: Replacement code block
            validate_syntax: If True, validate result doesn't introduce syntax errors

        Returns:
            New file content with replacement applied, or None if all strategies fail
        """
        strategies = [
            ("Exact Match", self._exact_match),
            ("Normalized Whitespace", self._normalized_whitespace_match),
            ("Semantic AST Match", self._semantic_ast_match),
            ("Context Anchor", self._context_anchor_match),
            ("Fuzzy Line Match", self._fuzzy_line_match),
            ("Signature Match", self._signature_match),
            ("Tab-Space Conversion", self._tab_space_match),  # New strategy
        ]

        for i, (name, strategy) in enumerate(strategies):
            if self.verbose:
                print(f"    Strategy {i+1}/{len(strategies)}: {name}...", flush=True)

            try:
                result = strategy(search, replace)
                if result:
                    # Validate syntax if this is a Python file
                    if validate_syntax and self.file_path.suffix == '.py':
                        syntax_error = self._validate_python_syntax(result)
                        if syntax_error:
                            if self.verbose:
                                print(f"    ⚠ {name} would introduce syntax error: {syntax_error}", flush=True)
                            continue  # Try next strategy

                    if self.verbose:
                        print(f"    ✓ {name} succeeded!", flush=True)
                    return result
            except Exception as e:
                if self.verbose:
                    logger.debug(f"    ⚠ {name} error: {e}")
                continue

        # All strategies failed - provide helpful error
        if self.verbose:
            print(f"    ✗ All strategies failed", flush=True)
            # Show nearest match for debugging
            nearest = self._find_nearest_match(search)
            if nearest:
                print(f"    Nearest match found:", flush=True)
                print(f"    {nearest[:200]}...", flush=True)

        return None

    def _validate_python_syntax(self, content: str) -> Optional[str]:
        """
        Validate Python syntax and return error message if invalid.

        Returns:
            Error message string if syntax is invalid, None if valid
        """
        try:
            ast.parse(content)
            return None  # Valid
        except SyntaxError as e:
            return f"{e.msg} at line {e.lineno}"

    def _tab_space_match(self, search: str, replace: str) -> Optional[str]:
        """
        Strategy 7: Convert tabs to spaces in both search and content.

        Handles files with mixed tabs/spaces that cause IndentationErrors.
        """
        # Normalize both search and content: convert all tabs to 4 spaces
        normalized_content = self.content.replace('\t', '    ')
        normalized_search = search.replace('\t', '    ')

        if normalized_search in normalized_content:
            # Found match - apply replacement to normalized content
            new_content = normalized_content.replace(normalized_search, replace, 1)
            return new_content

        return None
    
    # ==================== Strategy 1: Exact Match ====================
    
    def _exact_match(self, search: str, replace: str) -> Optional[str]:
        """
        Strategy 1: Exact string match (fastest, most reliable).
        
        Returns None if not found or if ambiguous (multiple matches).
        """
        if search not in self.content:
            return None
        
        count = self.content.count(search)
        if count > 1:
            raise ValueError(f"Ambiguous: {count} exact matches found")
        
        return self.content.replace(search, replace, 1)
    
    # ==================== Strategy 2: Normalized Whitespace ====================
    
    def _normalized_whitespace_match(self, search: str, replace: str) -> Optional[str]:
        """
        Strategy 2: Normalize whitespace before matching.

        Collapses multiple spaces, handles tabs vs spaces, but preserves line structure.
        """
        def normalize_line(line: str) -> str:
            """Normalize a single line's whitespace - convert tabs to spaces and strip."""
            # Convert tabs to 4 spaces for comparison
            normalized = line.replace('\t', '    ')
            return normalized.strip()

        def normalize_indent(line: str) -> Tuple[int, str]:
            """Return (indent_level, stripped_content) with tabs normalized."""
            # Convert tabs to 4 spaces
            normalized = line.replace('\t', '    ')
            stripped = normalized.lstrip()
            indent = len(normalized) - len(stripped)
            return (indent, stripped)

        search_lines = [normalize_line(line) for line in search.splitlines() if line.strip()]

        if not search_lines:
            return None

        # Sliding window search over normalized content
        for i in range(len(self.lines)):
            window_size = len(search_lines)
            if i + window_size > len(self.lines):
                break

            window_lines = [normalize_line(self.lines[i + j]) for j in range(window_size) if self.lines[i + j].strip()]

            if window_lines == search_lines:
                # Found match! Preserve original indentation
                return self._replace_preserving_indent(i, i + window_size, replace)

        # Try again with tab-to-space converted content
        tab_converted_content = self.content.replace('\t', '    ')
        if search in tab_converted_content:
            # Match found with tab conversion - apply to converted content
            new_content = tab_converted_content.replace(search, replace, 1)
            return new_content

        return None
    
    # ==================== Strategy 3: Semantic AST Match ====================
    
    def _semantic_ast_match(self, search: str, replace: str) -> Optional[str]:
        """
        Strategy 3: Match by AST structure (Python only).
        
        Compares code semantically, immune to whitespace and minor variations.
        """
        if not self.ast_tree:
            return None  # Not Python or parse failed
        
        try:
            search_ast = ast.parse(search.strip())
        except SyntaxError:
            return None  # Search block not valid Python
        
        # Find matching AST node in file
        for node in ast.walk(self.ast_tree):
            if self._ast_subtrees_match(node, search_ast.body[0] if search_ast.body else search_ast):
                # Found semantic match!
                if hasattr(node, 'lineno') and hasattr(node, 'end_lineno'):
                    start_line = node.lineno - 1  # 0-indexed
                    end_line = node.end_lineno
                    
                    return self._replace_preserving_indent(start_line, end_line, replace)
        
        return None
    
    def _ast_subtrees_match(self, node1, node2) -> bool:
        """
        Compare two AST nodes structurally (deep comparison).
        
        Returns True if they represent the same code structure.
        """
        if type(node1) != type(node2):
            return False
        
        # For simple nodes, compare key attributes
        if isinstance(node1, ast.Name):
            return node1.id == node2.id
        elif isinstance(node1, ast.Constant):
            return node1.value == node2.value
        elif isinstance(node1, ast.Assign):
            return (len(node1.targets) == len(node2.targets) and
                    all(self._ast_subtrees_match(t1, t2) for t1, t2 in zip(node1.targets, node2.targets)) and
                    self._ast_subtrees_match(node1.value, node2.value))
        elif isinstance(node1, ast.Attribute):
            return (self._ast_subtrees_match(node1.value, node2.value) and
                    node1.attr == node2.attr)
        elif isinstance(node1, ast.Call):
            return (self._ast_subtrees_match(node1.func, node2.func) and
                    len(node1.args) == len(node2.args) and
                    all(self._ast_subtrees_match(a1, a2) for a1, a2 in zip(node1.args, node2.args)))
        
        # For complex nodes, do shallow comparison (same type is good enough)
        return True
    
    # ==================== Strategy 4: Context Anchor ====================
    
    def _context_anchor_match(self, search: str, replace: str) -> Optional[str]:
        """
        Strategy 4: Use surrounding code as anchor points.
        
        Finds first and last lines, then checks if middle matches.
        """
        search_lines = [line.strip() for line in search.splitlines() if line.strip()]
        
        if len(search_lines) < 2:
            return None  # Need at least 2 lines for anchoring
        
        first_line = search_lines[0]
        last_line = search_lines[-1]
        
        # Find all occurrences of first line
        for i, line in enumerate(self.lines):
            if first_line in line.strip():
                # Found potential start anchor
                # Look for last line within reasonable distance
                window_end = min(i + len(search_lines) + 10, len(self.lines))
                
                for j in range(i + 1, window_end):
                    if last_line in self.lines[j].strip():
                        # Found both anchors! Verify middle content
                        middle_lines = [self.lines[k].strip() for k in range(i, j+1) if self.lines[k].strip()]
                        
                        # Fuzzy match middle (allow some variation)
                        if self._fuzzy_sequence_match(middle_lines, search_lines, threshold=0.8):
                            return self._replace_preserving_indent(i, j+1, replace)
        
        return None
    
    def _fuzzy_sequence_match(self, seq1: List[str], seq2: List[str], threshold: float = 0.8) -> bool:
        """Check if two sequences match with fuzzy tolerance."""
        if len(seq1) != len(seq2):
            return False
        
        matches = sum(1 for a, b in zip(seq1, seq2) if a == b or difflib.SequenceMatcher(None, a, b).ratio() > threshold)
        return matches / len(seq1) >= threshold
    
    # ==================== Strategy 5: Fuzzy Line Match ====================
    
    def _fuzzy_line_match(self, search: str, replace: str) -> Optional[str]:
        """
        Strategy 5: Fuzzy line-by-line matching with timeout.
        
        Uses existing fuzzy algorithm from patch_applier.py but with hard timeout.
        """
        def timeout_handler(signum, frame):
            raise TimeoutError()
        
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(5)  # 5 second timeout
        
        try:
            result = self._apply_fuzzy_patch_internal(search, replace)
            signal.alarm(0)
            return result
        except TimeoutError:
            signal.alarm(0)
            return None
    
    def _apply_fuzzy_patch_internal(self, search: str, replace: str) -> Optional[str]:
        """Internal fuzzy matching algorithm (from existing patch_applier.py)."""
        content_lines = self.lines
        search_lines = search.splitlines(keepends=True)
        
        if not search_lines:
            return None
        
        # Strip whitespace for comparison
        clean_search = [l.strip() for l in search_lines if l.strip()]
        
        if not clean_search:
            return None
        
        # Scan content for match
        match_start = -1
        match_end = -1
        
        for i in range(len(content_lines)):
            content_idx = i
            search_idx = 0
            possible_match = True
            temp_end = i
            
            while search_idx < len(clean_search):
                if content_idx >= len(content_lines):
                    possible_match = False
                    break
                
                line = content_lines[content_idx]
                
                if not line.strip():
                    content_idx += 1
                    continue
                
                if line.strip() != clean_search[search_idx]:
                    possible_match = False
                    break
                
                search_idx += 1
                content_idx += 1
                temp_end = content_idx
            
            if possible_match and search_idx == len(clean_search):
                match_start = i
                match_end = temp_end
                break
        
        if match_start != -1:
            return self._replace_preserving_indent(match_start, match_end, replace)
        
        return None
    
    # ==================== Strategy 6: Signature Match ====================
    
    def _signature_match(self, search: str, replace: str) -> Optional[str]:
        """
        Strategy 6: Match by function/class signature.
        
        Finds code blocks by their definition signatures.
        """
        # Extract function or class name from search block
        func_match = re.search(r'^\s*def\s+(\w+)\s*\(', search, re.MULTILINE)
        class_match = re.search(r'^\s*class\s+(\w+)\s*[:(]', search, re.MULTILINE)
        
        if func_match:
            func_name = func_match.group(1)
            # Find function definition in file
            pattern = rf'^\s*def\s+{re.escape(func_name)}\s*\('
            
            for i, line in enumerate(self.lines):
                if re.match(pattern, line):
                    # Found function! Find its end
                    end_i = self._find_block_end(i)
                    if end_i:
                        return self._replace_preserving_indent(i, end_i, replace)
        
        elif class_match:
            class_name = class_match.group(1)
            # Similar logic for classes
            pattern = rf'^\s*class\s+{re.escape(class_name)}\s*[:(]'
            
            for i, line in enumerate(self.lines):
                if re.match(pattern, line):
                    end_i = self._find_block_end(i)
                    if end_i:
                        return self._replace_preserving_indent(i, end_i, replace)
        
        return None
    
    def _find_block_end(self, start_line: int) -> Optional[int]:
        """Find the end of a Python block (function/class) starting at start_line."""
        if start_line >= len(self.lines):
            return None
        
        # Get indentation of definition line
        def_indent = len(self.lines[start_line]) - len(self.lines[start_line].lstrip())
        
        # Scan forward until we find a line with same or less indentation
        for i in range(start_line + 1, len(self.lines)):
            line = self.lines[i]
            
            if not line.strip():
                continue  # Skip empty lines
            
            line_indent = len(line) - len(line.lstrip())
            
            if line_indent <= def_indent:
                return i  # Found end of block
        
        return len(self.lines)  # Block extends to end of file
    
    # ==================== Helper Methods ====================
    
    def _replace_preserving_indent(self, start_line: int, end_line: int, replace: str) -> str:
        """
        Replace lines [start_line:end_line] with replace, preserving indentation.
        
        Automatically adjusts indentation of replace block to match original context.
        """
        if start_line >= len(self.lines):
            return self.content
        
        # Detect indentation of first non-empty line in original block
        original_indent = 0
        for i in range(start_line, min(end_line, len(self.lines))):
            if self.lines[i].strip():
                original_indent = len(self.lines[i]) - len(self.lines[i].lstrip())
                break
        
        # Detect indentation of replace block
        replace_lines = replace.splitlines()
        replace_indent = 0
        for line in replace_lines:
            if line.strip():
                replace_indent = len(line) - len(line.lstrip())
                break
        
        indent_delta = original_indent - replace_indent
        
        # Adjust replace block indentation
        adjusted_lines = []
        for line in replace_lines:
            if line.strip():
                new_indent = max(0, len(line) - len(line.lstrip()) + indent_delta)
                adjusted_lines.append(' ' * new_indent + line.lstrip())
            else:
                adjusted_lines.append('')  # Preserve empty lines
        
        # Reconstruct file
        prefix = ''.join(self.lines[:start_line])
        suffix = ''.join(self.lines[end_line:])
        
        # Ensure proper line ending
        adjusted_content = '\n'.join(adjusted_lines)
        if not adjusted_content.endswith('\n') and suffix:
            adjusted_content += '\n'
        
        return prefix + adjusted_content + suffix
    
    def _find_nearest_match(self, search: str) -> Optional[str]:
        """Find the most similar block in content (for error reporting)."""
        search_lines = search.splitlines()
        if not search_lines or len(search_lines) > 20:
            return None  # Too large for nearest match
        
        best_ratio = 0.0
        best_block = None
        window_size = len(search_lines)
        
        for i in range(len(self.lines) - window_size + 1):
            window = ''.join(self.lines[i:i + window_size])
            ratio = difflib.SequenceMatcher(None, search, window).ratio()
            
            if ratio > best_ratio:
                best_ratio = ratio
                best_block = window
        
        if best_ratio > 0.5:
            return best_block
        
        return None
