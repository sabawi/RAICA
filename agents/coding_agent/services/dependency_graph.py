"""
Dependency Graph Service
========================

Builds and maintains a dependency graph of the project's codebase.
Uses AST parsing to understand imports and relationships between files.

Key Features:
- AST-based parsing for accurate Python import resolution
- finding dependents (reverse dependencies) for regression testing
- tracing dependencies for context gathering
"""

import ast
import logging
import os
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple

logger = logging.getLogger(__name__)

class DependencyGraphService:
    """
    Service to build and query the project's dependency graph.
    """

    def __init__(self, project_dir: Path):
        self.project_dir = Path(project_dir)
        # Adjacency list: file_path -> set(imported_files)
        self._dependencies: Dict[str, Set[str]] = {}
        # Reverse adjacency: file_path -> set(dependent_files_that_import_me)
        self._dependents: Dict[str, Set[str]] = {}
        # Cache mapping module names to file paths (e.g. 'utils.string' -> 'utils/string.py')
        self._module_map: Dict[str, str] = {}
        
        self._graph_built = False

    def build_graph(self) -> None:
        """Parse all Python files and build the graph."""
        self._dependencies = {}
        self._dependents = {}
        self._module_map = {}
        
        # 1. Map all modules first
        self._scan_modules()
        
        # 2. Parse imports
        for file_path in self._module_map.values():
            self._parse_file_imports(file_path)
            
        self._graph_built = True
        logger.info(f"Dependency graph built: {len(self._module_map)} modules")

    def get_dependents(self, file_path: str, recursive: bool = True) -> Set[str]:
        """
        Get files that depend on (import) the given file.
        Useful for finding tests that need to run when a file changes.
        """
        if not self._graph_built:
            self.build_graph()
            
        rel_path = self._normalize_path(file_path)
        if not rel_path:
            return set()

        direct_dependents = self._dependents.get(rel_path, set())
        
        if not recursive:
            return direct_dependents
            
        # BFS for transitive dependents
        visited = set()
        queue = list(direct_dependents)
        
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            
            # Add files that import 'current'
            next_dependents = self._dependents.get(current, set())
            queue.extend(next_dependents)
            
        return visited

    def get_dependencies(self, file_path: str, recursive: bool = False) -> Set[str]:
        """
        Get files that the given file imports.
        Useful for context gathering.
        """
        if not self._graph_built:
            self.build_graph()
            
        rel_path = self._normalize_path(file_path)
        if not rel_path:
            return set()
            
        direct_deps = self._dependencies.get(rel_path, set())
        
        if not recursive:
            return direct_deps
            
        visited = set()
        queue = list(direct_deps)
        
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            
            next_deps = self._dependencies.get(current, set())
            queue.extend(next_deps)
            
        return visited

    def _scan_modules(self) -> None:
        """Scan project to map module names to file paths."""
        for root, _, files in os.walk(self.project_dir):
            for file in files:
                if file.endswith('.py'):
                    full_path = Path(root) / file
                    rel_path = str(full_path.relative_to(self.project_dir))
                    
                    # Convert path to module name
                    # e.g. agents/coding/utils.py -> agents.coding.utils
                    module_name = rel_path.replace(os.sep, '.')[:-3]
                    if file == '__init__.py':
                        module_name = module_name[:-9] # strip .__init__
                    
                    self._module_map[module_name] = rel_path
                    # Also map the filename itself as a key for easier lookup
                    self._module_map[rel_path] = rel_path

    def _parse_file_imports(self, rel_path: str) -> None:
        """Parse a single file for imports."""
        full_path = self.project_dir / rel_path
        try:
            content = full_path.read_text(encoding='utf-8')
            tree = ast.parse(content)
            
            for node in ast.walk(tree):
                imported_modules = []
                
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imported_modules.append(alias.name)
                        
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        # from x.y import z
                        imported_modules.append(node.module)
                    elif node.level:
                        # Relative import: from . import x
                        # Resolve relative path
                        parent_module = self._resolve_relative_module(rel_path, node.level)
                        if parent_module:
                            imported_modules.append(parent_module)

                # Resolve modules to files
                for mod in imported_modules:
                    target_file = self._resolve_module_to_file(mod)
                    if target_file and target_file != rel_path:
                        self._add_edge(rel_path, target_file)
                        
        except Exception:
            # Squelch parse errors for robustness
            pass

    def _resolve_module_to_file(self, module_name: str) -> Optional[str]:
        """Resolve a module name (e.g. 'os.path') to a tracked file."""
        # Exact match
        if module_name in self._module_map:
            return self._module_map[module_name]
            
        # Prefix match (e.g. importing a package 'agents.coding' might mean 'agents/coding/__init__.py')
        # Simple heuristic: try to find longest matching prefix in our map
        # But for now, let's assume direct mapping or nothing.
        
        # Check if it's a file path pretending to be a module (sometimes happens in loose scripts)
        return None

    def _resolve_relative_module(self, current_file: str, level: int) -> Optional[str]:
        """Resolve relative import (dots)."""
        # agents/coding/utils.py -> agents.coding.utils
        parts = current_file.replace(os.sep, '.').split('.')[:-1] # drop extension
        
        if len(parts) < level:
            return None
            
        base_parts = parts[:-level]
        return '.'.join(base_parts)

    def _add_edge(self, source_file: str, target_file: str) -> None:
        """Record a dependency: source -> target."""
        if source_file not in self._dependencies:
            self._dependencies[source_file] = set()
        self._dependencies[source_file].add(target_file)
        
        if target_file not in self._dependents:
            self._dependents[target_file] = set()
        self._dependents[target_file].add(source_file)

    def _normalize_path(self, file_path: str) -> Optional[str]:
        """Ensure file path is relative and clean."""
        try:
            p = Path(file_path)
            if p.is_absolute():
                return str(p.relative_to(self.project_dir))
            return str(p)
        except Exception:
            return None
