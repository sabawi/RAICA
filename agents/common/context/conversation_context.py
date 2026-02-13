"""
Conversation Context
====================

Conversation history and decisions tracking.
Maintains conversation history for context and records decisions made.

Storage: ~/.raica/history/conversations/{session_id}.json
"""

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Message:
    """A conversation message."""
    role: str  # 'user', 'assistant', 'system'
    content: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'role': self.role,
            'content': self.content,
            'timestamp': self.timestamp,
            'metadata': self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Message':
        return cls(
            role=data.get('role', 'user'),
            content=data.get('content', ''),
            timestamp=data.get('timestamp', datetime.now().isoformat()),
            metadata=data.get('metadata', {}),
        )


@dataclass
class Decision:
    """A decision made during the conversation."""
    description: str
    choice: str
    rationale: str
    alternatives: List[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    context: str = ""  # What was being discussed

    def to_dict(self) -> Dict[str, Any]:
        return {
            'description': self.description,
            'choice': self.choice,
            'rationale': self.rationale,
            'alternatives': self.alternatives,
            'timestamp': self.timestamp,
            'context': self.context,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Decision':
        return cls(
            description=data.get('description', ''),
            choice=data.get('choice', ''),
            rationale=data.get('rationale', ''),
            alternatives=data.get('alternatives', []),
            timestamp=data.get('timestamp', datetime.now().isoformat()),
            context=data.get('context', ''),
        )


class ConversationContext:
    """
    Manages conversation history and decisions.
    Persists to ~/.raica/history/conversations/
    """

    CONVERSATIONS_DIR = "conversations"
    MAX_MESSAGES_IN_MEMORY = 100

    def __init__(
        self,
        global_storage: Optional[Path] = None,
        session_id: Optional[str] = None
    ):
        """
        Initialize ConversationContext.

        Args:
            global_storage: Path to global storage. Defaults to ~/.raica/
            session_id: Session ID. Auto-generated if not provided.
        """
        self.global_storage = global_storage or (Path.home() / ".raica")
        self.conversations_dir = self.global_storage / "history" / self.CONVERSATIONS_DIR

        # Session info
        self.session_id = session_id or str(uuid.uuid4())[:12]
        self.session_file = self.conversations_dir / f"{self.session_id}.json"
        self.started_at = datetime.now().isoformat()

        # Conversation data
        self.messages: List[Message] = []
        self.decisions: List[Decision] = []
        self.summary: str = ""  # Running summary of conversation

        # Tracking
        self.project_path: Optional[str] = None
        self.topics_discussed: List[str] = []

    def add_message(
        self,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Message:
        """
        Add a message to the conversation.

        Args:
            role: Message role ('user', 'assistant', 'system')
            content: Message content
            metadata: Optional metadata

        Returns:
            Created Message
        """
        message = Message(
            role=role,
            content=content,
            metadata=metadata or {}
        )
        self.messages.append(message)

        # Trim if over limit
        if len(self.messages) > self.MAX_MESSAGES_IN_MEMORY:
            self._summarize_and_trim()

        return message

    def add_user_message(self, content: str) -> Message:
        """Add a user message."""
        return self.add_message('user', content)

    def add_assistant_message(self, content: str) -> Message:
        """Add an assistant message."""
        return self.add_message('assistant', content)

    def add_system_message(self, content: str) -> Message:
        """Add a system message."""
        return self.add_message('system', content)

    def record_decision(
        self,
        description: str,
        choice: str,
        rationale: str,
        alternatives: Optional[List[str]] = None
    ) -> Decision:
        """
        Record a decision made during the conversation.

        Args:
            description: What decision was made
            choice: The chosen option
            rationale: Why this choice was made
            alternatives: Other options that were considered

        Returns:
            Created Decision
        """
        # Get recent context
        context = ""
        if self.messages:
            recent = self.messages[-3:]
            context = " | ".join([m.content[:100] for m in recent])

        decision = Decision(
            description=description,
            choice=choice,
            rationale=rationale,
            alternatives=alternatives or [],
            context=context
        )
        self.decisions.append(decision)

        logger.debug(f"Recorded decision: {description} -> {choice}")
        return decision

    def add_topic(self, topic: str) -> None:
        """Add a topic that was discussed."""
        if topic not in self.topics_discussed:
            self.topics_discussed.append(topic)

    def _summarize_and_trim(self) -> None:
        """Summarize old messages and trim the list."""
        # Keep last 50 messages, summarize the rest
        if len(self.messages) > 50:
            old_messages = self.messages[:-50]
            self.messages = self.messages[-50:]

            # Create a simple summary
            user_msgs = [m for m in old_messages if m.role == 'user']
            if user_msgs:
                topics = [m.content[:50] for m in user_msgs[:5]]
                self.summary += f"\nPrevious topics: {'; '.join(topics)}"

    def get_recent_messages(self, limit: int = 10) -> List[Message]:
        """Get recent messages."""
        return self.messages[-limit:]

    def get_messages_for_llm(self, limit: int = 20) -> List[Dict[str, str]]:
        """
        Get messages formatted for LLM context.

        Args:
            limit: Maximum messages to return

        Returns:
            List of dicts with 'role' and 'content'
        """
        messages = self.messages[-limit:]
        return [{'role': m.role, 'content': m.content} for m in messages]

    def get_recent_decisions(self, limit: int = 5) -> List[Decision]:
        """Get recent decisions."""
        return self.decisions[-limit:]

    def search_messages(self, query: str, limit: int = 10) -> List[Message]:
        """
        Search messages for a query string.

        Args:
            query: Search query
            limit: Maximum results

        Returns:
            Matching messages
        """
        query_lower = query.lower()
        matches = [
            m for m in self.messages
            if query_lower in m.content.lower()
        ]
        return matches[-limit:]

    def save(self) -> bool:
        """Save conversation to disk."""
        try:
            self.conversations_dir.mkdir(parents=True, exist_ok=True)

            data = {
                'session_id': self.session_id,
                'started_at': self.started_at,
                'project_path': self.project_path,
                'summary': self.summary,
                'topics_discussed': self.topics_discussed,
                'messages': [m.to_dict() for m in self.messages],
                'decisions': [d.to_dict() for d in self.decisions],
            }

            with open(self.session_file, 'w') as f:
                json.dump(data, f, indent=2)

            return True

        except Exception as e:
            logger.warning(f"Failed to save conversation: {e}")
            return False

    def load(self) -> bool:
        """Load conversation from disk."""
        if not self.session_file.exists():
            return False

        try:
            with open(self.session_file, 'r') as f:
                data = json.load(f)

            self.session_id = data.get('session_id', self.session_id)
            self.started_at = data.get('started_at', self.started_at)
            self.project_path = data.get('project_path')
            self.summary = data.get('summary', '')
            self.topics_discussed = data.get('topics_discussed', [])

            self.messages = [
                Message.from_dict(m) for m in data.get('messages', [])
            ]
            self.decisions = [
                Decision.from_dict(d) for d in data.get('decisions', [])
            ]

            return True

        except Exception as e:
            logger.warning(f"Failed to load conversation: {e}")
            return False

    @classmethod
    def list_sessions(
        cls,
        global_storage: Optional[Path] = None,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        List available conversation sessions.

        Args:
            global_storage: Storage path
            limit: Maximum sessions to return

        Returns:
            List of session info dicts
        """
        storage = global_storage or (Path.home() / ".raica")
        conversations_dir = storage / "history" / cls.CONVERSATIONS_DIR

        if not conversations_dir.exists():
            return []

        sessions = []
        for session_file in sorted(conversations_dir.glob("*.json"), reverse=True):
            try:
                with open(session_file, 'r') as f:
                    data = json.load(f)

                sessions.append({
                    'session_id': data.get('session_id'),
                    'started_at': data.get('started_at'),
                    'project_path': data.get('project_path'),
                    'message_count': len(data.get('messages', [])),
                    'topics': data.get('topics_discussed', [])[:3],
                })

                if len(sessions) >= limit:
                    break

            except Exception:
                continue

        return sessions

    def get_summary_for_llm(self) -> str:
        """Get a summary for LLM context."""
        lines = []

        if self.summary:
            lines.append(f"Previous context: {self.summary}")

        if self.topics_discussed:
            lines.append(f"Topics: {', '.join(self.topics_discussed[-5:])}")

        if self.decisions:
            recent_decisions = self.decisions[-3:]
            for d in recent_decisions:
                lines.append(f"Decision: {d.description} -> {d.choice}")

        return '\n'.join(lines) if lines else ""

    def to_dict(self) -> Dict[str, Any]:
        """Export to dictionary."""
        return {
            'session_id': self.session_id,
            'started_at': self.started_at,
            'project_path': self.project_path,
            'summary': self.summary,
            'topics_discussed': self.topics_discussed,
            'message_count': len(self.messages),
            'decision_count': len(self.decisions),
        }
