"""test_data_extract_chronoitems — unit tests for DataAgent._extract_chronological_entries.

Tests the LLM prompt + output parsing without hitting the API.
The method receives raw file content and returns two-line tag-format entries.
"""

import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_agent():
    """DataAgent with mocked config — no real vault or API needed."""
    with patch("outheis.agents.data.load_config"), \
         patch("outheis.agents.data.get_human_dir"):
        from outheis.agents.data import DataAgent
        agent = DataAgent.__new__(DataAgent)
        agent.model_alias = "fast"
        agent.name = "data"
        agent.get_system_prompt = lambda: "system"
        return agent


def fake_llm_response(text: str):
    """Build a minimal response object matching what call_llm returns."""
    block = MagicMock()
    block.text = text
    response = MagicMock()
    response.content = [block]
    return response


# ---------------------------------------------------------------------------
# Output format
# ---------------------------------------------------------------------------

class TestOutputFormat:

    def test_returns_two_line_entries(self):
        """Valid entries are returned as tag-line + text-line pairs."""
        agent = make_agent()
        raw = (
            "#date-2026-03-20 #action-required\n"
            "Send quarterly report to accountant\n\n"
            "#action-required #unit-project\n"
            "Follow-up with project lead on deliverables"
        )
        with patch("outheis.core.llm.call_llm", return_value=fake_llm_response(raw)):
            result = agent._extract_chronological_entries("test.md", "content")
        lines = [l for l in result.splitlines() if l.strip()]
        assert lines[0].startswith("#date-")
        assert not lines[1].startswith("#")
        assert lines[2].startswith("#action-required")
        assert not lines[3].startswith("#")

    def test_none_response_returns_empty_string(self):
        """NONE response means no actionable items — returns empty string."""
        agent = make_agent()
        with patch("outheis.core.llm.call_llm", return_value=fake_llm_response("NONE")):
            result = agent._extract_chronological_entries("empty.md", "no content here")
        assert result == ""

    def test_none_with_trailing_text_still_empty(self):
        """Model sometimes appends reasoning after NONE — still treated as empty."""
        agent = make_agent()
        with patch("outheis.core.llm.call_llm", return_value=fake_llm_response("NONE\n\nNo entries found.")):
            result = agent._extract_chronological_entries("empty.md", "content")
        assert result == ""


# ---------------------------------------------------------------------------
# Tag format correctness
# ---------------------------------------------------------------------------

class TestTagFormat:

    def test_date_tag_format(self):
        """Date tags must follow #date-YYYY-MM-DD."""
        agent = make_agent()
        raw = "#date-2026-05-15 #action-required\nPickup at workshop"
        with patch("outheis.core.llm.call_llm", return_value=fake_llm_response(raw)):
            result = agent._extract_chronological_entries("f.md", "c")
        import re
        assert re.search(r"#date-\d{4}-\d{2}-\d{2}", result)

    def test_action_required_without_date(self):
        """Undated items use #action-required as primary tag."""
        agent = make_agent()
        raw = "#action-required\nCall client about funding"
        with patch("outheis.core.llm.call_llm", return_value=fake_llm_response(raw)):
            result = agent._extract_chronological_entries("f.md", "c")
        assert "#action-required" in result

    def test_recurring_tag_format(self):
        """Recurring items use #recurring-FREQ tag."""
        agent = make_agent()
        raw = "#recurring-weekly\nWeekly team standup"
        with patch("outheis.core.llm.call_llm", return_value=fake_llm_response(raw)):
            result = agent._extract_chronological_entries("f.md", "c")
        assert "#recurring-weekly" in result


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:

    def test_llm_error_returns_empty(self):
        """LLM errors are caught and logged — method returns empty string, not raises."""
        agent = make_agent()
        with patch("outheis.core.llm.call_llm", side_effect=Exception("timeout")):
            result = agent._extract_chronological_entries("f.md", "c")
        assert result == ""

    def test_empty_file_content(self):
        """Empty file content — model should return NONE."""
        agent = make_agent()
        with patch("outheis.core.llm.call_llm", return_value=fake_llm_response("NONE")):
            result = agent._extract_chronological_entries("empty.md", "")
        assert result == ""
