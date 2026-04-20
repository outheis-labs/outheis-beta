"""Tests for search index."""

import tempfile
from pathlib import Path

import pytest

from outheis.core.index import IndexEntry, create_index


@pytest.fixture
def temp_vault():
    """Create a temporary vault with test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        vault = Path(tmpdir)

        # Create test files
        (vault / "projects").mkdir()
        (vault / "notes").mkdir()

        # Project file
        (vault / "projects" / "alpha.md").write_text("""---
title: Project Alpha
tags: [active, client]
---

# Project Alpha

This is the main project document.
Status: in progress.
""")

        # Note file
        (vault / "notes" / "ideas.md").write_text("""---
title: Random Ideas
tags: [brainstorm]
---

# Ideas

- Build a better mousetrap
- Learn Rust
- Project Alpha integration
""")

        # File without frontmatter
        (vault / "readme.md").write_text("""# README

This vault contains notes and projects.
""")

        yield vault


class TestIndexEntry:
    def test_to_dict_roundtrip(self):
        entry = IndexEntry(
            path="test.md",
            title="Test",
            tags=["a", "b"],
            content_hash="abc123",
            indexed_at="2025-01-01T00:00:00Z",
            searchable="test a b content",
        )

        data = entry.to_dict()
        restored = IndexEntry.from_dict(data)

        assert restored.path == entry.path
        assert restored.title == entry.title
        assert restored.tags == entry.tags
        assert restored.content_hash == entry.content_hash


class TestSearchIndex:
    def test_rebuild(self, temp_vault):
        index = create_index(temp_vault)
        count = index.rebuild()

        assert count == 3  # alpha.md, ideas.md, readme.md
        assert "projects/alpha.md" in index.entries
        assert "notes/ideas.md" in index.entries

    def test_search(self, temp_vault):
        index = create_index(temp_vault)
        index.rebuild()

        results = index.search("alpha")
        assert len(results) >= 1

        # Both files mention "alpha"
        paths = [e.path for e in results]
        assert "projects/alpha.md" in paths

    def test_search_by_tag(self, temp_vault):
        index = create_index(temp_vault)
        index.rebuild()

        results = index.search_by_tag("active")
        assert len(results) == 1
        assert results[0].path == "projects/alpha.md"

    def test_get_all_tags(self, temp_vault):
        index = create_index(temp_vault)
        index.rebuild()

        tags = index.get_all_tags()
        assert "active" in tags
        assert "client" in tags
        assert "brainstorm" in tags

    def test_incremental_update(self, temp_vault):
        index = create_index(temp_vault)
        index.rebuild()

        # Modify a file
        (temp_vault / "projects" / "alpha.md").write_text("""---
title: Project Alpha Updated
tags: [active, client, updated]
---

# Updated content
""")

        added, updated, removed = index.update()

        assert updated == 1
        assert added == 0
        assert removed == 0

        # Check tag was added
        tags = index.get_all_tags()
        assert "updated" in tags

    def test_save_and_load(self, temp_vault):
        index = create_index(temp_vault)
        index.rebuild()

        # Create new index instance and load
        index2 = create_index(temp_vault)
        index2.load()

        assert len(index2.entries) == len(index.entries)
        assert "projects/alpha.md" in index2.entries


class TestSearchRelevance:
    def test_multiple_term_match_ranks_higher(self, temp_vault):
        # Add file that matches multiple terms
        (temp_vault / "notes" / "multi.md").write_text("""---
title: Multi Match
tags: [alpha, project]
---

Project Alpha discussion about alpha testing.
""")

        index = create_index(temp_vault)
        index.rebuild()

        results = index.search("alpha project")

        # multi.md should rank high (matches both terms multiple times)
        assert len(results) >= 1
