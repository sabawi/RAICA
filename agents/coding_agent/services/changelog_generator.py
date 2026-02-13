"""
Changelog Generator - Human-Readable Change Descriptions
========================================================

Generates human-readable changelogs from patches.
Makes git commit messages understandable to humans.
"""

import re
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)


class ChangelogGenerator:
    """
    Generates human-readable changelogs from patches.
    
    Analyzes patches to describe what changed in plain English.
    """
    
    def generate_from_patches(
        self,
        patches: List[Dict[str, str]],
        change_type: str
    ) -> str:
        """
        Generate changelog from patch list.
        
        Args:
            patches: List of dicts with 'file', 'search', 'replace'
            change_type: Type of change (BUG_FIX, ENHANCEMENT, etc.)
            
        Returns:
            Formatted changelog string
        """
        if not patches:
            return "No code changes (configuration/data only)"
        
        changelog_lines = []
        
        # Group by file
        by_file = {}
        for patch in patches:
            file = patch.get('file', 'unknown')
            if file not in by_file:
                by_file[file] = []
            by_file[file].append(patch)
        
        # Generate per-file descriptions
        for file, file_patches in by_file.items():
            changelog_lines.append(f"\n📄 {file}")
            
            for i, patch in enumerate(file_patches, 1):
                search = patch.get('search', '')
                replace = patch.get('replace', '')
                
                # Analyze what changed
                change_desc = self._describe_change(search, replace, file)
                changelog_lines.append(f"   {i}. {change_desc}")
        
        return "\n".join(changelog_lines)
    
    def _describe_change(self, search: str, replace: str, filename: str) -> str:
        """
        Generate human-readable description of a single change.
        
        Uses heuristics to identify common patterns.
        """
        search_lines = search.splitlines()
        replace_lines = replace.splitlines()
        
        # Line count changes
        lines_added = len(replace_lines) - len(search_lines)
        
        # Detect specific patterns
        
        # Import additions
        if self._contains_pattern(replace, r"^import |^from .* import", search):
            import_names = self._extract_imports(replace, search)
            if import_names:
                return f"Added imports: {', '.join(import_names)}"
            return "Added import statement"
        
        # Function definitions
        if self._contains_pattern(replace, r"^def \w+\(", search):
            func_names = self._extract_functions(replace, search)
            if func_names:
                return f"Added/modified functions: {', '.join(func_names)}"
            return "Modified function definition"
        
        # Class definitions
        if self._contains_pattern(replace, r"^class \w+", search):
            class_names = self._extract_classes(replace, search)
            if func_names:
                return f"Added/modified classes: {', '.join(class_names)}"
            return "Modified class definition"
        
        # Method additions within classes
        if "    def " in replace and "    def " not in search:
            method_names = re.findall(r'    def (\w+)\(', replace)
            if method_names:
                return f"Added methods: {', '.join(set(method_names))}"
        
        # Comments
        if replace.count("#") > search.count("#"):
            return "Added documentation/comments"
        
        # String literals (likely messages or labels)
        if replace.count('"') > search.count('"') or replace.count("'") > search.count("'"):
            # Extract new strings
            new_strings = self._extract_new_strings(search, replace)
            if new_strings:
                preview = new_strings[0][:40] + "..." if len(new_strings[0]) > 40 else new_strings[0]
                return f"Added text/labels: \"{preview}\""
        
       # Logic changes (if/else, loops)
        if "if " in replace and "if " not in search:
            return "Added conditional logic"
        elif "for " in replace and "for " not in search:
            return "Added loop"
        elif "while " in replace and "while " not in search:
            return "Added while loop"
        
        # Try/except
        if "try:" in replace and "try:" not in search:
            return "Added error handling"
        
        # Variable assignments
        if "=" in replace and lines_added > 0:
            return "Added variable assignments/logic"
        
        # Generic descriptions based on line changes
        if lines_added > 5:
            return f"Added {lines_added} lines of code"
        elif lines_added > 0:
            return f"Added {lines_added} lines"
        elif lines_added < -5:
            return f"Removed {-lines_added} lines of code"
        elif lines_added < 0:
            return f"Removed {-lines_added} lines"
        else:
            # Same number of lines, but content changed
            return f"Modified {len(search_lines)} lines"
    
    def _contains_pattern(self, text: str, pattern: str, exclude_text: str) -> bool:
        """Check if text contains pattern that's not in exclude_text."""
        if not re.search(pattern, text, re.MULTILINE):
            return False
        if re.search(pattern, exclude_text, re.MULTILINE):
            return False
        return True
    
    def _extract_imports(self, replace: str, search: str) -> List[str]:
        """Extract newly added import names."""
        replace_imports = set(re.findall(r"import\s+([\w, ]+)", replace))
        search_imports = set(re.findall(r"import\s+([\w, ]+)", search))
        
        new_imports = replace_imports - search_imports
        return list(new_imports)
    
    def _extract_functions(self, replace: str, search: str) -> List[str]:
        """Extract newly added/modified function names."""
        replace_funcs = set(re.findall(r"def\s+(\w+)\(", replace))
        search_funcs = set(re.findall(r"def\s+(\w+)\(", search))
        
        new_funcs = replace_funcs - search_funcs
        return list(new_funcs)
    
    def _extract_classes(self, replace: str, search: str) -> List[str]:
        """Extract newly added/modified class names."""
        replace_classes = set(re.findall(r"class\s+(\w+)", replace))
        search_classes = set(re.findall(r"class\s+(\w+)", search))
        
        new_classes = replace_classes - search_classes
        return list(new_classes)
    
    def _extract_new_strings(self, search: str, replace: str) -> List[str]:
        """Extract string literals that appear in replace but not search."""
        # Simple extraction of double-quoted strings
        replace_strings = set(re.findall(r'"([^"]+)"', replace))
        search_strings = set(re.findall(r'"([^"]+)"', search))
        
        new_strings = replace_strings - search_strings
        return sorted(list(new_strings), key=len, reverse=True)[:3]  # Top 3 longest
