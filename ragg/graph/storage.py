import sqlite3
import json
from typing import Optional, List, Iterator, Dict, Any
from pathlib import Path
from ..core.models import UIRNode, UIREdge, NodeKind, EdgeKind, TextRange

class GraphStorage:
    """Persistence layer for RAGG graph using SQLite."""
    
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._conn = None
        self._init_db()
        
    def _init_db(self):
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        
        # Enable WAL mode for concurrency
        self._conn.execute("PRAGMA journal_mode=WAL")
        
        with self._conn:
            # Nodes table
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS nodes (
                    id TEXT PRIMARY KEY,
                    file_path TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    name TEXT NOT NULL,
                    type_sig TEXT,
                    start_line INTEGER NOT NULL,
                    start_col INTEGER NOT NULL,
                    end_line INTEGER NOT NULL,
                    end_col INTEGER NOT NULL,
                    docstring TEXT,
                    is_exported INTEGER DEFAULT 0,
                    parent_id TEXT,
                    metadata TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (parent_id) REFERENCES nodes(id) ON DELETE SET NULL
                )
            """)
            
            # Edges table
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS edges (
                    id TEXT PRIMARY KEY,
                    src_id TEXT NOT NULL,
                    dst_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    weight REAL DEFAULT 1.0,
                    metadata TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (src_id) REFERENCES nodes(id) ON DELETE CASCADE,
                    FOREIGN KEY (dst_id) REFERENCES nodes(id) ON DELETE CASCADE
                )
            """)
            
            # Indexes
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_nodes_file ON nodes(file_path)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_nodes_name ON nodes(name)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src_id)")
            
            # Full-text search for symbol names and docstrings
            self._conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(
                    name,
                    docstring,
                    content='nodes',
                    content_rowid='rowid'
                )
            """)
            
            # Triggers to maintain FTS index
            self._conn.execute("""
                CREATE TRIGGER IF NOT EXISTS nodes_ai AFTER INSERT ON nodes BEGIN
                    INSERT INTO nodes_fts(rowid, name, docstring)
                    VALUES (new.rowid, new.name, new.docstring);
                END
            """)
            
            self._conn.execute("""
                CREATE TRIGGER IF NOT EXISTS nodes_au AFTER UPDATE ON nodes BEGIN
                    INSERT INTO nodes_fts(nodes_fts, rowid, name, docstring)
                    VALUES('delete', old.rowid, old.name, old.docstring);
                    INSERT INTO nodes_fts(rowid, name, docstring)
                    VALUES (new.rowid, new.name, new.docstring);
                END
            """)
            
            self._conn.execute("""
                CREATE TRIGGER IF NOT EXISTS nodes_ad AFTER DELETE ON nodes BEGIN
                    INSERT INTO nodes_fts(nodes_fts, rowid, name, docstring)
                    VALUES('delete', old.rowid, old.name, old.docstring);
                END
            """)
            
    def upsert_node(self, node: UIRNode):
        with self._conn:
            self._conn.execute("""
                INSERT OR REPLACE INTO nodes (
                    id, file_path, kind, name, type_sig, 
                    start_line, start_col, end_line, end_col,
                    docstring, is_exported, parent_id, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                node.id, node.file_path, node.kind.value, node.name, node.type_sig,
                node.range.start_line, node.range.start_col, node.range.end_line, node.range.end_col,
                node.docstring, 1 if node.is_exported else 0, node.parent_id,
                json.dumps(node.metadata)
            ))
            
    def get_node(self, node_id: str) -> Optional[UIRNode]:
        cursor = self._conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,))
        row = cursor.fetchone()
        if not row:
            return None
            
        return UIRNode(
            id=row['id'],
            file_path=row['file_path'],
            kind=NodeKind(row['kind']),
            name=row['name'],
            type_sig=row['type_sig'],
            range=TextRange(
                row['start_line'], row['start_col'],
                row['end_line'], row['end_col']
            ),
            docstring=row['docstring'],
            is_exported=bool(row['is_exported']),
            parent_id=row['parent_id'],
            metadata=json.loads(row['metadata'] or '{}')
        )
        
    def find_nodes(self, name: str) -> List[UIRNode]:
        cursor = self._conn.execute("SELECT * FROM nodes WHERE name = ?", (name,))
        return [self._row_to_node(row) for row in cursor.fetchall()]

    def get_nodes_by_parent(self, parent_id: str) -> List[UIRNode]:
        """Get all nodes defined within a scope."""
        cursor = self._conn.execute("SELECT * FROM nodes WHERE parent_id = ?", (parent_id,))
        return [self._row_to_node(row) for row in cursor.fetchall()]

    def get_nodes_by_file(self, file_path: str) -> List[UIRNode]:
        """Get all nodes in a file (optionally top-level only if needed)."""
        cursor = self._conn.execute("SELECT * FROM nodes WHERE file_path = ?", (file_path,))
        return [self._row_to_node(row) for row in cursor.fetchall()]

    def _row_to_node(self, row) -> UIRNode:
        return UIRNode(
            id=row['id'],
            file_path=row['file_path'],
            kind=NodeKind(row['kind']),
            name=row['name'],
            type_sig=row['type_sig'],
            range=TextRange(
                row['start_line'], row['start_col'],
                row['end_line'], row['end_col']
            ),
            docstring=row['docstring'],
            is_exported=bool(row['is_exported']),
            parent_id=row['parent_id'],
            metadata=json.loads(row['metadata'] or '{}')
        )

    def upsert_edge(self, edge: UIREdge):
        """Insert or update an edge."""
        with self._conn:
            self._conn.execute("""
                INSERT OR REPLACE INTO edges (
                    id, src_id, dst_id, kind, weight, metadata
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (
                edge.id, edge.src_id, edge.dst_id, edge.kind.value,
                edge.weight, json.dumps(edge.metadata)
            ))

    def get_edge(self, edge_id: str) -> Optional[UIREdge]:
        """Retrieve edge by ID."""
        cursor = self._conn.execute("SELECT * FROM edges WHERE id = ?", (edge_id,))
        row = cursor.fetchone()
        if not row:
            return None
        
        return self._row_to_edge(row)

    def get_edges_by_src(self, src_id: str, kind: Optional[str] = None) -> List[UIREdge]:
        """Get all edges from a source node."""
        if kind:
            cursor = self._conn.execute(
                "SELECT * FROM edges WHERE src_id = ? AND kind = ?", 
                (src_id, kind)
            )
        else:
            cursor = self._conn.execute(
                "SELECT * FROM edges WHERE src_id = ?", 
                (src_id,)
            )
        
        return [self._row_to_edge(row) for row in cursor.fetchall()]

    def get_edges_by_dst(self, dst_id: str, kind: Optional[str] = None) -> List[UIREdge]:
        """Get all edges to a destination node."""
        if kind:
            cursor = self._conn.execute(
                "SELECT * FROM edges WHERE dst_id = ? AND kind = ?", 
                (dst_id, kind)
            )
        else:
            cursor = self._conn.execute(
                "SELECT * FROM edges WHERE dst_id = ?", 
                (dst_id,)
            )
        
        return [self._row_to_edge(row) for row in cursor.fetchall()]

    def _row_to_edge(self, row) -> UIREdge:
        """Convert SQLite row to UIREdge."""
        return UIREdge(
            src_id=row['src_id'],
            dst_id=row['dst_id'],
            kind=EdgeKind(row['kind']),
            weight=row['weight'],
            metadata=json.loads(row['metadata'] or '{}')
        )

    def remove_file(self, file_path: str) -> int:
        """Remove all nodes and edges for a file. Returns count."""
        with self._conn:
            # Get node IDs for this file
            cursor = self._conn.execute(
                "SELECT id FROM nodes WHERE file_path = ?", 
                (file_path,)
            )
            node_ids = [row['id'] for row in cursor.fetchall()]
            
            # Delete nodes (edges will cascade)
            self._conn.execute("DELETE FROM nodes WHERE file_path = ?", (file_path,))
            
            return len(node_ids)
    
    def search_symbols(self, query: str, limit: int = 50) -> List[UIRNode]:
        """Full-text search for symbols by name or docstring."""
        cursor = self._conn.execute("""
            SELECT nodes.* FROM nodes
            JOIN nodes_fts ON nodes.rowid = nodes_fts.rowid
            WHERE nodes_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """, (query, limit))
        
        return [self._row_to_node(row) for row in cursor.fetchall()]

    def close(self):
        if self._conn:
            self._conn.close()
