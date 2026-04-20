"""test_data_create_shadow — unit tests for DataAgent Shadow.md creation.

Tests _write_shadow, _parse_shadow_sections, and scan_chronological_entries
file-selection logic without hitting the filesystem or API.
"""

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
# _write_shadow
# ---------------------------------------------------------------------------

class TestWriteShadow:

    def test_creates_file_with_header(self):
        agent = make_agent()
        with tempfile.TemporaryDirectory() as d:
            shadow = Path(d) / "Agenda" / "Shadow.md"
            shadow.parent.mkdir()
            agent._write_shadow(shadow, {"file.md": "#action-required\nDo something"})
            content = shadow.read_text()
        assert content.startswith("# Shadow — Vault Chronological Index")

    def test_sections_wrapped_in_markers(self):
        agent = make_agent()
        with tempfile.TemporaryDirectory() as d:
            shadow = Path(d) / "Agenda" / "Shadow.md"
            shadow.parent.mkdir()
            agent._write_shadow(shadow, {"project.md": "#action-required\nFinish report"})
            content = shadow.read_text()
        assert "<!-- BEGIN: project.md -->" in content
        assert "<!-- END: project.md -->" in content

    def test_sections_sorted_alphabetically(self):
        agent = make_agent()
        with tempfile.TemporaryDirectory() as d:
            shadow = Path(d) / "Agenda" / "Shadow.md"
            shadow.parent.mkdir()
            agent._write_shadow(shadow, {
                "zebra.md": "#action-required\nZ task",
                "alpha.md": "#action-required\nA task",
            })
            content = shadow.read_text()
        assert content.index("alpha.md") < content.index("zebra.md")

    def test_empty_sections_produces_header_only(self):
        agent = make_agent()
        with tempfile.TemporaryDirectory() as d:
            shadow = Path(d) / "Agenda" / "Shadow.md"
            shadow.parent.mkdir()
            agent._write_shadow(shadow, {})
            content = shadow.read_text()
        assert "<!-- BEGIN:" not in content


# ---------------------------------------------------------------------------
# _parse_shadow_sections
# ---------------------------------------------------------------------------

class TestParseShadowSections:

    def _make_shadow(self, path: Path, sections: dict[str, str]) -> None:
        make_agent()._write_shadow(path, sections)

    def test_roundtrip(self):
        """Write then parse returns identical sections."""
        agent = make_agent()
        with tempfile.TemporaryDirectory() as d:
            shadow = Path(d) / "Shadow.md"
            original = {
                "a.md": "#action-required\nTask A",
                "b.md": "#date-2026-04-01 #action-required\nTask B",
            }
            agent._write_shadow(shadow, original)
            parsed = agent._parse_shadow_sections(shadow)
        assert parsed == original

    def test_missing_file_returns_empty(self):
        agent = make_agent()
        result = agent._parse_shadow_sections(Path("/nonexistent/Shadow.md"))
        assert result == {}

    def test_section_body_preserves_content(self):
        agent = make_agent()
        with tempfile.TemporaryDirectory() as d:
            shadow = Path(d) / "Shadow.md"
            body = "#date-2026-05-01 #action-required #unit-project\nSend quarterly report to accountant"
            agent._write_shadow(shadow, {"just.md": body})
            parsed = agent._parse_shadow_sections(shadow)
        assert parsed["just.md"] == body


# ---------------------------------------------------------------------------
# scan_chronological_entries — file selection logic
# ---------------------------------------------------------------------------

class TestScanFileSelection:

    def test_skips_agenda_directory(self):
        """Files inside Agenda/ are never scanned."""
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
        """Files in hidden directories (dot-prefixed) are skipped."""
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
        """scan_chronological_entries processes only new or changed files."""
        agent = make_agent()
        with tempfile.TemporaryDirectory() as d:
            vault = Path(d)
            (vault / "Agenda").mkdir()
            vault / "Agenda" / "Shadow.md"
            cache_path = Path(d) / "cache" / "shadow" / "file_state.json"
            cache_path.parent.mkdir(parents=True)

            note = vault / "note.md"
            note.write_text("content")

            # Simulate: note.md already cached with same hash
            import hashlib
            import json
            note_hash = hashlib.md5(note.read_bytes()).hexdigest()
            cache_path.write_text(json.dumps({"note.md": note_hash}))

            processed = []

            def fake_extract(filename, content):
                processed.append(filename)
                return ""

            with patch.object(agent, "_extract_chronological_entries", side_effect=fake_extract), \
                 patch("outheis.agents.data.load_config") as mock_cfg, \
                 patch("outheis.agents.data.get_human_dir", return_value=Path(d)):
                mock_cfg.return_value.human.primary_vault.return_value = vault
                mock_cfg.return_value.agents.get.return_value = None  # no retention
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
            cache_path.write_text("{}")  # empty cache = all files are new

            (vault / "new.md").write_text("Meeting with ministry on 2026-03-20")

            processed = []

            def fake_extract(filename, content):
                processed.append(filename)
                return ""

            with patch.object(agent, "_extract_chronological_entries", side_effect=fake_extract), \
                 patch("outheis.agents.data.load_config") as mock_cfg, \
                 patch("outheis.agents.data.get_human_dir", return_value=Path(d)):
                mock_cfg.return_value.human.primary_vault.return_value = vault
                mock_cfg.return_value.agents.get.return_value = None  # no retention
                agent.scan_chronological_entries()

        assert "new.md" in processed
