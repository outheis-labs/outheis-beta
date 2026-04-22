"""test_agenda_generate_backlog — unit tests for AgendaAgent.generate_backlog.

Tests Shadow.md reading, item counting, header format, and output validation.
No LLM calls — generate_backlog is mocked at the call_llm boundary.
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SHADOW_TWO_ITEMS = """\
# Shadow — Vault Chronological Index
*Last updated: 2026-04-08 03:33*

<!-- BEGIN: project.md -->
## project.md
#date-2026-03-20 #action-required #facet-project
Send quarterly report to accountant

#action-required #facet-startup
Complete business registration
<!-- END: project.md -->
"""

SHADOW_EMPTY = """\
# Shadow — Vault Chronological Index
*Last updated: 2026-04-08 03:33*
"""


def make_agent():
    with patch("outheis.agents.agenda.load_config"), \
         patch("outheis.agents.agenda.get_human_dir"):
        from outheis.agents.agenda import AgendaAgent
        agent = AgendaAgent.__new__(AgendaAgent)
        agent.model_alias = "capable"
        agent.name = "agenda"
        return agent


def fake_llm_response(text: str):
    block = MagicMock()
    block.text = text
    response = MagicMock()
    response.content = [block]
    return response


def run_generate(agent, shadow_content: str, llm_output: str):
    """Run generate_backlog with a temp Shadow.md and mocked LLM."""
    with tempfile.TemporaryDirectory() as d:
        agenda_dir = Path(d) / "Agenda"
        agenda_dir.mkdir()
        (agenda_dir / "Shadow.md").write_text(shadow_content, encoding="utf-8")

        with patch("outheis.agents.agenda.get_agenda_dir", return_value=agenda_dir), \
             patch("outheis.core.memory.get_memory_context", return_value=""), \
             patch("outheis.core.llm.call_llm", return_value=fake_llm_response(llm_output)):
            result = agent.generate_backlog()
            backlog_path = agenda_dir / "Backlog.md"
            backlog_content = backlog_path.read_text() if backlog_path.exists() else None

    return result, backlog_content


# ---------------------------------------------------------------------------
# Item counting
# ---------------------------------------------------------------------------

class TestItemCount:

    def test_counts_two_items(self):
        """Item count in header matches actual Shadow.md tag-line pairs."""
        agent = make_agent()
        llm_out = "# Backlog\n*placeholder*\n\n## All\n\n#action-required\nItem\n"
        result, content = run_generate(agent, SHADOW_TWO_ITEMS, llm_out)
        assert "2 items" in content

    def test_zero_items_returns_early(self):
        """Empty Shadow.md returns early without calling LLM."""
        agent = make_agent()
        with tempfile.TemporaryDirectory() as d:
            agenda_dir = Path(d) / "Agenda"
            agenda_dir.mkdir()
            (agenda_dir / "Shadow.md").write_text(SHADOW_EMPTY, encoding="utf-8")

            with patch("outheis.agents.agenda.get_agenda_dir", return_value=agenda_dir), \
                 patch("outheis.core.memory.get_memory_context", return_value=""), \
                 patch("outheis.core.llm.call_llm") as mock_llm:
                result = agent.generate_backlog()

        mock_llm.assert_not_called()
        assert "no open items" in result.lower()


# ---------------------------------------------------------------------------
# Output validation
# ---------------------------------------------------------------------------

class TestOutputValidation:

    def test_writes_backlog_file(self):
        """generate_backlog writes Backlog.md to the agenda directory."""
        agent = make_agent()
        llm_out = "# Backlog\n*placeholder*\n\n## Urgent\n\n#action-required\nDo it\n"
        result, content = run_generate(agent, SHADOW_TWO_ITEMS, llm_out)
        assert content is not None
        assert "# Backlog" in content

    def test_unexpected_output_not_written(self):
        """LLM output not starting with '# Backlog' is rejected."""
        agent = make_agent()
        llm_out = "Here is your backlog:\n\n## Urgent\n..."
        result, content = run_generate(agent, SHADOW_TWO_ITEMS, llm_out)
        assert "unexpected output" in result.lower()
        assert content is None

    def test_header_contains_timestamp(self):
        """Written Backlog.md second line contains a timestamp."""
        import re
        agent = make_agent()
        llm_out = "# Backlog\n*2026-04-08 08:55 — 2 items — derived from Shadow.md, safe to delete*\n\n## All\n\n#action-required\nTask\n"
        result, content = run_generate(agent, SHADOW_TWO_ITEMS, llm_out)
        assert re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", content)

    def test_missing_shadow_returns_error(self):
        """Missing Shadow.md returns descriptive error string."""
        agent = make_agent()
        with tempfile.TemporaryDirectory() as d:
            agenda_dir = Path(d) / "Agenda"
            agenda_dir.mkdir()
            with patch("outheis.agents.agenda.get_agenda_dir", return_value=agenda_dir):
                result = agent.generate_backlog()
        assert "not found" in result.lower()

    def test_missing_agenda_dir_returns_error(self):
        """None agenda dir returns descriptive error string."""
        agent = make_agent()
        with patch("outheis.agents.agenda.get_agenda_dir", return_value=None):
            result = agent.generate_backlog()
        assert "no agenda" in result.lower()
