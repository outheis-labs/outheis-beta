"""test_pattern_migrate_integrate — unit tests for PatternAgent migration Phase A + C."""

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


def run_migration(agent, migration_dir: Path, store: MagicMock,
                  propose_return=None, mock_write_proposals=True):
    """Run run_migration with patched config/store. Returns the result string."""
    vault = migration_dir.parent

    kwargs = {}
    if mock_write_proposals:
        kwargs["write_proposals"] = patch.object(agent, "_write_proposals")

    with patch("outheis.core.config.load_config") as mock_cfg, \
         patch("outheis.core.memory.get_memory_store", return_value=store), \
         patch.object(agent, "_propose_from_sources",
                      return_value=propose_return or []):
        mock_cfg.return_value.human.primary_vault.return_value = vault
        if mock_write_proposals:
            with patch.object(agent, "_write_proposals"):
                return agent.run_migration()
        return agent.run_migration()


EXCHANGE_WITH_ACCEPT = """\
# Migration Exchange

---
*extracted: 2026-04-07 22:00*
User prefers direct responses [user]
- [x] Accept
- [ ] Reject
---
Agenda uses plain lines [rule:agenda]
- [ ] Accept
- [x] Reject
---
"""

EXCHANGE_BOTH_UNCHECKED = """\
---
*extracted: 2026-04-07 22:00*
Some pending fact [user]
- [ ] Accept
- [ ] Reject
---
"""

EXCHANGE_OLD_FORMAT = """\
- [x] User speaks German [user]
- [ ] Always use Markdown [feedback]
"""


# ---------------------------------------------------------------------------
# Phase A — accept/reject parsing
# ---------------------------------------------------------------------------

class TestPhaseA:

    def _setup(self, exchange_text: str):
        d = tempfile.mkdtemp()
        vault = Path(d) / "vault"
        migration_dir = vault / "Migration"
        migration_dir.mkdir(parents=True)
        exchange_path = migration_dir / "Exchange.md"
        exchange_path.write_text(exchange_text, encoding="utf-8")
        store = MagicMock()
        agent = make_agent()
        run_migration(agent, migration_dir, store)
        return store, exchange_path

    def test_accepted_item_written_to_memory(self):
        store, _ = self._setup(EXCHANGE_WITH_ACCEPT)
        calls = [args[0] for args, _ in store.add.call_args_list]
        assert any("User prefers direct responses" in c for c in calls)

    def test_rejected_item_not_written_to_memory(self):
        store, _ = self._setup(EXCHANGE_WITH_ACCEPT)
        calls = [args[0] for args, _ in store.add.call_args_list]
        assert not any("Agenda uses plain lines" in c for c in calls)

    def test_exchange_cleared_after_phase_a(self):
        _, exchange_path = self._setup(EXCHANGE_WITH_ACCEPT)
        assert exchange_path.read_text(encoding="utf-8") == ""

    def test_pending_items_not_written_to_memory(self):
        store, _ = self._setup(EXCHANGE_BOTH_UNCHECKED)
        store.add.assert_not_called()

    def test_old_format_accepted(self):
        store, _ = self._setup(EXCHANGE_OLD_FORMAT)
        calls = [args[0] for args, _ in store.add.call_args_list]
        assert any("User speaks German" in c for c in calls)

    def test_rule_type_appends_to_rules_file(self):
        exchange_text = (
            "---\n*ts*\nUse plain lines in agenda [rule:agenda]\n"
            "- [x] Accept\n- [ ] Reject\n---\n"
        )
        d = tempfile.mkdtemp()
        vault = Path(d) / "vault"
        migration_dir = vault / "Migration"
        migration_dir.mkdir(parents=True)
        (migration_dir / "Exchange.md").write_text(exchange_text, encoding="utf-8")

        store = MagicMock()
        appended_rules = []
        agent = make_agent()

        with patch("outheis.core.config.load_config") as mock_cfg, \
             patch("outheis.core.memory.get_memory_store", return_value=store), \
             patch.object(agent, "_propose_from_sources", return_value=[]), \
             patch.object(agent, "_write_proposals"), \
             patch.object(agent, "_append_user_rule",
                          side_effect=lambda a, r: appended_rules.append((a, r))):
            mock_cfg.return_value.human.primary_vault.return_value = vault
            agent.run_migration()

        assert any(a == "agenda" for a, _ in appended_rules)
        store.add.assert_not_called()


# ---------------------------------------------------------------------------
# Phase C — _write_proposals + source file x-prefixing
# ---------------------------------------------------------------------------

class TestPhaseC:

    def test_write_proposals_creates_exchange_with_header(self):
        agent = make_agent()
        with tempfile.TemporaryDirectory() as d:
            exchange_path = Path(d) / "Exchange.md"
            agent._write_proposals(exchange_path, [
                ("User prefers brevity", "user"),
                ("Agenda uses plain lines", "rule:agenda"),
            ])
            content = exchange_path.read_text()
        assert "# Migration Exchange" in content

    def test_write_proposals_each_item_has_checkboxes(self):
        agent = make_agent()
        with tempfile.TemporaryDirectory() as d:
            exchange_path = Path(d) / "Exchange.md"
            agent._write_proposals(exchange_path, [("some fact", "user")])
            content = exchange_path.read_text()
        assert "- [ ] Accept" in content
        assert "- [ ] Reject" in content

    def test_write_proposals_item_has_type_tag(self):
        agent = make_agent()
        with tempfile.TemporaryDirectory() as d:
            exchange_path = Path(d) / "Exchange.md"
            agent._write_proposals(exchange_path, [("a rule", "rule:agenda")])
            content = exchange_path.read_text()
        assert "[rule:agenda]" in content

    def test_write_proposals_appends_to_existing(self):
        agent = make_agent()
        with tempfile.TemporaryDirectory() as d:
            exchange_path = Path(d) / "Exchange.md"
            exchange_path.write_text("# Migration Exchange\n\nexisting content", encoding="utf-8")
            agent._write_proposals(exchange_path, [("new fact", "user")])
            content = exchange_path.read_text()
        assert "existing content" in content
        assert "new fact" in content

    def test_source_files_xprefixed_after_migration(self):
        d = tempfile.mkdtemp()
        vault = Path(d) / "vault"
        migration_dir = vault / "Migration"
        migration_dir.mkdir(parents=True)
        source = migration_dir / "notes.md"
        source.write_text("some notes to migrate", encoding="utf-8")
        (migration_dir / "Exchange.md").write_text("", encoding="utf-8")

        store = MagicMock()
        agent = make_agent()

        with patch("outheis.core.config.load_config") as mock_cfg, \
             patch("outheis.core.memory.get_memory_store", return_value=store), \
             patch.object(agent, "_propose_from_sources", return_value=[("fact", "user")]):
            mock_cfg.return_value.human.primary_vault.return_value = vault
            agent.run_migration()

        assert (migration_dir / "x-notes.md").exists()
        assert not (migration_dir / "notes.md").exists()

    def test_already_xprefixed_files_skipped(self):
        d = tempfile.mkdtemp()
        vault = Path(d) / "vault"
        migration_dir = vault / "Migration"
        migration_dir.mkdir(parents=True)
        (migration_dir / "x-old.md").write_text("already migrated", encoding="utf-8")
        (migration_dir / "Exchange.md").write_text("", encoding="utf-8")

        processed_sources = []

        def fake_propose(sources, store):
            processed_sources.extend(sources.keys())
            return []

        store = MagicMock()
        agent = make_agent()

        with patch("outheis.core.config.load_config") as mock_cfg, \
             patch("outheis.core.memory.get_memory_store", return_value=store), \
             patch.object(agent, "_propose_from_sources", side_effect=fake_propose):
            mock_cfg.return_value.human.primary_vault.return_value = vault
            agent.run_migration()

        assert "x-old.md" not in processed_sources
