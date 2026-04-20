"""test_agenda_propose_memory — unit tests for cato's annotation → memory proposal path.

When cato processes a user annotation (> line) and detects a correction,
clarification, or behavioral instruction, it calls propose_memory. This writes
a proposal to Agenda/Exchange.md in the Phase-A format so rumi can adopt it
on the next memory_migrate run.
"""

import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_agent():
    with patch("outheis.agents.agenda.load_config"), \
         patch("outheis.agents.agenda.get_human_dir"):
        from outheis.agents.agenda import AgendaAgent
        agent = AgendaAgent.__new__(AgendaAgent)
        agent.model_alias = "capable"
        agent.name = "agenda"
        agent._agenda_snapshot = ""
        agent._dispatcher = None
        return agent


def fake_config(vault_path: Path):
    cfg = MagicMock()
    cfg.human.primary_vault.return_value = vault_path
    return cfg


# ---------------------------------------------------------------------------
# _tool_propose_memory — output format
# ---------------------------------------------------------------------------

class TestProposeMemoryFormat:

    def test_creates_migration_exchange_if_missing(self):
        agent = make_agent()
        with tempfile.TemporaryDirectory() as d:
            vault = Path(d)
            with patch("outheis.agents.agenda.load_config", return_value=fake_config(vault)):
                result = agent._tool_propose_memory("Quarterly report sent to accountant.", "user")

            exchange = vault / "Agenda" / "Exchange.md"
            assert exchange.exists()
            assert "Quarterly report sent" in exchange.read_text()
            assert "✓" in result

    def test_format_has_separator_and_checkboxes(self):
        agent = make_agent()
        with tempfile.TemporaryDirectory() as d:
            vault = Path(d)
            with patch("outheis.agents.agenda.load_config", return_value=fake_config(vault)):
                agent._tool_propose_memory("User prefers appointments on Fridays.", "user")

            text = (vault / "Agenda" / "Exchange.md").read_text()
            assert "---" in text
            assert "- [ ] Accept" in text
            assert "- [ ] Reject" in text
            assert "[user]" in text

    def test_type_tag_written_correctly(self):
        agent = make_agent()
        with tempfile.TemporaryDirectory() as d:
            vault = Path(d)
            with patch("outheis.agents.agenda.load_config", return_value=fake_config(vault)):
                agent._tool_propose_memory("Work items always scheduled first.", "rule:agenda")

            text = (vault / "Agenda" / "Exchange.md").read_text()
            assert "[rule:agenda]" in text

    def test_appends_to_existing_exchange(self):
        agent = make_agent()
        with tempfile.TemporaryDirectory() as d:
            vault = Path(d)
            migration = vault / "Agenda"
            migration.mkdir()
            (migration / "Exchange.md").write_text(
                "# Migration Exchange\n\nexisting content\n", encoding="utf-8"
            )
            with patch("outheis.agents.agenda.load_config", return_value=fake_config(vault)):
                agent._tool_propose_memory("New fact.", "user")

            text = (migration / "Exchange.md").read_text()
            assert "existing content" in text
            assert "New fact." in text

    def test_empty_content_returns_error(self):
        agent = make_agent()
        with tempfile.TemporaryDirectory() as d:
            vault = Path(d)
            with patch("outheis.agents.agenda.load_config", return_value=fake_config(vault)):
                result = agent._tool_propose_memory("", "user")
        assert "error" in result.lower()

    def test_timestamp_written_in_from_annotation_line(self):
        agent = make_agent()
        with tempfile.TemporaryDirectory() as d:
            vault = Path(d)
            with patch("outheis.agents.agenda.load_config", return_value=fake_config(vault)):
                agent._tool_propose_memory("Fact.", "user")

            text = (vault / "Agenda" / "Exchange.md").read_text()
            assert "from annotation:" in text


# ---------------------------------------------------------------------------
# propose_memory reachable via _execute_tool
# ---------------------------------------------------------------------------

class TestProposeMemoryViaExecuteTool:

    def test_tool_dispatched_correctly(self):
        agent = make_agent()
        with tempfile.TemporaryDirectory() as d:
            vault = Path(d)
            with patch("outheis.agents.agenda.load_config", return_value=fake_config(vault)):
                result = agent._execute_tool("propose_memory", {
                    "content": "Meetings preferred on Tuesdays.",
                    "type": "rule:agenda",
                })

            assert "✓" in result
            text = (vault / "Agenda" / "Exchange.md").read_text()
            assert "Meetings preferred" in text

    def test_missing_content_returns_error(self):
        agent = make_agent()
        with tempfile.TemporaryDirectory() as d:
            vault = Path(d)
            with patch("outheis.agents.agenda.load_config", return_value=fake_config(vault)):
                result = agent._execute_tool("propose_memory", {"type": "user"})
        assert "error" in result.lower()

    def test_multiple_proposals_all_appended(self):
        agent = make_agent()
        with tempfile.TemporaryDirectory() as d:
            vault = Path(d)
            with patch("outheis.agents.agenda.load_config", return_value=fake_config(vault)):
                agent._execute_tool("propose_memory", {"content": "Fact A.", "type": "user"})
                agent._execute_tool("propose_memory", {"content": "Fact B.", "type": "user"})

            text = (vault / "Agenda" / "Exchange.md").read_text()
            assert "Fact A." in text
            assert "Fact B." in text
