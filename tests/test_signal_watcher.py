"""Tests for SignalTransport watcher — regression for watcher thread crash.

The watcher thread died silently when a broadcast message with non-empty text
was encountered because self.user_phone was never set in __init__ (AttributeError
on `if text and self.user_phone`).

Two regressions guarded here:
1. user_phone is set after __init__ (attribute exists)
2. _watch_responses survives a broadcast message in the queue
"""

import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from outheis.core.message import create_agent_message

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_transport(tmp_path: Path, human_phones=None):
    """Construct a real SignalTransport via __init__ with all I/O patched out."""
    from outheis.transport.signal import SignalTransport

    config = MagicMock()
    config.signal.bot_phone = "+49176000000"
    config.signal.bot_name = None
    config.signal.allowed = []
    config.human.phone = human_phones if human_phones is not None else ["+49123456789"]
    config.human.name = "Markus"

    with patch("outheis.transport.signal.SignalRPC"), \
         patch("outheis.core.config.get_human_dir", return_value=tmp_path), \
         patch("outheis.core.config.get_messages_path", return_value=tmp_path / "messages.jsonl"):
        t = SignalTransport(config)

    # Point queue to tmp dir and suppress RPC
    t.queue_path = tmp_path / "messages.jsonl"
    t.rpc = MagicMock()
    return t


def write_broadcast(queue_path: Path, text: str) -> None:
    """Append a broadcast message to the queue."""
    msg = create_agent_message(
        from_agent="relay",
        to="transport",
        type="response",
        payload={"text": text},
        conversation_id="test-conv",
        intent="broadcast",
    )
    from outheis.core.queue import append
    append(queue_path, msg)


# ---------------------------------------------------------------------------
# user_phone attribute
# ---------------------------------------------------------------------------

class TestUserPhoneAttribute:

    def test_user_phone_set_after_init(self, tmp_path):
        t = make_transport(tmp_path, human_phones=["+49123456789"])
        assert hasattr(t, "user_phone"), "user_phone must be set in __init__"

    def test_user_phone_matches_first_human_phone(self, tmp_path):
        t = make_transport(tmp_path, human_phones=["+49123456789"])
        assert t.user_phone == "+49123456789"

    def test_user_phone_is_first_when_multiple(self, tmp_path):
        t = make_transport(tmp_path, human_phones=["+49111111111", "+49222222222"])
        assert t.user_phone == "+49111111111"


# ---------------------------------------------------------------------------
# Watcher survives broadcast in queue
# ---------------------------------------------------------------------------

class TestWatcherBroadcastSurvival:
    """_watch_responses must not crash when broadcast messages are in the queue."""

    def _run_watcher_briefly(self, t: "SignalTransport", duration: float = 1.5) -> threading.Thread:  # noqa: F821
        """Start the watcher thread and let it run for `duration` seconds."""
        t._watching = True
        thread = threading.Thread(target=t._watch_responses, daemon=True)
        thread.start()
        time.sleep(duration)
        t._watching = False
        return thread

    def test_watcher_alive_after_broadcast_with_text(self, tmp_path):
        t = make_transport(tmp_path)
        write_broadcast(t.queue_path, "Fallback mode activated")

        thread = self._run_watcher_briefly(t)

        assert thread.is_alive(), (
            "_watch_responses crashed — likely AttributeError on self.user_phone"
        )

    def test_watcher_alive_after_multiple_broadcasts(self, tmp_path):
        t = make_transport(tmp_path)
        for i in range(4):
            write_broadcast(t.queue_path, f"Broadcast {i}")

        thread = self._run_watcher_briefly(t)

        assert thread.is_alive()

    def test_broadcast_sent_to_user_phone(self, tmp_path):
        t = make_transport(tmp_path, human_phones=["+49123456789"])
        write_broadcast(t.queue_path, "Cloud billing failed")

        self._run_watcher_briefly(t)

        # send_to_phone must have been called with the human's phone
        calls = t.rpc.send_to_phone.call_args_list
        assert any(c.args[0] == "+49123456789" for c in calls), (
            "broadcast must be sent to user_phone"
        )

    def test_watcher_alive_with_empty_queue(self, tmp_path):
        t = make_transport(tmp_path)
        # No messages — queue file doesn't exist yet

        thread = self._run_watcher_briefly(t)

        assert thread.is_alive()
