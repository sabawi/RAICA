class RAGGError(Exception):
    """Base exception for all RAGG errors."""
    pass

class ParseError(RAGGError):
    """Failed to parse source file."""
    def __init__(self, file_path: str, line: int = 0, message: str = "Parse error"):
        self.file_path = file_path
        self.line = line
        super().__init__(f"{file_path}:{line}: {message}")

class AdapterNotFoundError(RAGGError):
    """No adapter registered for file extension."""
    pass

class SymbolNotFoundError(RAGGError):
    """Symbol not found in graph."""
    pass

class RefactoringError(RAGGError):
    """Base for refactoring failures."""
    pass

class CollisionError(RefactoringError):
    """Rename would cause name collision."""
    def __init__(self, symbol: str, conflicting_scope: str):
        super().__init__(
            f"Cannot rename to '{symbol}': already defined in {conflicting_scope}"
        )

class ShadowingError(RefactoringError):
    """Rename would cause shadowing."""
    pass

class StorageError(RAGGError):
    """Database or file system error."""
    pass

class LLMError(RAGGError):
    """LLM provider error."""
    pass
