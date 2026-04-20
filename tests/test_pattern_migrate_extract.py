"""test_pattern_migrate_extract — unit tests for PatternAgent migration Phase B.

Phase B: single LLM call across source files → list of (content, type) proposals.
Tests _propose_from_sources (LLM output parsing) and _parse_json_migration (JSON formats).
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_agent():
    from outheis.agents.pattern import PatternAgent
    agent = PatternAgent.__new__(PatternAgent)
    agent.model_alias = "reasoning"
    agent.name = "pattern"
    return agent


def fake_llm_response(text: str):
    block = MagicMock()
    block.text = text
    response = MagicMock()
    response.content = [block]
    return response


def fake_store(existing=None):
    store = MagicMock()
    store.get_all.return_value = existing or {}
    return store


# ---------------------------------------------------------------------------
# _parse_json_migration
# ---------------------------------------------------------------------------

class TestParseJsonMigration:

    def _write_and_parse(self, data) -> list:
        agent = make_agent()
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w",
                                         encoding="utf-8", delete=False) as f:
            json.dump(data, f)
            path = Path(f.name)
        return agent._parse_json_migration(path)

    def test_entries_format(self):
        result = self._write_and_parse({
            "entries": [
                {"content": "User speaks German", "type": "user"},
                {"content": "Always use AGPL", "type": "rule:agenda"},
            ]
        })
        assert len(result) == 2
        assert result[0] == ("User speaks German", "user")
        assert result[1] == ("Always use AGPL", "rule:agenda")

    def test_list_of_dicts_format(self):
        result = self._write_and_parse([{"content": "Alice works at Acme Corp", "type": "user"}])
        assert result[0][0] == "Alice works at Acme Corp"

    def test_list_of_strings_format(self):
        result = self._write_and_parse(["fact one", "fact two"])
        assert len(result) == 2
        assert all(t == "user" for _, t in result)

    def test_key_value_dict_format(self):
        result = self._write_and_parse({"name": "Alice", "language": "de"})
        contents = [c for c, _ in result]
        assert any("name" in c and "Alice" in c for c in contents)

    def test_invalid_json_raises(self):
        agent = make_agent()
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w",
                                         encoding="utf-8", delete=False) as f:
            f.write("not valid json {{")
            path = Path(f.name)
        with pytest.raises(Exception):  # noqa: B017
            agent._parse_json_migration(path)

    def test_missing_type_defaults_to_user(self):
        result = self._write_and_parse([{"content": "some fact"}])
        assert result[0][1] == "user"


# ---------------------------------------------------------------------------
# _propose_from_sources — LLM output parsing
# ---------------------------------------------------------------------------

class TestProposeFromSources:

    VALID_JSON = json.dumps([
        {"content": "User prefers direct responses", "type": "user"},
        {"content": "Agenda items use plain lines", "type": "rule:agenda"},
    ])
    VALID_JSON_IN_FENCE = "```json\n" + VALID_JSON + "\n```"

    def test_parses_valid_json_response(self):
        agent = make_agent()
        with patch("outheis.core.llm.call_llm",
                   return_value=fake_llm_response(self.VALID_JSON)), \
             patch.object(agent, "_load_current_user_rules", return_value=""), \
             patch("outheis.core.config.get_skills_dir",
                   return_value=Path("/nonexistent")):
            result = agent._propose_from_sources({"notes.md": "content"}, fake_store())
        assert len(result) == 2
        assert result[0][1] == "user"

    def test_strips_markdown_fence(self):
        agent = make_agent()
        with patch("outheis.core.llm.call_llm",
                   return_value=fake_llm_response(self.VALID_JSON_IN_FENCE)), \
             patch.object(agent, "_load_current_user_rules", return_value=""), \
             patch("outheis.core.config.get_skills_dir",
                   return_value=Path("/nonexistent")):
            result = agent._propose_from_sources({"notes.md": "content"}, fake_store())
        assert len(result) == 2

    def test_llm_error_propagates(self):
        """LLM errors propagate — caller is responsible for handling."""
        agent = make_agent()
        with patch("outheis.core.llm.call_llm", side_effect=Exception("timeout")), \
             patch.object(agent, "_load_current_user_rules", return_value=""), \
             patch("outheis.core.config.get_skills_dir",
                   return_value=Path("/nonexistent")):
            with pytest.raises(Exception, match="timeout"):
                agent._propose_from_sources({"f.md": "c"}, fake_store())

    def test_empty_sources_calls_llm_with_empty_text(self):
        """Empty sources dict still calls LLM (no early-return guard)."""
        agent = make_agent()
        with patch("outheis.core.llm.call_llm",
                   return_value=fake_llm_response("[]")), \
             patch.object(agent, "_load_current_user_rules", return_value=""), \
             patch("outheis.core.config.get_skills_dir",
                   return_value=Path("/nonexistent")):
            result = agent._propose_from_sources({}, fake_store())
        assert result == []
