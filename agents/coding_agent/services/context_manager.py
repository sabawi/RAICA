"""
Context Manager for RAICA Coding Agent.

This module handles the prioritization, budgeting, and assembly of context
for LLM prompts. It ensures that the most critical information is included
while respecting token limits.
"""

from enum import IntEnum
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

class ContextPriority(IntEnum):
    """
    Priority levels for context items.
    Lower number means higher priority (processed first).
    """
    CRITICAL_ERROR = 0   # Error traces, exceptions
    USER_REQUEST = 1    # The user's prompt/instruction
    SYSTEM_INSTRUCTION = 2 # Core system prompts
    TOOL_RESULT = 3     # Output from executed tools (recent)
    FILE_CONTENT = 4    # Content of read files
    PLANNING_DOC = 5    # Implementation plans, tasks
    CONVERSATION_HISTORY = 6 # Previous turns
    LOW_PRIORITY = 99   # Other info

@dataclass
class ContextItem:
    """A single item of context."""
    type: str # e.g. "error", "file", "user_msg"
    content: str
    priority: ContextPriority
    tokens: int
    metadata: Dict[str, Any] = None

class TokenBudget:
    """Manages token limits and tracking."""
    
    def __init__(self, max_tokens: int = 4000):
        self.max_tokens = max_tokens
        self.current_tokens = 0
        
    def check_fit(self, tokens: int) -> bool:
        """Check if adding tokens would exceed budget."""
        return (self.current_tokens + tokens) <= self.max_tokens
        
    def add(self, tokens: int):
        """Register usage of tokens."""
        self.current_tokens += tokens
        
    def reset(self):
        self.current_tokens = 0
        
    def remaining(self) -> int:
        return max(0, self.max_tokens - self.current_tokens)

class ContextManager:
    """
    Intelligent Context Manager.
    
    Accumulates context items and assembles them based on priority.
    """
    
    def __init__(self, max_tokens: int = 8000): # Default context window
        self.budget = TokenBudget(max_tokens)
        self.items: List[ContextItem] = []
        
    def add_context_item(
        self,
        type: str,
        content: str,
        priority: ContextPriority,
        metadata: Dict[str, Any] = None
    ):
        """Add an item to the context pool."""
        # Simple estimation: 1 token ~= 4 chars
        estimated_tokens = len(content) // 4
        
        item = ContextItem(
            type=type,
            content=content,
            priority=priority,
            tokens=estimated_tokens,
            metadata=metadata or {}
        )
        self.items.append(item)
        logger.debug(f"Added context: {type} (p={priority.name}, tokens={estimated_tokens})")

    def clear(self):
        """Clear all context items."""
        self.items = []
        self.budget.reset()

    def compile_context(self) -> str:
        """
        Assemble the final context string.
        
        Sorts items by priority and includes as many as possible
        within the token budget.
        """
        # Sort by priority (asc)
        sorted_items = sorted(self.items, key=lambda x: x.priority)
        
        final_context_parts = []
        self.budget.reset()
        
        dropped_items = []
        
        for item in sorted_items:
            if self.budget.check_fit(item.tokens):
                self.budget.add(item.tokens)
                final_context_parts.append(item.content)
            else:
                dropped_items.append(f"{item.type} ({item.priority.name})")
        
        if dropped_items:
            logger.warning(f"Context truncated. Dropped: {', '.join(dropped_items)}")
            
        return "\n\n".join(final_context_parts)

    def get_structured_context(self) -> List[Dict]:
        """
        Return context items structured (e.g. for chat messages format).
        Uses same prioritization logic but returns list of dicts.
        """
        sorted_items = sorted(self.items, key=lambda x: x.priority)
        self.budget.reset()
        
        final_items = []
        
        for item in sorted_items:
            if self.budget.check_fit(item.tokens):
                self.budget.add(item.tokens)
                final_items.append({
                    "role": "user" if item.priority == ContextPriority.USER_REQUEST else "system",
                    "content": item.content,
                    "metadata": item.metadata
                })
        
        return final_items
