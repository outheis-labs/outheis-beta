"""
Tests for Signal transport conversation persistence.

Tests the fix for multi-turn conversations via Signal.
"""

import json
import tempfile
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest


class TestConversationPersistence:
    """Test conversation_id persistence for multi-turn Signal conversations."""

    def test_first_message_creates_conversation(self):
        """First message from an identity creates a new conversation_id."""
        from outheis.transport.signal import SignalTransport

        # Create transport instance with mocked dependencies
        transport = self._create_mock_transport()

        identity = "+491111111111"
        conv_id = transport._get_or_create_conversation(identity)

        assert conv_id is not None
        assert conv_id.startswith("conv_")
        assert identity in transport._conversations
        assert transport._conversations[identity]["conversation_id"] == conv_id

    def test_second_message_reuses_conversation(self):
        """Second message within timeout reuses the same conversation_id."""
        from outheis.transport.signal import SignalTransport

        transport = self._create_mock_transport()
        identity = "+491111111111"

        # First message
        conv_id_1 = transport._get_or_create_conversation(identity)

        # Second message (within timeout)
        conv_id_2 = transport._get_or_create_conversation(identity)

        assert conv_id_1 == conv_id_2

    def test_timeout_creates_new_conversation(self):
        """After timeout, a new conversation is started."""
        from outheis.transport.signal import SignalTransport

        transport = self._create_mock_transport()
        identity = "+491111111111"

        # First message
        conv_id_1 = transport._get_or_create_conversation(identity)

        # Simulate timeout (35 minutes)
        transport._conversations[identity]["last_activity"] = (
            (datetime.now() - timedelta(minutes=35)).isoformat()
        )

        # New message after timeout
        conv_id_2 = transport._get_or_create_conversation(identity)

        assert conv_id_1 != conv_id_2

    def test_conversations_persisted_to_disk(self):
        """Conversation state is saved to signal.json."""
        from outheis.transport.signal import SignalTransport

        with tempfile.TemporaryDirectory() as tmpdir:
            transport = self._create_mock_transport(tmpdir)
            identity = "+491111111111"

            # Create conversation
            conv_id = transport._get_or_create_conversation(identity)

            # Verify file exists
            state_file = Path(tmpdir) / "signal.json"
            assert state_file.exists()

            # Verify content
            data = json.loads(state_file.read_text())
            assert "conversations" in data
            assert identity in data["conversations"]
            assert data["conversations"][identity]["conversation_id"] == conv_id

    def test_different_identities_separate_conversations(self):
        """Different identities have separate conversations."""
        from outheis.transport.signal import SignalTransport

        transport = self._create_mock_transport()

        conv_id_1 = transport._get_or_create_conversation("+491111111111")
        conv_id_2 = transport._get_or_create_conversation("+492222222222")

        assert conv_id_1 != conv_id_2
        assert "+491111111111" in transport._conversations
        assert "+492222222222" in transport._conversations

    def test_old_format_migration(self):
        """Old signal.json format is migrated correctly."""
        from outheis.transport.signal import SignalTransport

        with tempfile.TemporaryDirectory() as tmpdir:
            # Write old format
            old_format = {
                "user_uuid": "68102f77-fdd0-464f-8187-4b690bcde710",
                "user_phone": "+491111111111"
            }
            state_file = Path(tmpdir) / "signal.json"
            state_file.write_text(json.dumps(old_format))

            # Create transport with mocked path
            transport = self._create_mock_transport(tmpdir)

            # Manually trigger state load (since __init__ was bypassed)
            state = transport._load_state()
            transport.known_uuids = state.get("known_uuids", {})
            transport._conversations = state.get("conversations", {})

            # Verify migration
            assert "+491111111111" in transport.known_uuids
            assert transport.known_uuids["+491111111111"] == "68102f77-fdd0-464f-8187-4b690bcde710"

    def test_new_format_preserved(self):
        """New signal.json format is loaded correctly."""
        from outheis.transport.signal import SignalTransport

        with tempfile.TemporaryDirectory() as tmpdir:
            # Write new format
            new_format = {
                "known_uuids": {"+491234567890": "uuid-abc-123"},
                "conversations": {
                    "+491234567890": {
                        "conversation_id": "conv_existing",
                        "last_activity": datetime.now().isoformat()
                    }
                }
            }
            state_file = Path(tmpdir) / "signal.json"
            state_file.write_text(json.dumps(new_format))

            # Create transport
            transport = self._create_mock_transport(tmpdir)

            # Manually trigger state load
            state = transport._load_state()
            transport.known_uuids = state.get("known_uuids", {})
            transport._conversations = state.get("conversations", {})

            # Verify loaded
            assert "+491234567890" in transport.known_uuids
            assert "+491234567890" in transport._conversations
            assert transport._conversations["+491234567890"]["conversation_id"] == "conv_existing"

    def test_handle_message_uses_persistent_conversation(self):
        """_handle_message passes persistent conversation_id to message."""
        from outheis.transport.signal import SignalTransport
        from outheis.core.message import create_user_message
        from outheis.core.queue import append

        with tempfile.TemporaryDirectory() as tmpdir:
            transport = self._create_mock_transport(tmpdir)
            transport.queue_path = Path(tmpdir) / "messages.jsonl"
            transport._lock = threading.Lock()  # Need a real lock for _handle_message

            # Mock the message creation to capture conversation_id
            created_ids = []
            original_create = create_user_message

            def mock_create_user_message(**kwargs):
                created_ids.append(kwargs.get("conversation_id"))
                return original_create(**kwargs)

            with patch("outheis.transport.signal.create_user_message", mock_create_user_message):
                # Simulate first message
                msg1 = MagicMock()
                msg1.text = "test"
                msg1.sender_phone = "+491111111111"
                msg1.sender_uuid = "test-uuid"
                msg1.sender_name = "Test User"
                msg1.is_voice = False

                # Set up allowed_phones for _is_allowed
                transport.allowed_phones["+491111111111"] = "Test User"

                transport._handle_message(msg1)
                conv_id_1 = created_ids[-1]

                # Simulate second message (within timeout)
                transport._handle_message(msg1)
                conv_id_2 = created_ids[-1]

                # Same conversation_id
                assert conv_id_1 == conv_id_2
                assert conv_id_1 is not None

    # Helper methods

    def _create_mock_transport(self, tmpdir: Optional[str] = None) -> "SignalTransport":
        """Create a SignalTransport with mocked dependencies."""
        from outheis.transport.signal import SignalTransport
        from outheis.core.config import load_config

        config = load_config()

        # Create instance without full initialization
        transport = SignalTransport.__new__(SignalTransport)
        transport.config = config
        transport.bot_phone = config.signal.bot_phone if config.signal else "+49123456789"
        transport.allowed_phones = {}
        transport.known_uuids = {}
        transport._conversations = {}
        transport._conversation_timeout_minutes = 30
        transport.rpc = MagicMock()
        transport.queue_path = Path(tmpdir) / "messages.jsonl" if tmpdir else Path("/tmp/test_messages.jsonl")
        transport.pending = {}
        transport._lock = None
        transport.whisper_model = None
        transport.user_phone = "+491111111111"

        # Override state path for testing
        if tmpdir:
            transport._get_signal_state_path = lambda: Path(tmpdir) / "signal.json"

        return transport


if __name__ == "__main__":
    pytest.main([__file__, "-v"])