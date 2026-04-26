"""test_agenda_store — unit tests for core/agenda_store.py.

Covers: parse_tag_entries_to_items, items_to_tag_text, merge_cato_write,
replace_items_by_source, remove_items_by_source, prune_done_items.
"""

import json
import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TODAY = date.today().isoformat()
TOMORROW = (date.today() + timedelta(days=1)).isoformat()
YESTERDAY = (date.today() - timedelta(days=1)).isoformat()
IN_5_DAYS = (date.today() + timedelta(days=5)).isoformat()
IN_10_DAYS = (date.today() + timedelta(days=10)).isoformat()


def _import():
    from outheis.core import agenda_store
    return agenda_store


# ---------------------------------------------------------------------------
# parse_tag_entries_to_items
# ---------------------------------------------------------------------------

class TestParseTagEntriesToItems:

    def test_fixed_single_day(self):
        store = _import()
        text = f"#date-{TODAY} #time-09:00-10:30 #facet-cato\nWorkshop\n"
        items = store.parse_tag_entries_to_items(text, source="projects/a.md")
        assert len(items) == 1
        it = items[0]
        tags = it.get("tags", [])
        assert f"#date-{TODAY}" in tags
        assert "#time-09:00-10:30" in tags
        assert "#facet-cato" in tags
        assert it["source"] == "projects/a.md"

    def test_volatile_with_date(self):
        store = _import()
        text = f"#date-{IN_5_DAYS} #facet-senswork\nCall Supplier\n"
        items = store.parse_tag_entries_to_items(text, source="inbox.md")
        assert len(items) == 1
        it = items[0]
        tags = it.get("tags", [])
        assert f"#date-{IN_5_DAYS}" in tags
        assert "#facet-senswork" in tags

    def test_undated_action_required(self):
        store = _import()
        text = "#action-required #facet-misc\nReview contract\n"
        items = store.parse_tag_entries_to_items(text, source="cato")
        assert len(items) == 1
        it = items[0]
        tags = it.get("tags", [])
        assert "#action-required" in tags

    def test_multiday_fixed(self):
        store = _import()
        text = f"#date-{IN_5_DAYS} #date-{IN_10_DAYS} #time-12:00-18:00 #facet-zeno\nConference\n"
        items = store.parse_tag_entries_to_items(text, source="travel.md")
        assert len(items) == 1
        it = items[0]
        tags = it.get("tags", [])
        assert f"#date-{IN_5_DAYS}" in tags
        assert f"#date-{IN_10_DAYS}" in tags
        assert "#time-12:00-18:00" in tags
        assert "#facet-zeno" in tags

    def test_done_item_skipped(self):
        store = _import()
        text = f"#done-{YESTERDAY} #date-{TODAY} #facet-cato\nAlready done\n"
        items = store.parse_tag_entries_to_items(text, source="file.md")
        assert items == []

    def test_multiple_entries(self):
        store = _import()
        text = (
            f"#date-{TODAY} #facet-cato\nTask A\n\n"
            f"#date-{TOMORROW} #facet-hiro\nTask B\n"
        )
        items = store.parse_tag_entries_to_items(text, source="work.md")
        assert len(items) == 2
        assert items[0]["title"] == "Task A"
        assert items[1]["title"] == "Task B"

    def test_preserves_existing_id(self):
        store = _import()
        text = f"#id-abc123 #date-{TODAY} #facet-cato\nNamed item\n"
        items = store.parse_tag_entries_to_items(text, source="file.md")
        assert items[0]["id"] == "abc123"

    def test_generates_id_when_missing(self):
        store = _import()
        text = f"#date-{TODAY} #facet-cato\nItem without ID\n"
        items = store.parse_tag_entries_to_items(text, source="file.md")
        assert items[0]["id"] != ""
        assert len(items[0]["id"]) > 0

    def test_density_tag(self):
        store = _import()
        text = f"#date-{TODAY} #time-09:00-11:00 #facet-cato #density-high\nDeep work\n"
        items = store.parse_tag_entries_to_items(text, source="file.md")
        tags = items[0].get("tags", [])
        assert "#density-high" in tags

    def test_size_tag_volatile(self):
        store = _import()
        text = f"#date-{TODAY} #facet-misc #size-l\nBig task\n"
        items = store.parse_tag_entries_to_items(text, source="file.md")
        tags = items[0].get("tags", [])
        assert "#size-l" in tags

    def test_default_facet_is_none(self):
        """Items without explicit facet get no #facet tag (implicit 'none')."""
        store = _import()
        text = f"#date-{TODAY}\nTask without facet\n"
        items = store.parse_tag_entries_to_items(text, source="file.md")
        tags = items[0].get("tags", [])
        assert not any(t.startswith("#facet-") for t in tags)

    def test_empty_text_returns_empty(self):
        store = _import()
        assert store.parse_tag_entries_to_items("", source="file.md") == []

    def test_none_text_returns_empty(self):
        store = _import()
        assert store.parse_tag_entries_to_items("NONE", source="file.md") == []


# ---------------------------------------------------------------------------
# items_to_tag_text
# ---------------------------------------------------------------------------

class TestItemsToTagText:

    def _make_item(self, **kwargs):
        """Create an item dict with tags array (current schema)."""
        base = {
            "id": "0000000000000001",
            "title": "Test item",
            "source": "cato",
            "tags": [],
        }
        base.update(kwargs)
        return base

    def test_contains_id_tag(self):
        store = _import()
        item = self._make_item(id="abc999")
        text = store.items_to_tag_text([item])
        assert "#id-abc999" in text

    def test_fixed_item_has_time_tag(self):
        store = _import()
        item = self._make_item(tags=["#date-2026-04-25", "#time-09:00-10:30", "#facet-cato"])
        text = store.items_to_tag_text([item])
        assert "#time-09:00-10:30" in text

    def test_volatile_no_time_tag(self):
        store = _import()
        item = self._make_item(tags=["#date-2026-04-27", "#facet-zeno"])
        text = store.items_to_tag_text([item])
        assert "#time-" not in text

    def test_undated_has_action_required(self):
        store = _import()
        item = self._make_item(tags=["#action-required"])
        text = store.items_to_tag_text([item])
        assert "#action-required" in text

    def test_title_present(self):
        store = _import()
        item = self._make_item(title="Call Markus")
        text = store.items_to_tag_text([item])
        assert "Call Markus" in text

    def test_grouped_by_source(self):
        store = _import()
        items = [
            self._make_item(source="projects/a.md", title="A"),
            self._make_item(source="cato", title="B"),
        ]
        text = store.items_to_tag_text(items)
        assert "<!-- BEGIN: projects/a.md -->" in text
        assert "<!-- BEGIN: cato -->" in text

    def test_facet_tag_included(self):
        store = _import()
        item = self._make_item(tags=["#date-2026-04-25", "#facet-hiro"])
        text = store.items_to_tag_text([item])
        assert "#facet-hiro" in text

    def test_misc_facet_not_emitted(self):
        """'none' facet is implicit — no #facet tag in output."""
        store = _import()
        item = self._make_item(tags=["#date-2026-04-25"])  # no facet
        text = store.items_to_tag_text([item])
        assert "#facet-" not in text

    def test_done_item_includes_done_tag(self):
        store = _import()
        item = self._make_item(tags=["#date-2026-04-25"], done=YESTERDAY)
        text = store.items_to_tag_text([item])
        assert f"#done-{YESTERDAY}" in text

    def test_roundtrip_volatile(self):
        """parse → render → parse gives same title."""
        store = _import()
        original = f"#date-{TODAY} #facet-ou\nBuy groceries\n"
        items = store.parse_tag_entries_to_items(original, source="list.md")
        text = store.items_to_tag_text(items)
        # items_to_tag_text wraps in tag format — extract the entry
        import re
        entry_match = re.search(r'(#id-\S+.*?\n.*?\n)', text, re.DOTALL)
        assert entry_match, f"No entry found in: {text}"
        # Parse the entry portion
        items2 = store.parse_tag_entries_to_items(entry_match.group(1), source="list.md")
        assert len(items2) == 1
        assert items2[0]["title"] == "Buy groceries"
        # Check facet is in tags
        assert any(t == "#facet-ou" for t in items2[0].get("tags", []))


# ---------------------------------------------------------------------------
# replace_items_by_source / remove_items_by_source
# ---------------------------------------------------------------------------

class TestSourceMutations:

    def _data(self):
        return {
            "items": [
                {"id": "1", "source": "file.md", "title": "From file"},
                {"id": "2", "source": "cato",    "title": "From cato"},
                {"id": "3", "source": "webui",   "title": "From webui"},
            ]
        }

    def test_replace_replaces_only_matching_source(self):
        store = _import()
        data = self._data()
        new = [{"id": "99", "source": "cato", "title": "New cato item"}]
        result = store.replace_items_by_source(data, "cato", new)
        titles = [it["title"] for it in result["items"]]
        assert "From file" in titles
        assert "From webui" in titles
        assert "From cato" not in titles
        assert "New cato item" in titles

    def test_replace_with_empty_removes_source(self):
        store = _import()
        data = self._data()
        result = store.replace_items_by_source(data, "cato", [])
        assert all(it["source"] != "cato" for it in result["items"])

    def test_remove_removes_only_matching_source(self):
        store = _import()
        data = self._data()
        result = store.remove_items_by_source(data, "file.md")
        assert all(it["source"] != "file.md" for it in result["items"])
        assert len(result["items"]) == 2

    def test_remove_unknown_source_is_noop(self):
        store = _import()
        data = self._data()
        before = len(data["items"])
        result = store.remove_items_by_source(data, "nonexistent.md")
        assert len(result["items"]) == before


# ---------------------------------------------------------------------------
# merge_cato_write
# ---------------------------------------------------------------------------

class TestMergeCatoWrite:

    def _data_with_items(self, items):
        return {"meta": {}, "facets": [], "view": {}, "items": items}

    def test_new_item_added_with_default_source(self):
        store = _import()
        data = self._data_with_items([])
        tag_text = f"#date-{TODAY} #facet-cato\nNew task\n"
        result = store.merge_cato_write(data, tag_text, default_source="cato")
        items = result["items"]
        assert len(items) == 1
        assert items[0]["title"] == "New task"
        assert items[0]["source"] == "cato"

    def test_existing_item_updated_by_id(self):
        store = _import()
        existing = {
            "id": "id001", "title": "Old title", "source": "cato",
            "tags": ["#date-2026-04-25", "#facet-senswork"]
        }
        data = self._data_with_items([existing])
        tag_text = f"#id-id001 #date-{TOMORROW} #facet-hiro\nUpdated title\n"
        result = store.merge_cato_write(data, tag_text, default_source="cato")
        items = result["items"]
        assert len(items) == 1
        assert items[0]["title"] == "Updated title"
        # source preserved
        assert items[0]["source"] == "cato"

    def test_vault_item_not_removed_by_cato_write(self):
        """Items from vault sources are never removed by cato's write_file(shadow)."""
        store = _import()
        vault_item = {
            "id": "v001", "title": "From vault", "source": "projects/a.md",
            "tags": ["#date-2026-04-28", "#facet-senswork"]
        }
        data = self._data_with_items([vault_item])
        # cato writes only its own item, vault item not mentioned
        tag_text = f"#date-{TODAY} #facet-senswork\nCato task\n"
        result = store.merge_cato_write(data, tag_text, default_source="cato")
        sources = {it["source"] for it in result["items"]}
        assert "projects/a.md" in sources

    def test_done_tag_marks_item(self):
        store = _import()
        item = {
            "id": "d001", "title": "Finish report", "source": "cato",
            "tags": ["#date-2026-04-25", "#time-09:00-10:00", "#facet-senswork"]
        }
        data = self._data_with_items([item])
        tag_text = f"#done-{TODAY} #id-d001 #date-{TODAY} #time-09:00-10:00 #facet-senswork\nFinish report\n"
        result = store.merge_cato_write(data, tag_text, default_source="cato")
        done_items = [it for it in result["items"] if any(t.startswith("#done-") for t in (it.get("tags") or []))]
        assert len(done_items) == 1
        assert f"#done-{TODAY}" in done_items[0].get("tags", [])

    def test_done_on_vault_item_marks_it(self):
        """A #done- tag matching a vault item's id marks that item without changing its source."""
        store = _import()
        item = {
            "id": "vd01", "title": "Call supplier", "source": "projects/b.md",
            "tags": ["#date-2026-04-26", "#facet-senswork"]
        }
        data = self._data_with_items([item])
        tag_text = f"#done-{TODAY} #id-vd01 #date-{TODAY} #facet-senswork\nCall supplier\n"
        result = store.merge_cato_write(data, tag_text, default_source="cato")
        marked = next(it for it in result["items"] if it["id"] == "vd01")
        assert f"#done-{TODAY}" in marked.get("tags", [])
        assert marked["source"] == "projects/b.md"  # source unchanged

    def test_cato_item_not_in_write_is_removed(self):
        """cato-owned items absent from tag_text are dropped (LLM intentionally removed them)."""
        store = _import()
        items = [
            {"id": "c001", "source": "cato", "title": "Old cato", "tags": ["#date-2026-04-25", "#facet-misc"]},
            {"id": "c002", "source": "cato", "title": "Keep cato", "tags": ["#date-2026-04-26", "#facet-misc"]},
        ]
        data = self._data_with_items(items)
        # Only c002 in tag text
        tag_text = f"#id-c002 #date-{TOMORROW} #facet-misc\nKeep cato\n"
        result = store.merge_cato_write(data, tag_text, default_source="cato")
        ids = {it["id"] for it in result["items"]}
        assert "c001" not in ids
        assert "c002" in ids


# ---------------------------------------------------------------------------
# prune_done_items
# ---------------------------------------------------------------------------

class TestPruneDoneItems:

    def test_prunes_expired_done_item(self):
        store = _import()
        long_ago = (date.today() - timedelta(days=100)).isoformat()
        items = [
            {"id": "1", "done": long_ago, "source": "cato"},
            {"id": "2", "source": "cato"},
        ]
        data = {"items": items}
        pruned = store.prune_done_items(data, retention_days=90)
        assert pruned == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["id"] == "2"

    def test_keeps_recent_done_item(self):
        store = _import()
        items = [{"id": "1", "done": TODAY, "source": "cato"}]
        data = {"items": items}
        pruned = store.prune_done_items(data, retention_days=90)
        assert pruned == 0
        assert len(data["items"]) == 1

    def test_keeps_items_without_done(self):
        store = _import()
        items = [{"id": "1", "source": "cato", "title": "Open task"}]
        data = {"items": items}
        pruned = store.prune_done_items(data, retention_days=30)
        assert pruned == 0


# ---------------------------------------------------------------------------
# read_agenda_json / write_agenda_json
# ---------------------------------------------------------------------------

class TestReadWriteAgendaJson:

    def test_write_then_read_roundtrip(self, tmp_path):
        store = _import()
        agenda_path = tmp_path / "webui" / "pages" / "agenda.json"

        with patch("outheis.core.agenda_store._agenda_json_path", return_value=agenda_path):
            data = store.read_agenda_json()
            data["items"].append({"id": "t1", "title": "Test", "source": "cli"})
            store.write_agenda_json(data)
            loaded = store.read_agenda_json()

        assert any(it["id"] == "t1" for it in loaded["items"])

    def test_write_updates_meta_timestamps(self, tmp_path):
        """write_agenda_json sets generated timestamp and removes base_date."""
        store = _import()
        agenda_path = tmp_path / "webui" / "pages" / "agenda.json"

        with patch("outheis.core.agenda_store._agenda_json_path", return_value=agenda_path):
            data = store._empty_agenda()
            data["meta"]["base_date"] = "2000-01-01"  # stale
            store.write_agenda_json(data)
            loaded = store.read_agenda_json()

        # base_date is removed by write_agenda_json
        assert "base_date" not in loaded["meta"]
        # generated timestamp is set
        assert "generated" in loaded["meta"]

    def test_missing_file_returns_empty_structure(self, tmp_path):
        store = _import()
        missing = tmp_path / "nonexistent.json"

        with patch("outheis.core.agenda_store._agenda_json_path", return_value=missing):
            data = store.read_agenda_json()

        assert "items" in data
        assert "meta" in data
        assert "facets" in data
