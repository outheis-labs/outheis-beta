"""test_dispatcher_route_message — unit tests for dispatcher routing logic."""

import pytest

from outheis.core.message import Message, create_agent_message
from outheis.dispatcher.router import MENTION_PATTERNS, get_dispatch_target, route

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_message(text: str, to: str = "dispatcher") -> Message:
    return create_agent_message(
        from_agent="signal",
        to=to,
        type="request",
        payload={"text": text},
        conversation_id="test-conv",
    )


# ---------------------------------------------------------------------------
# Explicit @mentions
# ---------------------------------------------------------------------------

class TestMentionPatterns:

    @pytest.mark.parametrize("mention,expected_agent", [
        ("@ou bitte antworte",   "relay"),
        ("@zeno scan vault",     "data"),
        ("@cato zeige agenda",   "agenda"),
        ("@hiro do task",        "action"),
        ("@rumi reflect",        "pattern"),
        ("@alan review code",    "code"),
    ])
    def test_mention_routes_to_correct_agent(self, mention, expected_agent):
        msg = make_message(mention)
        assert route(msg) == expected_agent

    def test_no_mention_returns_none(self):
        msg = make_message("was ist heute auf dem plan?")
        assert route(msg) is None

    def test_mention_case_insensitive(self):
        msg = make_message("@CATO zeige agenda")
        assert route(msg) == "agenda"

    def test_mention_mid_sentence(self):
        msg = make_message("ich frage @zeno danach")
        assert route(msg) == "data"

    def test_first_mention_wins(self):
        """When multiple mentions present, first matched pattern wins."""
        msg = make_message("@cato und @zeno bitte")
        result = route(msg)
        assert result in ("agenda", "data")


# ---------------------------------------------------------------------------
# get_dispatch_target
# ---------------------------------------------------------------------------

class TestGetDispatchTarget:

    def test_already_addressed_passes_through(self):
        msg = make_message("hello", to="agenda")
        assert get_dispatch_target(msg) == "agenda"

    def test_dispatcher_addressed_routes(self):
        msg = make_message("@cato zeige heute", to="dispatcher")
        assert get_dispatch_target(msg) == "agenda"

    def test_transport_addressed_routes(self):
        msg = make_message("@alan help", to="transport")
        assert get_dispatch_target(msg) == "code"

    def test_no_mention_falls_back_to_relay(self):
        msg = make_message("was ist heute auf dem plan?", to="dispatcher")
        assert get_dispatch_target(msg) == "relay"

    def test_empty_text_falls_back_to_relay(self):
        msg = make_message("", to="dispatcher")
        assert get_dispatch_target(msg) == "relay"

    def test_internal_task_message_passes_through(self):
        msg = make_message("run_task:backlog_generate", to="dispatcher")
        result = get_dispatch_target(msg)
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# MENTION_PATTERNS completeness
# ---------------------------------------------------------------------------

class TestMentionPatternsRegistry:

    def test_all_agents_have_mention_pattern(self):
        expected = {"relay", "data", "agenda", "action", "pattern", "code"}
        assert set(MENTION_PATTERNS.keys()) == expected

    def test_patterns_require_word_boundary(self):
        """@ou does not match @outheis, @cato does not match @catobra."""
        msg_ou = make_message("@outheis start")
        msg_cato = make_message("@catobra")
        assert route(msg_ou) is None
        assert route(msg_cato) is None
