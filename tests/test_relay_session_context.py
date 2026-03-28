"""Tests for relay session context — delegated response handling.

Documents the intended behaviour of the source-tagged response approach
described in vault/Codebase/Claude.md.

When relay.handle() delegates to cato/zeno/alan it should write a
`source` field into the response payload. When _call_llm_with_tools
builds context from previous messages it should replace delegated
responses with a one-line marker instead of the full text.

These tests are written against the *intended* interface. They will
fail until the feature is implemented and serve as a specification.
"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from outheis.core.message import create_agent_message, Message


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_relay(tmp_path: Path):
    from outheis.agents.relay import RelayAgent
    agent = RelayAgent.__new__(RelayAgent)
    agent.model_alias = "fast"
    agent.name = "relay"
    agent._dispatcher = None
    agent.queue_path = tmp_path / "messages.jsonl"
    return agent


def make_transport_msg(text: str, source: str | None = None) -> Message:
    """Simulate a relay→transport response with optional source tag."""
    payload = {"text": text}
    if source is not None:
        payload["source"] = source
    return create_agent_message(
        from_agent="relay",
        to="transport",
        type="response",
        payload=payload,
        conversation_id="test-conv",
    )


# ---------------------------------------------------------------------------
# source field written by relay.handle()
# ---------------------------------------------------------------------------

class TestResponseSourceTag:
    """relay.handle() must tag responses with their source agent."""

    def _run(self, tmp_path, text: str, fake_handler, handler_name: str) -> Message:
        agent = make_relay(tmp_path)
        written = []
        original_respond = agent.__class__.respond

        def capture_respond(self, **kwargs):
            msg = original_respond(self, **kwargs)
            written.append(msg)
            return msg

        with patch.object(agent.__class__, "respond", capture_respond), \
             patch.object(agent, handler_name, return_value="agent response"), \
             patch.object(agent, "_schedule_interim", return_value=MagicMock(cancel=lambda: None)):
            from outheis.core.message import create_user_message
            msg = create_user_message(channel="signal", identity="+1", text=text)
            agent.handle(msg)

        return written[-1] if written else None

    def test_cato_delegation_tagged(self, tmp_path):
        msg = self._run(tmp_path, "@cato zeige agenda", lambda t, m: "agenda text", "_handle_with_agenda_agent")
        assert msg is not None
        assert msg.payload.get("source") == "cato"

    def test_zeno_delegation_tagged(self, tmp_path):
        msg = self._run(tmp_path, "@zeno scan vault", lambda t, m: "data text", "_handle_with_data_agent")
        assert msg is not None
        assert msg.payload.get("source") == "zeno"

    def test_alan_delegation_tagged(self, tmp_path):
        msg = self._run(tmp_path, "@alan review code", lambda t, m: "code text", "_handle_with_code_agent")
        assert msg is not None
        assert msg.payload.get("source") == "alan"

    def test_relay_own_response_not_tagged(self, tmp_path):
        agent = make_relay(tmp_path)
        written = []
        original_respond = agent.__class__.respond

        def capture_respond(self, **kwargs):
            msg = original_respond(self, **kwargs)
            written.append(msg)
            return msg

        with patch.object(agent.__class__, "respond", capture_respond), \
             patch.object(agent, "_generate_response", return_value="direct relay answer"), \
             patch.object(agent, "_schedule_interim", return_value=MagicMock(cancel=lambda: None)):
            from outheis.core.message import create_user_message
            msg = create_user_message(channel="signal", identity="+1", text="what time is it")
            agent.handle(msg)

        assert written[-1].payload.get("source") in (None, "relay")


# ---------------------------------------------------------------------------
# context summarisation in _call_llm_with_tools
# ---------------------------------------------------------------------------

class TestContextSummarisation:
    """Delegated responses must appear as one-line markers in LLM context."""

    def _build_context(self, agent, msgs: list[Message], query: str) -> list[dict]:
        """Capture the messages list passed to call_llm."""
        captured = []

        def fake_call_llm(**kwargs):
            captured.extend(kwargs.get("messages", []))
            return '{"tool": null}'  # minimal valid response

        with patch("outheis.core.llm.call_llm", fake_call_llm):
            try:
                agent._call_llm_with_tools(query, msgs, "test-conv")
            except Exception:
                pass  # we only care about what was passed to call_llm

        return captured

    def test_cato_response_summarised(self, tmp_path):
        agent = make_relay(tmp_path)
        long_agenda = "## 📅 Today\nMeeting at 10\nLunch at 12\n" + "item\n" * 50
        msgs = [make_transport_msg(long_agenda, source="cato")]

        context = self._build_context(agent, msgs, "wie viele items?")

        assistant_msgs = [m["content"] for m in context if m["role"] == "assistant"]
        assert any("[cato response:" in c for c in assistant_msgs), \
            "cato response must be summarised to a marker in LLM context"
        assert not any(long_agenda[:100] in c for c in assistant_msgs), \
            "full cato response text must not appear in LLM context"

    def test_zeno_response_summarised(self, tmp_path):
        agent = make_relay(tmp_path)
        long_data = "## Results\n" + "entry\n" * 60
        msgs = [make_transport_msg(long_data, source="zeno")]

        context = self._build_context(agent, msgs, "was hast du gefunden?")

        assistant_msgs = [m["content"] for m in context if m["role"] == "assistant"]
        assert any("[zeno response:" in c for c in assistant_msgs)

    def test_relay_response_kept_verbatim(self, tmp_path):
        agent = make_relay(tmp_path)
        short_reply = "Gerne, ich erledige das."
        msgs = [make_transport_msg(short_reply, source="relay")]

        context = self._build_context(agent, msgs, "danke")

        assistant_msgs = [m["content"] for m in context if m["role"] == "assistant"]
        assert any(short_reply in c for c in assistant_msgs), \
            "relay's own conversational responses must be kept verbatim"

    def test_untagged_response_kept_verbatim(self, tmp_path):
        """Backwards compat: messages without source field are kept as-is."""
        agent = make_relay(tmp_path)
        reply = "Alles klar."
        msgs = [make_transport_msg(reply, source=None)]

        context = self._build_context(agent, msgs, "ok")

        assistant_msgs = [m["content"] for m in context if m["role"] == "assistant"]
        assert any(reply in c for c in assistant_msgs)
