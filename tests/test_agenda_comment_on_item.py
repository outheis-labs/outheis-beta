"""test_agenda_comment_on_item — unit tests for Cato's user-comment detection.

run_review() skips when no changes AND no comments.
It triggers when Agenda.md or Exchange.md contain lines starting with '>'.
"""

import tempfile
from pathlib import Path
from unittest.mock import patch

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


def run_review_with_files(agent, agenda_text: str = "", exchange_text: str = "",
                          shadow_text: str = "", today_iso: str = "2026-04-08"):
    """Run run_review(force=False) with given file contents. Returns True if LLM was called."""
    called = []

    def fake_process(query, **kwargs):
        called.append(query)
        return "✓"

    with tempfile.TemporaryDirectory() as d:
        agenda_dir = Path(d) / "Agenda"
        agenda_dir.mkdir()

        (agenda_dir / "Agenda.md").write_text(agenda_text, encoding="utf-8")
        if exchange_text:
            (agenda_dir / "Exchange.md").write_text(exchange_text, encoding="utf-8")
        if shadow_text:
            (agenda_dir / "Shadow.md").write_text(shadow_text, encoding="utf-8")

        # Must match what _compute_hash returns for all filenames in run_review.
        # run_review computes hashes for ["Agenda.md", "Exchange.md"] plus "agenda.json".
        stored = {"Agenda.md": "same", "Exchange.md": "same", "agenda.json": "same"}

        with patch("outheis.agents.agenda.get_agenda_dir", return_value=agenda_dir), \
             patch("outheis.agents.agenda.date") as mock_date, \
             patch.object(agent, "_load_hashes", return_value=stored), \
             patch.object(agent, "_compute_hash", return_value="same"), \
             patch.object(agent, "_today_needs_refill", return_value=False), \
             patch.object(agent, "_process_with_tools", side_effect=fake_process), \
             patch.object(agent, "_build_agenda_md", return_value=""), \
             patch.object(agent, "_save_hashes"):
            mock_date.today.return_value.isoformat.return_value = today_iso
            agent.run_review(force=False)

    return len(called) > 0


# ---------------------------------------------------------------------------
# Comment detection
# ---------------------------------------------------------------------------

class TestCommentDetection:

    def test_no_changes_no_comments_skips(self):
        """No file changes and no '>' lines — run_review skips LLM call."""
        agent = make_agent()
        called = run_review_with_files(
            agent,
            agenda_text="2026-04-08\n# Agenda\n\nSome content without comments.",
        )
        assert not called

    def test_agenda_comment_triggers_review(self):
        """A '>' line in Agenda.md triggers review even without file changes."""
        agent = make_agent()
        called = run_review_with_files(
            agent,
            agenda_text="# Agenda\n\n> Mark report task as done",
        )
        assert called

    def test_exchange_comment_triggers_review(self):
        """A '>' line in Exchange.md triggers review."""
        agent = make_agent()
        called = run_review_with_files(
            agent,
            agenda_text="# Agenda\n\nNo comments here.",
            exchange_text="> postpone team meeting to next week",
        )
        assert called

    def test_comment_must_start_line(self):
        """A '>' mid-line does not count as a comment trigger."""
        agent = make_agent()
        called = run_review_with_files(
            agent,
            agenda_text="2026-04-08\n# Agenda\n\nSee item > details here.",
        )
        assert not called

    def test_multiple_comment_lines_triggers_once(self):
        """Multiple '>' lines still result in a single review run."""
        agent = make_agent()
        calls = []

        def fake_process(query, **kwargs):
            calls.append(1)
            return "✓"

        with tempfile.TemporaryDirectory() as d:
            agenda_dir = Path(d) / "Agenda"
            agenda_dir.mkdir()
            (agenda_dir / "Agenda.md").write_text(
                "# Agenda\n\n> comment 1\n> comment 2", encoding="utf-8"
            )
            with patch("outheis.agents.agenda.get_agenda_dir", return_value=agenda_dir), \
                 patch("outheis.agents.agenda.date") as mock_date, \
                 patch.object(agent, "_load_hashes", return_value={}), \
                 patch.object(agent, "_compute_hash", return_value="x"), \
                 patch.object(agent, "_process_with_tools", side_effect=fake_process), \
                 patch.object(agent, "_build_agenda_md", return_value=""), \
                 patch.object(agent, "_save_hashes"):
                mock_date.today.return_value.isoformat.return_value = "2026-04-08"
                agent.run_review(force=False)

        assert len(calls) == 1


# ---------------------------------------------------------------------------
# Force flag
# ---------------------------------------------------------------------------

class TestForceFlag:

    def test_force_true_always_runs(self):
        """force=True runs regardless of changes or comments."""
        agent = make_agent()
        calls = []

        def fake_process(query, **kwargs):
            calls.append(1)
            return "✓"

        with tempfile.TemporaryDirectory() as d:
            agenda_dir = Path(d) / "Agenda"
            agenda_dir.mkdir()
            (agenda_dir / "Agenda.md").write_text(
                "2026-04-08\nNo comments.", encoding="utf-8"
            )
            with patch("outheis.agents.agenda.get_agenda_dir", return_value=agenda_dir), \
                 patch("outheis.agents.agenda.date") as mock_date, \
                 patch.object(agent, "_load_hashes", return_value={}), \
                 patch.object(agent, "_compute_hash", return_value="x"), \
                 patch.object(agent, "_process_with_tools", side_effect=fake_process), \
                 patch.object(agent, "_build_agenda_md", return_value=""), \
                 patch.object(agent, "_save_hashes"):
                mock_date.today.return_value.isoformat.return_value = "2026-04-08"
                agent.run_review(force=True)

        assert len(calls) == 1

    def test_stale_date_forces_review(self):
        """Agenda.md from a previous day is treated as force=True."""
        agent = make_agent()
        calls = []

        def fake_process(query, **kwargs):
            calls.append(1)
            return "✓"

        with tempfile.TemporaryDirectory() as d:
            agenda_dir = Path(d) / "Agenda"
            agenda_dir.mkdir()
            # Agenda has yesterday's date, not today's
            (agenda_dir / "Agenda.md").write_text(
                "2026-04-07\nNo comments.", encoding="utf-8"
            )
            with patch("outheis.agents.agenda.get_agenda_dir", return_value=agenda_dir), \
                 patch("outheis.agents.agenda.date") as mock_date, \
                 patch.object(agent, "_load_hashes", return_value={"Agenda.md": "same"}), \
                 patch.object(agent, "_compute_hash", return_value="same"), \
                 patch.object(agent, "_process_with_tools", side_effect=fake_process), \
                 patch.object(agent, "_build_agenda_md", return_value=""), \
                 patch.object(agent, "_save_hashes"):
                mock_date.today.return_value.isoformat.return_value = "2026-04-08"
                agent.run_review(force=False)

        assert len(calls) == 1
