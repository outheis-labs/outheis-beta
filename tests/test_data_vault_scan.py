"""test_data_vault_scan — unit tests for DataAgent agenda.json integration.

Tests scan_chronological_entries file-selection logic and agenda.json writes
without hitting the filesystem or API.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_agent():
    with patch("outheis.agents.data.load_config"), \
         patch("outheis.agents.data.get_human_dir"):
        from outheis.agents.data import DataAgent
        agent = DataAgent.__new__(DataAgent)
        agent.model_alias = "fast"
        agent.name = "data"
        agent.get_system_prompt = lambda: "system"
        return agent


# ---------------------------------------------------------------------------
# scan_chronological_entries — file selection logic (unchanged behaviour)
# ---------------------------------------------------------------------------

class TestScanFileSelection:

    def test_skips_agenda_directory(self):
        agent = make_agent()
        with tempfile.TemporaryDirectory() as d:
            vault = Path(d)
            (vault / "Agenda").mkdir()
            (vault / "Agenda" / "Shadow.md").write_text("should be skipped")
            (vault / "note.md").write_text("real note")

            files = agent._get_vault_files(vault)
        assert not any("Agenda" in k for k in files)
        assert "note.md" in files

    def test_skips_hidden_directories(self):
        agent = make_agent()
        with tempfile.TemporaryDirectory() as d:
            vault = Path(d)
            (vault / ".obsidian").mkdir()
            (vault / ".obsidian" / "config.md").write_text("hidden")
            (vault / "visible.md").write_text("real")

            files = agent._get_vault_files(vault)
        assert not any(".obsidian" in k for k in files)
        assert "visible.md" in files

    def test_only_processes_changed_files(self):
        """scan_chronological_entries skips files whose hash is cached."""
        agent = make_agent()
        with tempfile.TemporaryDirectory() as d:
            vault = Path(d)
            (vault / "Agenda").mkdir()
            cache_path = Path(d) / "cache" / "shadow" / "file_state.json"
            cache_path.parent.mkdir(parents=True)

            note = vault / "note.md"
            note.write_text("content")

            import hashlib
            note_hash = hashlib.md5(note.read_bytes()).hexdigest()
            cache_path.write_text(json.dumps({"note.md": note_hash}))

            processed = []

            def fake_extract(filename, content):
                processed.append(filename)
                return ""

            agenda_path = Path(d) / "webui" / "pages" / "agenda.json"
            with patch.object(agent, "_extract_chronological_entries", side_effect=fake_extract), \
                 patch("outheis.agents.data.load_config") as mock_cfg, \
                 patch("outheis.agents.data.get_human_dir", return_value=Path(d)), \
                 patch("outheis.core.agenda_store._agenda_json_path", return_value=agenda_path):
                mock_cfg.return_value.human.primary_vault.return_value = vault
                mock_cfg.return_value.agents.get.return_value = None
                count = agent.scan_chronological_entries()

        assert count == 0
        assert "note.md" not in processed

    def test_processes_new_file(self):
        """A file not in cache is extracted."""
        agent = make_agent()
        with tempfile.TemporaryDirectory() as d:
            vault = Path(d)
            (vault / "Agenda").mkdir()
            cache_path = Path(d) / "cache" / "shadow" / "file_state.json"
            cache_path.parent.mkdir(parents=True)
            cache_path.write_text("{}")

            (vault / "new.md").write_text("Meeting with ministry on 2026-03-20")

            processed = []

            def fake_extract(filename, content):
                processed.append(filename)
                return ""

            agenda_path = Path(d) / "webui" / "pages" / "agenda.json"
            with patch.object(agent, "_extract_chronological_entries", side_effect=fake_extract), \
                 patch("outheis.agents.data.load_config") as mock_cfg, \
                 patch("outheis.agents.data.get_human_dir", return_value=Path(d)), \
                 patch("outheis.core.agenda_store._agenda_json_path", return_value=agenda_path):
                mock_cfg.return_value.human.primary_vault.return_value = vault
                mock_cfg.return_value.agents.get.return_value = None
                agent.scan_chronological_entries()

        assert "new.md" in processed


# ---------------------------------------------------------------------------
# scan_chronological_entries — agenda.json output
# ---------------------------------------------------------------------------

class TestScanWritesAgendaJson:

    def test_extracted_items_written_to_agenda_json(self):
        """Entries from a new vault file appear in agenda.json with correct source."""
        from datetime import date
        agent = make_agent()
        today = date.today().isoformat()

        with tempfile.TemporaryDirectory() as d:
            vault = Path(d)
            (vault / "Agenda").mkdir()
            cache_path = Path(d) / "cache" / "shadow" / "file_state.json"
            cache_path.parent.mkdir(parents=True)
            cache_path.write_text("{}")

            (vault / "work.md").write_text("Team standup every Monday")

            def fake_extract(filename, content):
                return f"#date-{today} #facet-hiro\nTeam standup\n"

            agenda_path = Path(d) / "webui" / "pages" / "agenda.json"
            with patch.object(agent, "_extract_chronological_entries", side_effect=fake_extract), \
                 patch("outheis.agents.data.load_config") as mock_cfg, \
                 patch("outheis.agents.data.get_human_dir", return_value=Path(d)), \
                 patch("outheis.core.agenda_store._agenda_json_path", return_value=agenda_path):
                mock_cfg.return_value.human.primary_vault.return_value = vault
                mock_cfg.return_value.agents.get.return_value = None
                agent.scan_chronological_entries()

            assert agenda_path.exists()
            data = json.loads(agenda_path.read_text())
            items = data["items"]
            assert len(items) == 1
            assert items[0]["title"] == "Team standup"
            assert items[0]["source"] == "work.md"
            assert "#facet-hiro" in items[0].get("tags", [])

    def test_deleted_file_items_removed_from_agenda_json(self):
        """Items from a deleted vault file are removed from agenda.json."""
        from datetime import date
        agent = make_agent()
        today = date.today().isoformat()

        with tempfile.TemporaryDirectory() as d:
            vault = Path(d)
            (vault / "Agenda").mkdir()
            cache_path = Path(d) / "cache" / "shadow" / "file_state.json"
            cache_path.parent.mkdir(parents=True)
            # Cache says deleted.md existed before
            cache_path.write_text(json.dumps({"deleted.md": "oldhash"}))

            # agenda.json already has an item from deleted.md
            agenda_path = Path(d) / "webui" / "pages" / "agenda.json"
            agenda_path.parent.mkdir(parents=True)
            agenda_path.write_text(json.dumps({
                "meta": {}, "facets": [], "view": {},
                "items": [{"id": "x1", "source": "deleted.md", "title": "Gone"}]
            }))

            with patch("outheis.agents.data.load_config") as mock_cfg, \
                 patch("outheis.agents.data.get_human_dir", return_value=Path(d)), \
                 patch("outheis.core.agenda_store._agenda_json_path", return_value=agenda_path):
                mock_cfg.return_value.human.primary_vault.return_value = vault
                mock_cfg.return_value.agents.get.return_value = None
                agent.scan_chronological_entries()

            data = json.loads(agenda_path.read_text())
            assert not any(it["source"] == "deleted.md" for it in data["items"])

    def test_none_extraction_removes_source_items(self):
        """If LLM returns empty/NONE for a changed file, its items are removed."""
        agent = make_agent()

        with tempfile.TemporaryDirectory() as d:
            vault = Path(d)
            (vault / "Agenda").mkdir()
            cache_path = Path(d) / "cache" / "shadow" / "file_state.json"
            cache_path.parent.mkdir(parents=True)
            cache_path.write_text(json.dumps({"clean.md": "oldhash"}))

            note = vault / "clean.md"
            note.write_text("updated content with no dates")

            agenda_path = Path(d) / "webui" / "pages" / "agenda.json"
            agenda_path.parent.mkdir(parents=True)
            agenda_path.write_text(json.dumps({
                "meta": {}, "facets": [], "view": {},
                "items": [{"id": "stale", "source": "clean.md", "title": "Stale item"}]
            }))

            def fake_extract(filename, content):
                return ""  # no entries

            with patch.object(agent, "_extract_chronological_entries", side_effect=fake_extract), \
                 patch("outheis.agents.data.load_config") as mock_cfg, \
                 patch("outheis.agents.data.get_human_dir", return_value=Path(d)), \
                 patch("outheis.core.agenda_store._agenda_json_path", return_value=agenda_path):
                mock_cfg.return_value.human.primary_vault.return_value = vault
                mock_cfg.return_value.agents.get.return_value = None
                agent.scan_chronological_entries()

            data = json.loads(agenda_path.read_text())
            assert not any(it["source"] == "clean.md" for it in data["items"])
