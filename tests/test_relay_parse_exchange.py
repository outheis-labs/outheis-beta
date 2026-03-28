"""test_relay_parse_exchange — unit tests for Relay routing and config/memory tools."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from outheis.core.message import create_agent_message


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_relay(tmp_path=None):
    from outheis.agents.relay import RelayAgent
    import tempfile
    agent = RelayAgent.__new__(RelayAgent)
    agent.model_alias = "fast"
    agent.name = "relay"
    agent._dispatcher = None
    agent.queue_path = (tmp_path or Path(tempfile.mkdtemp())) / "messages.jsonl"
    return agent


def make_message(text: str):
    return create_agent_message(
        from_agent="signal",
        to="relay",
        type="request",
        payload={"text": text},
        conversation_id="test-conv",
    )


# ---------------------------------------------------------------------------
# @mention delegation
# ---------------------------------------------------------------------------

class TestMentionDelegation:

    def _run(self, text: str):
        agent = make_relay()
        delegated = []

        def fake_agenda(t, msg):
            delegated.append("agenda")
            return "cato response"

        def fake_data(t, msg):
            delegated.append("data")
            return "zeno response"

        def fake_code(t, msg):
            delegated.append("code")
            return "alan response"

        with patch.object(agent, "_handle_with_agenda_agent", side_effect=fake_agenda), \
             patch.object(agent, "_handle_with_data_agent", side_effect=fake_data), \
             patch.object(agent, "_handle_with_code_agent", side_effect=fake_code):
            agent.handle(make_message(text))
        return delegated

    def test_cato_mention_delegates_to_agenda(self):
        assert "agenda" in self._run("@cato zeige agenda")

    def test_zeno_mention_delegates_to_data(self):
        assert "data" in self._run("@zeno scan vault")

    def test_alan_mention_delegates_to_code(self):
        assert "code" in self._run("@alan review this diff")


# ---------------------------------------------------------------------------
# get_config tool
# ---------------------------------------------------------------------------

class TestGetConfigTool:

    def test_get_config_vault_returns_string(self):
        agent = make_relay()
        with patch("outheis.core.config.load_config") as mock_cfg:
            mock_cfg.return_value.human.primary_vault.return_value = \
                Path("/Users/od/Documents/Obsidian-Sync")
            mock_cfg.return_value.human.all_vaults.return_value = [
                Path("/Users/od/Documents/Obsidian-Sync")
            ]
            result = agent._get_config_info("vault")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_get_config_unknown_aspect_returns_string(self):
        agent = make_relay()
        with patch("outheis.core.config.load_config") as mock_cfg:
            mock_cfg.return_value.human.primary_vault.return_value = Path("/tmp")
            mock_cfg.return_value.human.all_vaults.return_value = []
            result = agent._get_config_info("all")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Memory traits
# ---------------------------------------------------------------------------

class TestMemoryTraits:

    def test_get_memory_traits_returns_string(self):
        agent = make_relay()
        with patch("outheis.core.memory.get_memory_store") as mock_store:
            mock_store.return_value.get_all.return_value = []
            result = agent._get_memory_traits()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_write_memory_trait_calls_add_to_rules(self):
        agent = make_relay()
        added = []
        with patch.object(agent, "_add_to_rules", side_effect=lambda a, c: added.append((a, c))):
            result = agent._write_memory_trait("agenda", "Use plain lines")
        assert any("agenda" in a for a, _ in added)
        assert "✓" in result or "rule" in result.lower()
