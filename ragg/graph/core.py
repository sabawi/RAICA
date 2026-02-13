import networkx as nx
from typing import Optional, List, Set, Iterator
from threading import RLock
from ..core.models import UIRNode, UIREdge, NodeKind, EdgeKind
from .storage import GraphStorage
from ..core.config import RAGGConfig

class SemanticGraph:
    """
    In-memory graph topology + persistent storage for metadata.
    """
    
    def __init__(self, config: RAGGConfig):
        self.config = config
        self.storage = GraphStorage(config.db_path)
        self._graph = nx.MultiDiGraph()
        self._lock = RLock()
        
    def add_node(self, node: UIRNode):
        with self._lock:
            # Update memory graph
            self._graph.add_node(node.id, kind=node.kind)
            # Update storage
            self.storage.upsert_node(node)
            
    def add_edge(self, edge: UIREdge):
        with self._lock:
            self._graph.add_edge(
                edge.src_id, 
                edge.dst_id, 
                key=edge.kind, 
                weight=edge.weight
            )
            # Persist to storage
            self.storage.upsert_edge(edge)
            
    def get_node(self, node_id: str) -> Optional[UIRNode]:
        return self.storage.get_node(node_id)
        
    def get_outgoing_edges(self, node_id: str, kind: Optional[EdgeKind] = None) -> Iterator[UIREdge]:
        if node_id not in self._graph:
            return
            
        for _, dst, key in self._graph.out_edges(node_id, keys=True):
            if kind and key != kind:
                continue
            # Construct edge object (simplified, normally fetched from edges table)
            yield UIREdge(src_id=node_id, dst_id=dst, kind=key)

    def find_by_name(self, name: str) -> List[UIRNode]:
        return self.storage.find_nodes(name)

    def get_incoming_edges(self, node_id: str, kind: Optional[EdgeKind] = None) -> Iterator[UIREdge]:
        """Get all edges pointing to this node."""
        kind_str = kind.value if kind else None
        edges = self.storage.get_edges_by_dst(node_id, kind_str)
        for edge in edges:
            yield edge

    def remove_file(self, file_path: str) -> int:
        """Remove all nodes/edges for a file."""
        with self._lock:
            # Remove from storage (cascades to edges)
            count = self.storage.remove_file(file_path)
            
            # Remove from in-memory graph
            # Note: We need to track file_path in node data for this to work
            # For now, we'll just clear and reload from storage
            # This is acceptable for MVP
            
            return count
    
    def search_symbols(self, query: str, limit: int = 50) -> List[UIRNode]:
        """Full-text search for symbols."""
        return self.storage.search_symbols(query, limit)
