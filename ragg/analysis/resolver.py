"""
Symbol Resolver - Resolves cross-file symbol references
"""

from typing import Optional, Dict, List
from ..core.models import UIRNode, UIREdge, EdgeKind
from ..graph.core import SemanticGraph

class SymbolResolver:
    """
    Resolves unresolved symbol references to their definitions.
    Uses lexical scoping rules with fallback chain.
    
    Resolution order:
    1. Local scope (same function/class)
    2. Enclosing scopes (parent functions/classes)
    3. Module scope (file-level definitions)
    4. Imported symbols (future)
    5. Built-in symbols (future)
    """
    
    def __init__(self, graph: SemanticGraph):
        self.graph = graph
        self._builtins = self._load_builtins()
    
    def resolve_unresolved_edges(self) -> int:
        """
        Resolve all edges with 'unresolved:' prefix in dst_id.
        Returns count of resolved edges.
        """
        # Get all edges from storage
        resolved_count = 0
        
        # Query all edges with unresolved destinations
        # For MVP, we'll iterate through all edges
        # In production, we'd add a query method for unresolved edges
        
        # Note: This is a placeholder for the actual implementation
        # The full implementation would require:
        # 1. Query method in storage to get unresolved edges
        # 2. Symbol resolution logic
        # 3. Edge update logic
        
        return resolved_count
    
    def resolve(self, symbol_name: str, context_node: UIRNode) -> Optional[UIRNode]:
        """
        Resolve a symbol reference to its definition.
        
        Args:
            symbol_name: Name of the symbol to resolve
            context_node: Node where the symbol is referenced
            
        Returns:
            UIRNode of the definition, or None if not found
        """
        # 1. Local scope (same function/class)
        if context_node.parent_id:
            if definition := self._find_in_scope(context_node.parent_id, symbol_name):
                return definition
        
        # 2. Walk up scope chain
        current_scope = context_node.parent_id
        while current_scope:
            parent = self.graph.get_node(current_scope)
            if parent and (defn := self._find_in_scope(parent.parent_id, symbol_name)):
                return defn
            current_scope = parent.parent_id if parent else None
        
        # 3. Module scope (file-level)
        if definition := self._find_in_file(context_node.file_path, symbol_name):
            return definition
        
        # 4. Imported symbols (TODO: implement import tracking)
        
        # 5. Built-ins
        return self._builtins.get(symbol_name)
    
    def _find_in_scope(self, scope_id: Optional[str], symbol_name: str) -> Optional[UIRNode]:
        """Find symbol defined in a specific scope."""
        if not scope_id:
            return None
        
        # Get all nodes with this parent using new storage method
        candidates = self.graph.storage.get_nodes_by_parent(scope_id)
        for node in candidates:
            if node.name == symbol_name:
                return node
        return None
    
    def _find_in_file(self, file_path: str, symbol_name: str) -> Optional[UIRNode]:
        """Find symbol defined at file level (top-level, no parent)."""
        # Use FTS search for fast lookup
        results = self.graph.search_symbols(symbol_name, limit=50)
        
        for node in results:
            if node.file_path == file_path and node.name == symbol_name and node.parent_id is None:
                return node
        
        return None
    
    def _load_builtins(self) -> Dict[str, UIRNode]:
        """
        Load built-in symbols (language-specific).
        For MVP, returns empty dict. Full implementation would include:
        - Python: print, len, str, int, list, dict, etc.
        - JavaScript: console, window, document, Object, Array, etc.
        """
        # TODO: Implement per-language builtins
        return {}
    
    def resolve_call_edges(self, file_path: Optional[str] = None) -> int:
        """
        Resolve unresolved CALLS edges in specified file or all files.
        
        Returns:
            Number of edges resolved
        """
        resolved = 0
        
        # Get edges to resolve (simplified - in production would query storage)
        # For now, we demonstrate the concept with a small example
        
        # This would be implemented when we have:
        # 1. A way to query unresolved edges
        # 2. The ability to update edge destinations
        
        return resolved
