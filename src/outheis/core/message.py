"""
Message schema and utilities.

Messages are the fundamental unit of communication in outheis.
All agents and components communicate via messages in the queue.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

from outheis.core.snowflake import generate_str as _snowflake_str

# =============================================================================
# TYPES
# =============================================================================

AgentId = Literal["relay", "data", "agenda", "action", "pattern"]
MessageType = Literal["request", "response", "event"]
Channel = Literal["signal", "cli", "api"]


# =============================================================================
# MESSAGE DATACLASS
# =============================================================================

@dataclass
class UserOrigin:
    """Origin information when message is from a user."""
    channel: Channel
    identity: str  # Phone number, username, API key
    name: str | None = None


@dataclass
class AgentOrigin:
    """Origin information when message is from an agent."""
    agent: AgentId


@dataclass
class Message:
    """
    A message in the outheis system.

    Messages are immutable once created. They are appended to the queue
    and never modified.
    """
    id: str
    conversation_id: str
    to: str  # AgentId | "dispatcher" | "transport"
    type: MessageType
    payload: dict

    # Origin: either agent or user, not both
    from_agent: AgentId | None = None
    from_user: UserOrigin | None = None

    # Optional fields
    intent: str | None = None
    reply_to: str | None = None

    # Metadata (not part of schema, added at write time)
    timestamp: float | None = None

    def __post_init__(self):
        if self.from_agent is None and self.from_user is None:
            raise ValueError("Message must have either from_agent or from_user")
        if self.from_agent is not None and self.from_user is not None:
            raise ValueError("Message cannot have both from_agent and from_user")

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        d = {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "to": self.to,
            "type": self.type,
            "payload": self.payload,
        }

        if self.from_agent:
            d["from"] = {"agent": self.from_agent}
        elif self.from_user:
            d["from"] = {
                "user": {
                    "channel": self.from_user.channel,
                    "identity": self.from_user.identity,
                }
            }
            if self.from_user.name:
                d["from"]["user"]["name"] = self.from_user.name

        if self.intent:
            d["intent"] = self.intent
        if self.reply_to:
            d["reply_to"] = self.reply_to
        if self.timestamp:
            d["timestamp"] = self.timestamp

        return d

    @classmethod
    def from_dict(cls, d: dict) -> Message:
        """Create from dictionary (after parsing JSON)."""
        from_agent = None
        from_user = None

        if "from" in d:
            if "agent" in d["from"]:
                from_agent = d["from"]["agent"]
            elif "user" in d["from"]:
                u = d["from"]["user"]
                from_user = UserOrigin(
                    channel=u["channel"],
                    identity=u["identity"],
                    name=u.get("name"),
                )

        return cls(
            id=d["id"],
            conversation_id=d["conversation_id"],
            to=d["to"],
            type=d["type"],
            payload=d["payload"],
            from_agent=from_agent,
            from_user=from_user,
            intent=d.get("intent"),
            reply_to=d.get("reply_to"),
            timestamp=d.get("timestamp"),
        )


# =============================================================================
# FACTORY FUNCTIONS
# =============================================================================

def generate_id() -> str:
    """Generate a unique, time-sortable message ID (Snowflake)."""
    return _snowflake_str()


def generate_conversation_id() -> str:
    """Generate a new conversation ID."""
    return f"conv_{uuid4().hex[:12]}"


def create_user_message(
    text: str,
    channel: Channel,
    identity: str,
    name: str | None = None,
    conversation_id: str | None = None,
) -> Message:
    """Create a message from a user."""
    return Message(
        id=generate_id(),
        conversation_id=conversation_id or generate_conversation_id(),
        to="dispatcher",
        type="request",
        payload={"text": text},
        from_user=UserOrigin(channel=channel, identity=identity, name=name),
        timestamp=time.time(),
    )


def create_agent_message(
    from_agent: AgentId,
    to: str,
    type: MessageType,
    payload: dict,
    conversation_id: str,
    intent: str | None = None,
    reply_to: str | None = None,
) -> Message:
    """Create a message from an agent."""
    return Message(
        id=generate_id(),
        conversation_id=conversation_id,
        to=to,
        type=type,
        payload=payload,
        from_agent=from_agent,
        intent=intent,
        reply_to=reply_to,
        timestamp=time.time(),
    )
