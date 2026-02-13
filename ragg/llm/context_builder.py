from dataclasses import dataclass, field
from typing import List, Optional
from ..core.models import UIRNode, NodeKind, EdgeKind
from ..graph.core import SemanticGraph

@dataclass
class SliceItem:
    category: str  # core, dependency, usage, type, similar
    node: UIRNode
    content: str
    tokens: int

@dataclass
class ContextSlice:
    target: UIRNode
    items: List[SliceItem]
    total_tokens: int
    
    def to_prompt(self) -> str:
        """Render slice as XML-structured prompt."""
        parts = ["<context>"]
        
        # Group by file to be cleaner
        for item in self.items:
            parts.append(f'  <item category="{item.category}" file="{item.node.file_path}">')
            parts.append(f'    <definition name="{item.node.name}">')
            parts.append(item.content)
            parts.append('    </definition>')
            parts.append('  </item>')
            
        parts.append("</context>")
        return "\n".join(parts)

class ContextBuilder:
    """
    Builds optimized context for LLM consumption using Semantic Slice algorithm.
    """
    
    def __init__(self, graph: SemanticGraph):
        self.graph = graph
        
    def build_slice(self, target_symbol: str, token_budget: int = 8000) -> Optional[ContextSlice]:
        # 1. Find target
        nodes = self.graph.find_by_name(target_symbol)
        if not nodes:
            return None
        target = nodes[0] # Ambiguity handling later
        
        items: List[SliceItem] = []
        current_tokens = 0
        
        # Helper to add item
        def add_item(cat: str, node: UIRNode, content: str):
            nonlocal current_tokens
            tokens = len(content) // 4 # Rough estimate
            if current_tokens + tokens <= token_budget:
                items.append(SliceItem(cat, node, content, tokens))
                current_tokens += tokens
                return True
            return False

        # 1. Core Code
        core_code = self._read_source(target)
        if not add_item("core", target, core_code):
            return None # Can't even fit core
            
        # 2. Dependencies (Call Graph)
        for edge in self.graph.get_outgoing_edges(target.id, EdgeKind.CALLS):
            dep_node = self.graph.get_node(edge.dst_id)
            if dep_node:
                # Get signature only fordeps
                sig = f"def {dep_node.name}(...): ..." 
                add_item("dependency", dep_node, sig)
                
        # 3. Usages (Back references) - Not implemented in MVP graph yet
        
        return ContextSlice(target, items, current_tokens)

    def _read_source(self, node: UIRNode) -> str:
        try:
            with open(node.file_path, 'r') as f:
                lines = f.readlines()
                # 0-indexed to 1-indexed conversion handled in range
                start = node.range.start_line - 1
                end = node.range.end_line
                return "".join(lines[start:end])
        except Exception:
            return f"# Error reading {node.file_path}"
