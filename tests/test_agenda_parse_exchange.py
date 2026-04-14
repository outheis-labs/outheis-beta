"""test_agenda_parse_exchange — unit tests for Cato's Exchange.md handling.

Cato reads Exchange.md on every review run. Items with '>' replies or
checked [x] boxes are treated as binding instructions and removed after
processing. Tests verify detection and context injection.
"""

import tempfile
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
        return agent


EXCHANGE_WITH_REPLY = """\
## Open item
Clarify open budget items
> postpone to next week
"""

EXCHANGE_WITH_CHECKBOX = """\
## Proposal
- [x] Tax office email done
"""

EXCHANGE_UNRESOLVED = """\
## Open item
Clarify open budget items
"""


# ---------------------------------------------------------------------------
# Exchange.md detection
# ---------------------------------------------------------------------------

class TestExchangeDetection:

    def _captured_query(self, agent, agenda_text: str, exchange_text: str):
        """Run run_review and capture the query passed to _process_with_tools."""
        captured = []

        def fake_process(query, **kwargs):
            captured.append(query)
            return "✓"

        with tempfile.TemporaryDirectory() as d:
            agenda_dir = Path(d) / "Agenda"
            agenda_dir.mkdir()
            (agenda_dir / "Agenda.md").write_text(
                f"2026-04-08\n{agenda_text}", encoding="utf-8"
            )
            (agenda_dir / "Exchange.md").write_text(exchange_text, encoding="utf-8")

            with patch("outheis.agents.agenda.get_agenda_dir", return_value=agenda_dir), \
                 patch("outheis.agents.agenda.date") as mock_date, \
                 patch.object(agent, "_load_hashes", return_value={}), \
                 patch.object(agent, "_compute_hash", return_value="changed"), \
                 patch.object(agent, "_process_with_tools", side_effect=fake_process), \
                 patch.object(agent, "_build_agenda_md", return_value=""), \
                 patch.object(agent, "_save_hashes"):
                mock_date.today.return_value.isoformat.return_value = "2026-04-08"
                agent.run_review(force=True)

        return captured[0] if captured else None

    def test_exchange_reply_triggers_review(self):
        """Exchange.md with '>' reply line triggers comment_trigger path."""
        agent = make_agent()
        # No file changes, but Exchange has '>' — must run
        calls = []

        def fake_process(query, **kwargs):
            calls.append(1)
            return "✓"

        with tempfile.TemporaryDirectory() as d:
            agenda_dir = Path(d) / "Agenda"
            agenda_dir.mkdir()
            (agenda_dir / "Agenda.md").write_text("2026-04-08\nclean", encoding="utf-8")
            (agenda_dir / "Exchange.md").write_text(EXCHANGE_WITH_REPLY, encoding="utf-8")

            with patch("outheis.agents.agenda.get_agenda_dir", return_value=agenda_dir), \
                 patch("outheis.agents.agenda.date") as mock_date, \
                 patch.object(agent, "_load_hashes", return_value={"Agenda.md": "same", "Exchange.md": "same"}), \
                 patch.object(agent, "_compute_hash", return_value="same"), \
                 patch.object(agent, "_process_with_tools", side_effect=fake_process), \
                 patch.object(agent, "_build_agenda_md", return_value=""), \
                 patch.object(agent, "_save_hashes"):
                mock_date.today.return_value.isoformat.return_value = "2026-04-08"
                agent.run_review(force=False)

        assert len(calls) == 1

    def test_unresolved_exchange_no_trigger_without_changes(self):
        """Exchange.md without '>' and no file changes — no review."""
        agent = make_agent()
        calls = []

        def fake_process(query, **kwargs):
            calls.append(1)
            return "✓"

        with tempfile.TemporaryDirectory() as d:
            agenda_dir = Path(d) / "Agenda"
            agenda_dir.mkdir()
            (agenda_dir / "Agenda.md").write_text("2026-04-08\nclean", encoding="utf-8")
            (agenda_dir / "Exchange.md").write_text(EXCHANGE_UNRESOLVED, encoding="utf-8")

            with patch("outheis.agents.agenda.get_agenda_dir", return_value=agenda_dir), \
                 patch("outheis.agents.agenda.date") as mock_date, \
                 patch.object(agent, "_load_hashes", return_value={"Agenda.md": "same", "Exchange.md": "same"}), \
                 patch.object(agent, "_compute_hash", return_value="same"), \
                 patch.object(agent, "_process_with_tools", side_effect=fake_process), \
                 patch.object(agent, "_build_agenda_md", return_value=""), \
                 patch.object(agent, "_save_hashes"):
                mock_date.today.return_value.isoformat.return_value = "2026-04-08"
                agent.run_review(force=False)

        assert len(calls) == 0

    def test_exchange_content_injected_into_query(self):
        """Exchange.md content appears in the LLM query."""
        agent = make_agent()
        query = self._captured_query(
            agent,
            agenda_text="some content",
            exchange_text=EXCHANGE_WITH_REPLY,
        )
        assert query is not None
        assert "Exchange.md" in query or "exchange" in query.lower() or "postpone" in query


# ---------------------------------------------------------------------------
# Exchange.md file tool mapping
# ---------------------------------------------------------------------------

class TestExchangeFileTool:

    def test_write_file_exchange_maps_correctly(self):
        """write_file with file='exchange' targets Exchange.md, not Agenda.md."""
        agent = make_agent()

        with tempfile.TemporaryDirectory() as d:
            agenda_dir = Path(d) / "Agenda"
            agenda_dir.mkdir()
            exchange_path = agenda_dir / "Exchange.md"

            with patch("outheis.agents.agenda.get_agenda_dir", return_value=agenda_dir):
                result = agent._write_file(exchange_path, "updated exchange content")

            assert "Exchange.md" in result or "✓" in result
            assert exchange_path.read_text() == "updated exchange content"

    def test_append_file_exchange(self):
        """append_file with file='exchange' appends to Exchange.md."""
        agent = make_agent()

        with tempfile.TemporaryDirectory() as d:
            agenda_dir = Path(d) / "Agenda"
            agenda_dir.mkdir()
            exchange_path = agenda_dir / "Exchange.md"
            exchange_path.write_text("existing content", encoding="utf-8")

            with patch("outheis.agents.agenda.get_agenda_dir", return_value=agenda_dir):
                result = agent._append_file(exchange_path, "\nnew item")

            content = exchange_path.read_text()
            assert "existing content" in content
            assert "new item" in content
