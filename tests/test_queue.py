"""Tests for message queue."""


import pytest

from outheis.core.message import create_user_message
from outheis.core.queue import (
    append,
    ensure_queue,
    message_count,
    read_all,
    read_last_n,
)


class TestQueue:
    """Tests for queue operations."""

    @pytest.fixture
    def queue_path(self, tmp_path):
        """Create a temporary queue file."""
        path = tmp_path / "messages.jsonl"
        ensure_queue(path)
        return path

    def test_append_and_read(self, queue_path):
        """append and read_all work together."""
        msg = create_user_message(
            text="hello",
            channel="cli",
            identity="test",
        )
        append(queue_path, msg)

        messages = read_all(queue_path)
        assert len(messages) == 1
        assert messages[0].id == msg.id

    def test_read_empty_queue(self, queue_path):
        """read_all returns empty list for empty queue."""
        messages = read_all(queue_path)
        assert messages == []

    def test_read_nonexistent_queue(self, tmp_path):
        """read_all returns empty list for nonexistent file."""
        path = tmp_path / "nonexistent.jsonl"
        messages = read_all(path)
        assert messages == []

    def test_message_count(self, queue_path):
        """message_count returns correct count."""
        assert message_count(queue_path) == 0

        for i in range(5):
            msg = create_user_message(
                text=f"message {i}",
                channel="cli",
                identity="test",
            )
            append(queue_path, msg)

        assert message_count(queue_path) == 5

    def test_read_last_n(self, queue_path):
        """read_last_n returns last N messages."""
        for i in range(10):
            msg = create_user_message(
                text=f"message {i}",
                channel="cli",
                identity="test",
            )
            append(queue_path, msg)

        last_3 = read_last_n(queue_path, 3)
        assert len(last_3) == 3
        assert last_3[0].payload["text"] == "message 7"
        assert last_3[2].payload["text"] == "message 9"
