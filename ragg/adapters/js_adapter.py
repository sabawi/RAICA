import hashlib
from typing import Iterator, Tuple, Dict, Any, Union, List, Optional
from pathlib import Path

try:
    from tree_sitter import Language, Parser, Tree, Node
    import tree_sitter_languages
except ImportError:
    pass

from ..core.models import UIRNode, UIREdge, NodeKind, EdgeKind, TextRange
from .base import LanguageAdapter

class JavaScriptAdapter(LanguageAdapter):
    """JavaScript/TypeScript language adapter using Tree-sitter."""
    
    def __init__(self, language: str = 'javascript'):
        """
        Args:
            language: 'javascript' or 'typescript'
        """
        self._lang_id = language
        self._language = tree_sitter_languages.get_language(language)
        self._parser = Parser()
        self._parser.set_language(self._language)
        
        # Load queries
        query_path = Path(__file__).parent / "queries" / "javascript" / "tags.scm"
        if query_path.exists():
            with open(query_path, "r") as f:
                self._query_scm = f.read()
            self._query = self._language.query(self._query_scm)
        else:
            self._query = None
            
    @property
    def language_id(self) -> str:
        return self._lang_id
    
    @property
    def file_extensions(self) -> Tuple[str, ...]:
        if self._lang_id == 'typescript':
            return ('.ts', '.tsx')
        return ('.js', '.jsx', '.mjs')
    
    def parse(self, content: bytes, file_path: str) -> Tree:
        return self._parser.parse(content)
        
    def extract(self, tree: Tree, source: bytes, file_path: str) -> Iterator[Union[UIRNode, UIREdge]]:
        if not self._query:
            return
            
        captures = self._query.captures(tree.root_node)
        
        # First pass: nodes
        nodes_by_name = {}
        
        for node, tag in captures:
            if tag == 'function_scope':
                uir_node = self._process_function(node, source, file_path)
                nodes_by_name[uir_node.name] = uir_node
                yield uir_node
            elif tag == 'class_scope':
                uir_node = self._process_class(node, source, file_path)
                nodes_by_name[uir_node.name] = uir_node
                yield uir_node
            elif tag == 'method_scope':
                uir_node = self._process_method(node, source, file_path)
                nodes_by_name[uir_node.name] = uir_node
                yield uir_node
        
        # Second pass: edges
        for node, tag in captures:
            if tag == 'call_site':
                func_name = self._extract_call_name(node, source)
                if func_name:
                    parent_func = self._find_containing_function(node, source)
                    if parent_func and parent_func in nodes_by_name:
                        src_node = nodes_by_name[parent_func]
                        edge = UIREdge(
                            src_id=src_node.id,
                            dst_id=f"unresolved:{func_name}",
                            kind=EdgeKind.CALLS,
                            metadata={'call_name': func_name, 'file_path': file_path}
                        )
                        yield edge
    
    def _process_function(self, node: Node, source: bytes, file_path: str) -> UIRNode:
        name_node = node.child_by_field_name('name')
        name = source[name_node.start_byte:name_node.end_byte].decode('utf-8') if name_node else "anonymous"
        
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
            )
        )
    
    def _process_class(self, node: Node, source: bytes, file_path: str) -> UIRNode:
        name_node = node.child_by_field_name('name')
        name = source[name_node.start_byte:name_node.end_byte].decode('utf-8') if name_node else "AnonymousClass"
        
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
    
    def _process_method(self, node: Node, source: bytes, file_path: str) -> UIRNode:
        name_node = node.child_by_field_name('name')
        name = source[name_node.start_byte:name_node.end_byte].decode('utf-8') if name_node else "method"
        
        sig_hash = hashlib.sha256(f"{file_path}:{name}:{node.start_point}".encode()).hexdigest()
        
        return UIRNode(
            id=sig_hash,
            file_path=file_path,
            kind=NodeKind.METHOD,
            name=name,
            range=TextRange(
                start_line=node.start_point[0] + 1,
                start_col=node.start_point[1],
                end_line=node.end_point[0] + 1,
                end_col=node.end_point[1]
            )
        )
    
    def _extract_call_name(self, call_node: Node, source: bytes) -> Optional[str]:
        """Extract function name from call expression."""
        func_node = call_node.child_by_field_name('function')
        if not func_node:
            return None
        
        if func_node.type == 'identifier':
            return source[func_node.start_byte:func_node.end_byte].decode('utf-8')
        elif func_node.type == 'member_expression':
            prop_node = func_node.child_by_field_name('property')
            if prop_node:
                return source[prop_node.start_byte:prop_node.end_byte].decode('utf-8')
        
        return None
    
    def _find_containing_function(self, call_node: Node, source: bytes) -> Optional[str]:
        """Find the function that contains this call site."""
        current = call_node.parent
        while current:
            if current.type in ('function_declaration', 'method_definition'):
                name_node = current.child_by_field_name('name')
                if name_node:
                    return source[name_node.start_byte:name_node.end_byte].decode('utf-8')
            current = current.parent
        return None
    
    def get_query_files(self) -> Dict[str, str]:
        return {}
    
    def supports_incremental(self) -> bool:
        return True
