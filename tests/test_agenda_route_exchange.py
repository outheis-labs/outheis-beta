"""test_agenda_route_exchange — Exchange.md routing across vault directories.

Exchange.md exists in three locations with different owners:
  Agenda/Exchange.md    → Cato (AgendaAgent)
  Codebase/Exchange.md  → Alan (CodeAgent)
  Migration/Exchange.md → Rumi (PatternAgent)

Tests verify the file tool mapping and that write_file targets the correct path.
"""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_agenda_agent():
    with patch("outheis.agents.agenda.load_config"), \
         patch("outheis.agents.agenda.get_human_dir"):
        from outheis.agents.agenda import AgendaAgent
        agent = AgendaAgent.__new__(AgendaAgent)
        agent.model_alias = "capable"
        agent.name = "agenda"
        agent._agenda_snapshot = ""
        return agent


def make_code_agent():
    with patch("outheis.agents.code.load_config"), \
         patch("outheis.agents.code.get_human_dir"):
        from outheis.agents.code import CodeAgent
        agent = CodeAgent.__new__(CodeAgent)
        agent.model_alias = "capable"
        agent.name = "code"
        return agent


# ---------------------------------------------------------------------------
# Cato — Agenda/Exchange.md
# ---------------------------------------------------------------------------

class TestAgendaExchangeRoute:

    def test_execute_tool_write_exchange_targets_agenda_dir(self):
        """Cato's write_file('exchange') writes to Agenda/Exchange.md."""
        agent = make_agenda_agent()
        with tempfile.TemporaryDirectory() as d:
            agenda_dir = Path(d) / "Agenda"
            agenda_dir.mkdir()
            with patch("outheis.agents.agenda.get_agenda_dir", return_value=agenda_dir):
                result = agent._execute_tool("write_file", {
                    "file": "exchange",
                    "content": "test exchange entry"
                })
            exchange_path = agenda_dir / "Exchange.md"
            assert exchange_path.exists()
            assert "test exchange entry" in exchange_path.read_text()

    def test_execute_tool_write_agenda_does_not_touch_exchange(self):
        """Cato's write_file('agenda') does not overwrite Exchange.md."""
        agent = make_agenda_agent()
        with tempfile.TemporaryDirectory() as d:
            agenda_dir = Path(d) / "Agenda"
            agenda_dir.mkdir()
            exchange_path = agenda_dir / "Exchange.md"
            exchange_path.write_text("exchange content", encoding="utf-8")
            with patch("outheis.agents.agenda.get_agenda_dir", return_value=agenda_dir):
                agent._execute_tool("write_file", {
                    "file": "agenda",
                    "content": "new agenda"
                })
            assert exchange_path.read_text() == "exchange content"

    def test_invalid_file_key_returns_error(self):
        """Unknown file key returns an error string, not an exception."""
        agent = make_agenda_agent()
        with tempfile.TemporaryDirectory() as d:
            agenda_dir = Path(d) / "Agenda"
            agenda_dir.mkdir()
            with patch("outheis.agents.agenda.get_agenda_dir", return_value=agenda_dir):
                result = agent._execute_tool("write_file", {
                    "file": "nonexistent",
                    "content": "test"
                })
        assert "invalid" in result.lower() or "error" in result.lower() or "choose" in result.lower()


# ---------------------------------------------------------------------------
# Alan — Codebase/Exchange.md
# ---------------------------------------------------------------------------

class TestCodebaseExchangeRoute:

    def _make_codebase(self):
        """Return a temp dir with a fake vault/Codebase/ structure."""
        import tempfile
        d = tempfile.mkdtemp()
        vault = Path(d) / "vault"
        codebase = vault / "Codebase"
        codebase.mkdir(parents=True)
        return d, vault, codebase

    def test_write_codebase_creates_file_in_codebase_dir(self):
        """_tool_write_codebase writes to Codebase/, not vault root."""
        agent = make_code_agent()
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            vault = Path(d) / "vault"
            codebase = vault / "Codebase"
            codebase.mkdir(parents=True)
            with patch.object(agent, "_get_codebase_dir", return_value=codebase), \
                 patch("outheis.agents.code.load_config"):
                result = agent._tool_write_codebase("proposal.md", "fix suggestion")
            assert (codebase / "proposal.md").exists()
            assert "Written: vault/Codebase/proposal.md" in result

    def test_write_codebase_rejects_path_traversal(self):
        """Path traversal outside Codebase/ is rejected."""
        agent = make_code_agent()
        with tempfile.TemporaryDirectory() as d:
            vault = Path(d) / "vault"
            codebase = vault / "Codebase"
            codebase.mkdir(parents=True)
            with patch.object(agent, "_get_codebase_dir", return_value=codebase):
                result = agent._tool_write_codebase("../../../etc/passwd", "evil")
        assert "rejected" in result.lower()

    def test_append_codebase_rejects_path_traversal(self):
        """append_codebase also rejects paths outside Codebase/."""
        agent = make_code_agent()
        with tempfile.TemporaryDirectory() as d:
            vault = Path(d) / "vault"
            codebase = vault / "Codebase"
            codebase.mkdir(parents=True)
            with patch.object(agent, "_get_codebase_dir", return_value=codebase):
                result = agent._tool_append_codebase("../../secret.md", "content")
        assert "rejected" in result.lower()

    def test_write_exchange_md_no_timestamp_prepend(self):
        """Writing Exchange.md directly does not get a timestamp prepended."""
        agent = make_code_agent()
        with tempfile.TemporaryDirectory() as d:
            vault = Path(d) / "vault"
            codebase = vault / "Codebase"
            codebase.mkdir(parents=True)
            with patch.object(agent, "_get_codebase_dir", return_value=codebase), \
                 patch("outheis.agents.code.load_config"):
                agent._tool_write_codebase("Exchange.md", "## Entry\npending")
            content = (codebase / "Exchange.md").read_text()
        # Timestamp is NOT prepended for Exchange.md (only for proposals)
        assert content.startswith("## Entry")
