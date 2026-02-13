from typing import Protocol, Iterator, Tuple, Dict, Any, Union
from tree_sitter import Tree
from ..core.models import UIRNode, UIREdge

class LanguageAdapter(Protocol):
    """
    Stateless transformer: converts source to UIR stream.
    Each adapter handles one language family.
    """
    
    @property
    def language_id(self) -> str:
        """Unique identifier: 'python', 'javascript', etc."""
        ...
    
    @property
    def file_extensions(self) -> Tuple[str, ...]:
        """Supported extensions: ('.py',) or ('.js', '.jsx', '.ts')"""
        ...
    
    def parse(self, content: bytes, file_path: str) -> Tree:
        """Parse source into Tree-sitter CST."""
        ...
    
    def extract(self, tree: Tree, source: bytes, file_path: str) -> Iterator[Union[UIRNode, UIREdge]]:
        """Extract UIR elements from parsed tree."""
        ...
    
    def get_query_files(self) -> Dict[str, str]:
        """Return paths to tags.scm, queries files."""
        ...
    
    def supports_incremental(self) -> bool:
        """Whether adapter supports incremental re-parsing."""
        return True
