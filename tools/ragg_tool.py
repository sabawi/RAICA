from typing import Optional, Dict, Any, List
from ragg.core.config import load_config
from ragg.graph.core import SemanticGraph
from ragg.llm.context_builder import ContextBuilder

class RAGGTool:
    """
    Agent tool wrapper for RAGG engine.
    Allows agents to semantic search and explain code.
    """
    
    def __init__(self):
        self.config = load_config()
        self.graph = SemanticGraph(self.config)
        self.context_builder = ContextBuilder(self.graph)
        
    def find_definition(self, symbol: str) -> str:
        """Find where a symbol is defined."""
        nodes = self.graph.find_by_name(symbol)
        if not nodes:
            return f"Symbol '{symbol}' not found in index."
            
        results = []
        for node in nodes:
            results.append(f"Found {node.kind.name} '{node.name}' in {node.file_path}:{node.range.start_line}")
            
        return "\n".join(results)
        
    def get_semantic_context(self, symbol: str) -> str:
        """Get LLM-optimized context for a symbol."""
        slice = self.context_builder.build_slice(symbol)
        if not slice:
            return f"Could not build context for '{symbol}' (not found or too large)."
        return slice.to_prompt()

def main():
    # Simple test
    tool = RAGGTool()
    print(tool.find_definition("UIRNode"))

if __name__ == "__main__":
    main()
