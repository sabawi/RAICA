import hashlib
from typing import Iterator, Tuple, Dict, Any, Union, List, Optional
from pathlib import Path

# tree_sitter and tree_sitter_languages might not be installed immediately 
# when this file is written, so we handle imports inside methods or use try/except block
# However, standard practice is top-level imports. We assume dependency install finishes.
try:
    from tree_sitter import Language, Parser, Tree, Node
    import tree_sitter_languages
except ImportError:
    # This will fail at runtime if deps aren't installed yet, which is expected
    pass

from ..core.models import UIRNode, UIREdge, NodeKind, EdgeKind, TextRange
from .base import LanguageAdapter

class PythonAdapter(LanguageAdapter):
    """Python language adapter using Tree-sitter."""
    
    def __init__(self):
        self._language = tree_sitter_languages.get_language('python')
        self._parser = Parser()
        self._parser.set_language(self._language)
        
        # Load queries
        query_path = Path(__file__).parent / "queries" / "python" / "tags.scm"
        if query_path.exists():
            with open(query_path, "r") as f:
                self._query_scm = f.read()
            self._query = self._language.query(self._query_scm)
        else:
            self._query = None
            
    @property
    def language_id(self) -> str:
        return 'python'
    
    @property
    def file_extensions(self) -> Tuple[str, ...]:
        return ('.py',)
    
    def parse(self, content: bytes, file_path: str) -> Tree:
        return self._parser.parse(content)
        
    def extract(self, tree: Tree, source: bytes, file_path: str) -> Iterator[Union[UIRNode, UIREdge]]:
        if not self._query:
            return
            
        captures = self._query.captures(tree.root_node)
        
        # First pass: Extract all nodes and track them
        nodes_by_name = {}  # name -> UIRNode
        
        for node, tag in captures:
            if tag == 'function.scope':
                uir_node = self._process_function(node, source, file_path)
                nodes_by_name[uir_node.name] = uir_node
                yield uir_node
            elif tag == 'class.scope':
                uir_node = self._process_class(node, source, file_path)
                nodes_by_name[uir_node.name] = uir_node
                yield uir_node
        
        # Second pass: Extract edges (calls)
        for node, tag in captures:
            if tag == 'call.site':
                # Extract the function being called
                func_name = None
                for child, child_tag in self._query.captures(node):
                    if child_tag == 'call.function':
                        func_name = source[child.start_byte:child.end_byte].decode('utf-8')
                        break
                    elif child_tag == 'call.method':
                        func_name = source[child.start_byte:child.end_byte].decode('utf-8')
                        break
                
                if func_name:
                    # Find the containing function
                    parent_func = self._find_containing_function(node, source)
                    if parent_func and parent_func in nodes_by_name:
                        src_node = nodes_by_name[parent_func]
                        
                        # Create CALLS edge (dst will be resolved later by symbol resolver)
                        edge = UIREdge(
                            src_id=src_node.id,
                            dst_id=f"unresolved:{func_name}",  # Placeholder
                            kind=EdgeKind.CALLS,
                            weight=1.0,
                            metadata={'call_name': func_name, 'file_path': file_path}
                        )
                        yield edge
                
    def _process_function(self, node: Node, source: bytes, file_path: str) -> UIRNode:
        # Extract name
        name_node = node.child_by_field_name('name')
        name = source[name_node.start_byte:name_node.end_byte].decode('utf-8') if name_node else "anonymous"
        
        # Create ID
        sig_hash = hashlib.sha256(f"{file_path}:{name}:{node.start_point}".encode()).hexdigest()
        
        return UIRNode(
            id=sig_hash,
            file_path=file_path,
            kind=NodeKind.FUNCTION,
            name=name,
            range=TextRange(
                start_line=node.start_point[0] + 1,
                start_col=node.start_point[1],
                end_line=node.end_point[0] + 1,
                end_col=node.end_point[1]
            ),
            type_sig=None, # Helper to extract signature
            docstring=None # Helper to extract docstring
        )

    def _process_class(self, node: Node, source: bytes, file_path: str) -> UIRNode:
        name_node = node.child_by_field_name('name')
        name = source[name_node.start_byte:name_node.end_byte].decode('utf-8') if name_node else "anonymous"
        
        sig_hash = hashlib.sha256(f"{file_path}:{name}:{node.start_point}".encode()).hexdigest()
        
        return UIRNode(
            id=sig_hash,
            file_path=file_path,
            kind=NodeKind.CLASS,
            name=name,
            range=TextRange(
                start_line=node.start_point[0] + 1,
                start_col=node.start_point[1],
                end_line=node.end_point[0] + 1,
                end_col=node.end_point[1]
            )
        )

    def _find_containing_function(self, call_node: Node, source: bytes) -> Optional[str]:
        """Find the function that contains this call site."""
        # Walk up the tree to find enclosing function
        current = call_node.parent
        while current:
            if current.type == 'function_definition':
                name_node = current.child_by_field_name('name')
                if name_node:
                    return source[name_node.start_byte:name_node.end_byte].decode('utf-8')
            current = current.parent
        return None

    def get_query_files(self) -> Dict[str, str]:
        return {}
