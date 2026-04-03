"""Tests for dispatcher routing."""

import pytest

from outheis.core.config import RoutingConfig
from outheis.core.message import create_user_message
from outheis.dispatcher.router import get_dispatch_target, route, score_keywords


class TestRouting:
    """Tests for message routing."""

    @pytest.fixture
    def config(self):
        """Create routing config for tests."""
        return RoutingConfig(
            threshold=0.3,
            data=["vault", "search", "find", "note"],
            agenda=["calendar", "appointment", "tomorrow"],
            action=["send", "email", "execute"],
        )

    def test_explicit_mention_relay(self, config):
        """@ou routes to relay."""
        msg = create_user_message(
            text="@ou help me",
            channel="cli",
            identity="test",
        )
        assert route(msg, config) == "relay"

    def test_explicit_mention_data(self, config):
        """@zeno routes to data."""
        msg = create_user_message(
            text="@zeno search for notes",
            channel="cli",
            identity="test",
        )
        assert route(msg, config) == "data"

    def test_explicit_mention_case_insensitive(self, config):
        """Mentions are case insensitive."""
        msg = create_user_message(
            text="@ZENO find something",
            channel="cli",
            identity="test",
        )
        assert route(msg, config) == "data"

    def test_keyword_routing_data(self, config):
        """Keywords route to appropriate agent."""
        msg = create_user_message(
            text="search my vault for notes",
            channel="cli",
            identity="test",
        )
        target = route(msg, config)
        assert target == "data"

    def test_keyword_routing_agenda(self, config):
        """Calendar keywords route to agenda."""
        msg = create_user_message(
            text="what's on my calendar tomorrow",
            channel="cli",
            identity="test",
        )
        target = route(msg, config)
        assert target == "agenda"

    def test_no_match_returns_none(self, config):
        """No match returns None (fallback to relay)."""
        msg = create_user_message(
            text="hello there",
            channel="cli",
            identity="test",
        )
        assert route(msg, config) is None

    def test_get_dispatch_target_fallback(self, config):
        """get_dispatch_target falls back to relay."""
        msg = create_user_message(
            text="random message",
            channel="cli",
            identity="test",
        )
        assert get_dispatch_target(msg, config) == "relay"


class TestScoreKeywords:
    """Tests for keyword scoring."""

    def test_no_keywords_returns_zero(self):
        """Empty keyword list returns 0."""
        assert score_keywords("hello world", []) == 0.0

    def test_no_matches_returns_zero(self):
        """No matches returns 0."""
        assert score_keywords("hello world", ["foo", "bar"]) == 0.0

    def test_partial_match(self):
        """Partial matches give proportional score."""
        score = score_keywords("search the vault", ["search", "find", "note", "vault"])
        assert score == 0.5  # 2 of 4 keywords

    def test_full_match(self):
        """All keywords matching gives 1.0."""
        score = score_keywords("search find note vault", ["search", "find", "note", "vault"])
        assert score == 1.0
