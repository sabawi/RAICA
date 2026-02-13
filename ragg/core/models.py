from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, Dict, Any, List

class NodeKind(Enum):
    FUNCTION = "FUNCTION"
    CLASS = "CLASS"
    METHOD = "METHOD"
    VARIABLE = "VARIABLE"
    PARAMETER = "PARAMETER"
    INTERFACE = "INTERFACE"
    MODULE = "MODULE"
    IMPORT = "IMPORT"
    CONSTANT = "CONSTANT"
    TYPE_ALIAS = "TYPE_ALIAS"

class EdgeKind(Enum):
    CALLS = "CALLS"           # Function invocation
    IMPORTS = "IMPORTS"         # Module import
    DEFINES = "DEFINES"         # Symbol definition
    USES = "USES"            # Symbol reference
    INHERITS = "INHERITS"        # Class inheritance
    IMPLEMENTS = "IMPLEMENTS"      # Interface implementation
    CONTAINS = "CONTAINS"        # Structural containment
    DATA_FLOW = "DATA_FLOW"       # Variable assignment chain
    TYPE_OF = "TYPE_OF"         # Type annotation

@dataclass(frozen=True, slots=True)
class TextRange:
    start_line: int
    start_col: int
    end_line: int
    end_col: int
    
    def contains(self, line: int, col: int) -> bool:
        if line < self.start_line or line > self.end_line:
            return False
        if line == self.start_line and col < self.start_col:
            return False
        if line == self.end_line and col > self.end_col:
            return False
        return True
        
    def to_dict(self) -> Dict[str, int]:
        return {
            "start_line": self.start_line,
            "start_col": self.start_col,
            "end_line": self.end_line,
            "end_col": self.end_col
        }
        
    @classmethod
    def from_dict(cls, data: Dict[str, int]) -> 'TextRange':
        return cls(
            start_line=data["start_line"],
            start_col=data["start_col"],
            end_line=data["end_line"],
            end_col=data["end_col"]
        )

@dataclass(slots=True)
class UIRNode:
    id: str                      # SHA256 hash of signature
    file_path: str               # Absolute path
    kind: NodeKind
    name: str
    range: TextRange
    type_sig: Optional[str] = None      # Normalized type signature
    docstring: Optional[str] = None
    is_exported: bool = False
    parent_id: Optional[str] = None     # Containing scope
    metadata: Dict[str, Any] = field(default_factory=dict) # Language-specific extras
    
    @property
    def qualified_name(self) -> str:
        """Return fully qualified name including module path."""
        # Simple implementation, can be enhanced
        return f"{self.file_path}::{self.name}"

@dataclass(slots=True)
class UIREdge:
    src_id: str
    dst_id: str
    kind: EdgeKind
    weight: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def id(self) -> str:
        """Composite key for edge deduplication."""
        return f"{self.src_id}:{self.dst_id}:{self.kind.value}"
