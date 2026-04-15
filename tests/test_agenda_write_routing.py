"""test_agenda_write_routing — ensure handle_direct() routes write queries through LLM.

The fast-path in handle_direct() returns Agenda.md verbatim for read-only queries.
Write queries (schreib, add, trag ein, …) must NOT hit this fast-path — they must
go through _process_with_tools so the LLM can call write_file.

Regression test for: "schreib" not in AGENDA_MODIFY_STEMS → wrongly returned
verbatim agenda instead of writing.
"""

from unittest.mock import MagicMock, patch

from tests.fixtures.agenda_write_inputs import (
    DE_HINZUFUEG,
    DE_NOTIER,
    DE_RELAY_FORMAT,
    DE_SCHREIB,
    DE_TRAG_EIN,
    DE_ZEIG_AGENDA,
)


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
        agent._passthrough_content = None
        agent._agenda_snapshot = ""
        return agent


AGENDA_CONTENT = "## ⛅ Today\n\n*test agenda*\n"


# ---------------------------------------------------------------------------
# Tests: write queries must reach _process_with_tools
# ---------------------------------------------------------------------------

class TestHandleDirectWriteRouting:
    """Write-intent queries must bypass the fast-path and call _process_with_tools."""

    def _assert_routes_to_process(self, agent, query: str):
        """Assert _process_with_tools is called (not the verbatim fast-path)."""
        called = []

        def fake_process(q, **kwargs):
            called.append(q)
            return "✓ written"

        with patch.object(agent, "_process_with_tools", side_effect=fake_process), \
             patch.object(agent, "_tool_get_daily", return_value=AGENDA_CONTENT) as mock_daily:
            result = agent.handle_direct(query)

        assert called, f"_process_with_tools not called for: {repr(query)}"
        assert mock_daily.call_count == 0, (
            f"_tool_get_daily called for write query: {repr(query)}"
        )
        assert result == "✓ written"

    def test_de_schreib(self):
        """'schreib' (German) must route to _process_with_tools."""
        agent = make_agent()
        self._assert_routes_to_process(agent, DE_SCHREIB)

    def test_de_trag_ein(self):
        agent = make_agent()
        self._assert_routes_to_process(agent, DE_TRAG_EIN)

    def test_de_notier(self):
        agent = make_agent()
        self._assert_routes_to_process(agent, DE_NOTIER)

    def test_de_hinzufug(self):
        agent = make_agent()
        self._assert_routes_to_process(agent, DE_HINZUFUEG)

    def test_en_add(self):
        agent = make_agent()
        self._assert_routes_to_process(agent, "add to today: call dentist")

    def test_en_write(self):
        agent = make_agent()
        self._assert_routes_to_process(agent, "write to agenda: team meeting at 3pm")

    def test_relay_dispatched_format(self):
        """Format relay sends after fast-route: 'Add to Agenda.md in section X: Y'."""
        agent = make_agent()
        self._assert_routes_to_process(agent, DE_RELAY_FORMAT)

    def test_relay_dispatched_format_no_section(self):
        agent = make_agent()
        self._assert_routes_to_process(
            agent,
            "Add to Agenda.md: Reminder Willi Stemmer"
        )


# ---------------------------------------------------------------------------
# Tests: read queries still hit fast-path
# ---------------------------------------------------------------------------

class TestHandleDirectReadFastPath:
    """Pure read queries must still return verbatim content without LLM."""

    def _assert_fast_path(self, agent, query: str):
        called = []

        def fake_process(q, **kwargs):
            called.append(q)
            return "should not reach here"

        with patch.object(agent, "_process_with_tools", side_effect=fake_process), \
             patch.object(agent, "_tool_get_daily", return_value=AGENDA_CONTENT):
            result = agent.handle_direct(query)

        assert not called, f"_process_with_tools called for read query: {repr(query)}"
        assert result == AGENDA_CONTENT

    def test_de_zeig_agenda(self):
        agent = make_agent()
        self._assert_fast_path(agent, DE_ZEIG_AGENDA)

    def test_en_show_agenda(self):
        agent = make_agent()
        self._assert_fast_path(agent, "show me the agenda")

    def test_en_whats_on_today(self):
        agent = make_agent()
        self._assert_fast_path(agent, "what's on today?")
