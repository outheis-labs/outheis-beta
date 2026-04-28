"""test_agenda_run_review_tokens — ensure run_review uses sufficient max_tokens.

Regression test for: deepseek-v4-flash hitting 2048 token limit and returning
"No response." because the complex agenda review task needs more output space.

The fix: run_review now passes max_tokens=8192 to _process_with_tools.
"""

import inspect
from unittest.mock import patch, MagicMock

from outheis.agents.agenda import AgendaAgent


def make_agent():
    """Create a minimal AgendaAgent for testing."""
    with patch("outheis.agents.agenda.load_config"), \
         patch("outheis.agents.agenda.get_human_dir"):
        agent = AgendaAgent.__new__(AgendaAgent)
        agent.model_alias = "capable"
        agent.name = "agenda"
        agent._passthrough_content = None
        agent._agenda_snapshot = ""
        agent._dispatcher = None
        agent._write_happened = False
        return agent


class TestRunReviewMaxTokens:
    """run_review must use sufficient max_tokens for complex LLM responses."""

    def test_run_review_passes_8192_tokens(self):
        """Verify run_review passes max_tokens=8192 to _process_with_tools."""
        agent = make_agent()

        # Track all arguments passed to _process_with_tools
        captured_args = {}

        def fake_process(query, tools_override=None, max_tokens=None, **kwargs):
            captured_args["query"] = query
            captured_args["tools_override"] = tools_override
            captured_args["max_tokens"] = max_tokens
            return "✓ Agenda.md updated"

        with patch.object(agent, "_process_with_tools", side_effect=fake_process), \
             patch.object(agent, "_load_hashes", return_value={}), \
             patch.object(agent, "_compute_hash", return_value="abc123"), \
             patch.object(agent, "_build_agenda_md", return_value="## scaffold"), \
             patch.object(agent, "_save_hashes"):
            agent.run_review(force=True)

        assert captured_args.get("max_tokens") == 8192, \
            f"max_tokens should be 8192, got {captured_args.get('max_tokens')}"

    def test_default_process_with_tools_still_2048(self):
        """Default _process_with_tools still uses 2048 for backward compatibility."""
        # Verify the default parameter value hasn't changed
        sig = inspect.signature(AgendaAgent._process_with_tools)
        max_tokens_default = sig.parameters["max_tokens"].default
        assert max_tokens_default == 2048, \
            f"Default max_tokens should remain 2048, got {max_tokens_default}"

    def test_run_review_skips_get_daily_tool(self):
        """run_review must exclude get_daily from tools to prevent passthrough."""
        agent = make_agent()

        captured_tools = None

        def fake_process(query, tools_override=None, max_tokens=None, **kwargs):
            nonlocal captured_tools
            if tools_override is not None:
                captured_tools = tools_override
            return "✓ done"

        with patch.object(agent, "_process_with_tools", side_effect=fake_process), \
             patch.object(agent, "_load_hashes", return_value={}), \
             patch.object(agent, "_compute_hash", return_value="abc123"), \
             patch.object(agent, "_build_agenda_md", return_value="## scaffold"), \
             patch.object(agent, "_save_hashes"):
            agent.run_review(force=True)

        assert captured_tools is not None, "tools_override was not passed"
        tool_names = [t.get("name") for t in captured_tools]
        assert "get_daily" not in tool_names, \
            "get_daily should be excluded from run_review tools to prevent passthrough"
        assert "write_file" in tool_names, \
            "write_file must be available for run_review to update Agenda.md"