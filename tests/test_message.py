"""Tests for message handling."""

import pytest

from outheis.core.message import (
    Message,
    create_agent_message,
    create_user_message,
)


class TestMessage:
    """Tests for Message dataclass."""

    def test_create_user_message(self):
        """create_user_message creates valid message."""
        msg = create_user_message(
            text="hello",
            channel="cli",
            identity="test_user",
        )
        assert msg.id is not None
        assert msg.conversation_id is not None
        assert msg.to == "dispatcher"
        assert msg.type == "request"
        assert msg.payload["text"] == "hello"
        assert msg.from_user is not None
        assert msg.from_user.channel == "cli"

    def test_create_agent_message(self):
        """create_agent_message creates valid message."""
        msg = create_agent_message(
            from_agent="relay",
            to="transport",
            type="response",
            payload={"text": "hi"},
            conversation_id="conv_001",
        )
        assert msg.from_agent == "relay"
        assert msg.to == "transport"
        assert msg.type == "response"

    def test_message_requires_origin(self):
        """Message must have either from_agent or from_user."""
        with pytest.raises(ValueError):
            Message(
                id="test",
                conversation_id="conv",
                to="dispatcher",
                type="request",
                payload={},
            )

    def test_message_to_dict(self):
        """Message.to_dict produces valid dictionary."""
        msg = create_user_message(
            text="test",
            channel="cli",
            identity="user",
        )
        d = msg.to_dict()
        assert "id" in d
        assert "from" in d
        assert "user" in d["from"]
        assert d["from"]["user"]["channel"] == "cli"

    def test_message_from_dict(self):
        """Message.from_dict reconstructs message."""
        original = create_user_message(
            text="test",
            channel="cli",
            identity="user",
        )
        d = original.to_dict()
        reconstructed = Message.from_dict(d)
        assert reconstructed.id == original.id
        assert reconstructed.from_user.channel == "cli"
