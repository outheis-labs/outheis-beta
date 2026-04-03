"""Integration tests requiring running system and API key."""

import os
import time

import pytest

# Skip all tests if no API key
pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set"
)


class TestRelayAgent:
    """Integration tests for relay agent with real LLM."""

    def test_simple_response(self):
        """Relay agent responds to simple query."""
        from outheis.agents.relay import create_relay_agent
        from outheis.core.message import create_user_message

        agent = create_relay_agent()
        msg = create_user_message(
            text="What is 2 + 2? Reply with just the number.",
            channel="cli",
            identity="test",
        )

        response = agent.handle(msg)

        assert response is not None
        assert "4" in response.payload.get("text", "")

    def test_acknowledges_uncertainty(self):
        """Relay agent acknowledges when it doesn't know."""
        from outheis.agents.relay import create_relay_agent
        from outheis.core.message import create_user_message

        agent = create_relay_agent()
        msg = create_user_message(
            text="What is the exact current price of Bitcoin right now?",
            channel="cli",
            identity="test",
        )

        response = agent.handle(msg)

        assert response is not None
        # Should indicate uncertainty about real-time data
        text = response.payload.get("text", "").lower()
        assert any(word in text for word in ["don't", "cannot", "can't", "unable", "know"])


class TestDaemon:
    """Integration tests for dispatcher daemon."""

    @pytest.fixture
    def temp_outheis_dir(self, tmp_path, monkeypatch):
        """Create temporary outheis directory."""
        outheis_dir = tmp_path / ".outheis"
        outheis_dir.mkdir()
        (outheis_dir / "human").mkdir()

        # Patch home directory
        monkeypatch.setenv("HOME", str(tmp_path))

        return outheis_dir

    def test_daemon_start_stop(self, temp_outheis_dir):
        """Daemon starts and stops cleanly."""
        import threading

        # Start in background thread (foreground=True but in thread)
        def run_daemon():
            from outheis.dispatcher.daemon import Dispatcher
            d = Dispatcher()
            d.running = True
            # Run briefly then stop
            time.sleep(1)
            d.running = False

        thread = threading.Thread(target=run_daemon)
        thread.start()
        thread.join(timeout=3)

        assert not thread.is_alive()

    def test_message_processing(self, temp_outheis_dir):
        """Daemon processes messages correctly."""
        from outheis.core.message import create_user_message
        from outheis.core.queue import append, read_all
        from outheis.dispatcher.daemon import Dispatcher

        # Create dispatcher
        dispatcher = Dispatcher()

        # Send a message
        msg = create_user_message(
            text="Hello",
            channel="cli",
            identity="test",
        )
        append(dispatcher.queue_path, msg)

        # Process it
        count = dispatcher.process_pending()

        assert count == 1

        # Check for response
        messages = read_all(dispatcher.queue_path)
        responses = [m for m in messages if m.to == "transport"]

        assert len(responses) >= 1


class TestEndToEnd:
    """Full end-to-end tests."""

    def test_cli_send_receive(self, tmp_path, monkeypatch):
        """CLI transport sends and receives."""
        # Set up temp directory
        outheis_dir = tmp_path / ".outheis"
        outheis_dir.mkdir()
        (outheis_dir / "human").mkdir()
        monkeypatch.setenv("HOME", str(tmp_path))

        from outheis.core.queue import read_all
        from outheis.dispatcher.daemon import Dispatcher
        from outheis.transport.cli import CLITransport

        # Create transport and dispatcher
        transport = CLITransport()
        dispatcher = Dispatcher()

        # Send message
        msg = transport.send("Say 'test passed' and nothing else.")

        # Process with dispatcher
        dispatcher.process_pending()

        # Check response exists
        messages = read_all(dispatcher.queue_path)
        responses = [m for m in messages if m.reply_to == msg.id]

        assert len(responses) >= 1
        assert "test" in responses[0].payload.get("text", "").lower()
