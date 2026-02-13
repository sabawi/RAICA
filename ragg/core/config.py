import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List

@dataclass
class RAGGConfig:
    """Central configuration for RAGG engine."""
    
    # Storage paths
    storage_dir: Path = field(default_factory=lambda: Path.home() / ".raica" / "ragg_storage")
    db_name: str = "ragg_index.db"
    vector_db_path: str = "vector_store"
    
    # Indexing settings
    max_file_size_kb: int = 1024  # Skip files larger than 1MB
    excluded_dirs: List[str] = field(default_factory=lambda: [
        ".git", "__pycache__", "node_modules", "venv", ".venv", "dist", "build"
    ])
    allowed_extensions: List[str] = field(default_factory=lambda: [
        ".py", ".js", ".ts", ".jsx", ".tsx"
    ])
    
    # LLM Settings
    token_budget: int = 8000
    embedding_model: str = "all-MiniLM-L6-v2"
    
    # Threading
    worker_threads: int = 4
    
    def __post_init__(self):
        # Expand user path
        self.storage_dir = self.storage_dir.expanduser()
        os.makedirs(self.storage_dir, exist_ok=True)
        
    @property
    def db_path(self) -> Path:
        return self.storage_dir / self.db_name
        
    @property
    def full_vector_db_path(self) -> Path:
        return self.storage_dir / self.vector_db_path

def load_config() -> RAGGConfig:
    """Load configuration from env or defaults."""
    # In future, can load from yaml/json
    return RAGGConfig()
