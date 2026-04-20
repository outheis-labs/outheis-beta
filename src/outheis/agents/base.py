"""
Base agent class.

All agents inherit from this base class.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from outheis.core.config import get_messages_path
from outheis.core.message import AgentId, Message, create_agent_message
from outheis.core.queue import append, read_conversation

# =============================================================================
# BASE AGENT
# =============================================================================

@dataclass
class BaseAgent(ABC):
    """
    Base class for all agents.

    Provides common functionality for message handling,
    queue access, and response creation.
    """

    name: AgentId
    model_alias: str = "capable"  # Model alias from config ("fast", "capable", etc.)
    queue_path: Path = field(default_factory=get_messages_path)

    @abstractmethod
    def handle(self, msg: Message) -> Message | None:
        """
        Handle an incoming message.

        Returns a response message, or None if no response needed.
        """
        pass

    @abstractmethod
    def get_system_prompt(self) -> str:
        """Get the system prompt for this agent."""
        pass

    def respond(
        self,
        to: str,
        payload: dict,
        conversation_id: str,
        reply_to: str | None = None,
        intent: str | None = None,
    ) -> Message:
        """Create and queue a response message."""
        msg = create_agent_message(
            from_agent=self.name,
            to=to,
            type="response",
            payload=payload,
            conversation_id=conversation_id,
            reply_to=reply_to,
            intent=intent,
        )
        append(self.queue_path, msg)
        return msg

    def request(
        self,
        to: str,
        payload: dict,
        conversation_id: str,
        intent: str | None = None,
    ) -> Message:
        """Create and queue a request to another agent."""
        msg = create_agent_message(
            from_agent=self.name,
            to=to,
            type="request",
            payload=payload,
            conversation_id=conversation_id,
            intent=intent,
        )
        append(self.queue_path, msg)
        return msg

    def get_conversation_context(
        self,
        conversation_id: str,
        max_messages: int = 10,
    ) -> list[Message]:
        """Get recent messages in a conversation for context."""
        messages = read_conversation(self.queue_path, conversation_id)
        return messages[-max_messages:]

    def get_session_context(self, max_messages: int = 50) -> list[Message]:
        """
        Get recent messages across all conversations for session continuity.

        This provides context from previous sessions, allowing the user to
        continue conversations after restart.
        """
        from outheis.core.queue import read_last_n

        all_recent = read_last_n(self.queue_path, max_messages * 2)

        # Filter to user messages and relay responses
        relevant = [
            msg for msg in all_recent
            if msg.from_user or (msg.from_agent == "relay" and msg.to == "transport")
        ]

        return relevant[-max_messages:]

    def remember(
        self,
        content: str,
        memory_type: str = "context",
        confidence: float = 0.9,
    ) -> None:
        """
        Store information in memory during interaction.

        Called by agents when they recognize something worth remembering:
        - User expresses an intent or gives an order
        - User shares personal information
        - User states a preference about how to work

        The agent decides what's relevant. No rigid rules.

        Args:
            content: What to remember (concise, one fact)
            memory_type: "user" (personal), "feedback" (preferences), "context" (current focus)
            confidence: 0-1, how certain (default 0.9 for agent-inferred)
        """
        from outheis.core.memory import get_memory_store

        store = get_memory_store()
        store.add(
            content,
            memory_type,  # type: ignore
            confidence=confidence,
            is_explicit=False,  # Agent-inferred, not user-marked
        )

    def log_session_note(
        self,
        problem: str,
        solution: str,
        session_id: str,
        context: dict | None = None,
    ) -> None:
        """
        Log a session note for Pattern agent to review.

        Used when user helps solve a problem.
        """
        import time

        from outheis.core.config import get_session_notes_path
        from outheis.core.schema import write_session_note

        note = {
            "id": f"note_{int(time.time())}",
            "session_id": session_id,
            "agent": self.name,
            "problem": problem,
            "solution": solution,
            "context": context or {},
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "reviewed": False,
        }

        path = get_session_notes_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "a", encoding="utf-8") as f:
            f.write(write_session_note(note) + "\n")
