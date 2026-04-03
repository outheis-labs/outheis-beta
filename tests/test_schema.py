"""Tests for schema versioning and migration."""

import json

import pytest

from outheis.core.schema import (
    INSIGHTS_VERSION,
    MESSAGES_VERSION,
    UnsupportedVersion,
    migrate_message,
    read_insight,
    read_message,
    write_insight,
    write_message,
)


class TestMessageVersioning:
    """Tests for message schema versioning."""

    def test_write_adds_version(self):
        """write_message adds current version."""
        msg = {"id": "test_001", "payload": {"text": "hello"}}
        line = write_message(msg)
        parsed = json.loads(line)
        assert parsed["v"] == MESSAGES_VERSION

    def test_read_current_version(self):
        """read_message passes through current version."""
        msg = {"v": MESSAGES_VERSION, "id": "test_001"}
        line = json.dumps(msg)
        result = read_message(line)
        assert result["v"] == MESSAGES_VERSION
        assert result["id"] == "test_001"

    def test_read_old_version_migrates(self):
        """read_message migrates old versions."""
        msg = {"v": 0, "id": "test_001"}
        line = json.dumps(msg)
        result = read_message(line)
        assert result["v"] == MESSAGES_VERSION

    def test_read_future_version_raises(self):
        """read_message raises for unsupported future versions."""
        msg = {"v": MESSAGES_VERSION + 10, "id": "test_001"}
        line = json.dumps(msg)
        with pytest.raises(UnsupportedVersion):
            read_message(line)

    def test_read_no_version_treated_as_v0(self):
        """Messages without version are treated as v0."""
        msg = {"id": "test_001"}
        line = json.dumps(msg)
        result = read_message(line)
        assert result["v"] == MESSAGES_VERSION


class TestMigration:
    """Tests for migration logic."""

    def test_migrate_v0_to_v1(self):
        """Migration from v0 to v1."""
        msg = {"id": "test_001", "from": "relay"}
        result = migrate_message(msg, from_version=0)
        assert result["v"] >= 1

    def test_migrate_preserves_data(self):
        """Migration preserves existing data."""
        msg = {"id": "test_001", "payload": {"text": "hello"}}
        result = migrate_message(msg, from_version=0)
        assert result["id"] == "test_001"
        assert result["payload"]["text"] == "hello"


class TestInsightVersioning:
    """Tests for insight schema versioning."""

    def test_write_adds_version(self):
        """write_insight adds current version."""
        insight = {"id": "ins_001", "type": "pattern"}
        line = write_insight(insight)
        parsed = json.loads(line)
        assert parsed["v"] == INSIGHTS_VERSION

    def test_read_current_version(self):
        """read_insight passes through current version."""
        insight = {"v": INSIGHTS_VERSION, "id": "ins_001"}
        line = json.dumps(insight)
        result = read_insight(line)
        assert result["v"] == INSIGHTS_VERSION
