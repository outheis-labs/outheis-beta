"""
Schema versioning — single source of truth.

All data structures are versioned. Migration happens at read time
for outdated records. Use `outheis migrate` for batch conversion.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

# =============================================================================
# VERSION CONSTANTS — increment when schema changes
# =============================================================================

MESSAGES_VERSION = 1
INSIGHTS_VERSION = 1
SESSION_NOTES_VERSION = 1
CONFIG_VERSION = 1
INDEX_VERSION = 1
TAG_WEIGHTS_VERSION = 1


# =============================================================================
# EXCEPTIONS
# =============================================================================

class SchemaError(Exception):
    """Base class for schema errors."""
    pass


class UnsupportedVersion(SchemaError):
    """Record version is newer than supported."""

    def __init__(self, record_type: str, found: int, supported: int):
        self.record_type = record_type
        self.found = found
        self.supported = supported
        super().__init__(
            f"{record_type} v{found} requires newer outheis "
            f"(this version supports up to v{supported})"
        )


class MigrationError(SchemaError):
    """Migration failed."""
    pass


# =============================================================================
# MIGRATION FUNCTIONS
# =============================================================================

def migrate_message(msg: dict, from_version: int) -> dict:
    """
    Stepwise migration: v0 → v1 → v2 → ...

    Each step is isolated and testable.
    Returns migrated message with updated version.
    """
    if from_version < 1:
        # v0 → v1: Initial schema, no changes needed
        # (v0 means pre-versioning, treat as v1)
        msg["v"] = 1
        from_version = 1

    # Future migrations go here:
    # if from_version < 2:
    #     # v1 → v2: Add new field with default
    #     msg.setdefault("priority", "normal")
    #     msg["v"] = 2
    #     from_version = 2

    return msg


def migrate_insight(insight: dict, from_version: int) -> dict:
    """Migrate insight records."""
    if from_version < 1:
        insight["v"] = 1
        from_version = 1

    return insight


def migrate_session_note(note: dict, from_version: int) -> dict:
    """Migrate session note records."""
    if from_version < 1:
        note["v"] = 1
        from_version = 1

    return note


# =============================================================================
# READ FUNCTIONS — handle version check and migration
# =============================================================================

def read_message(line: str) -> dict:
    """
    Parse and migrate a message record.

    Hot path: if version matches, just parse and return.
    Cold path: migrate outdated records.
    """
    msg = json.loads(line)
    version = msg.get("v", 0)

    if version == MESSAGES_VERSION:
        return msg  # Hot path, no overhead

    if version > MESSAGES_VERSION:
        raise UnsupportedVersion("Message", version, MESSAGES_VERSION)

    return migrate_message(msg, from_version=version)


def read_insight(line: str) -> dict:
    """Parse and migrate an insight record."""
    insight = json.loads(line)
    version = insight.get("v", 0)

    if version == INSIGHTS_VERSION:
        return insight

    if version > INSIGHTS_VERSION:
        raise UnsupportedVersion("Insight", version, INSIGHTS_VERSION)

    return migrate_insight(insight, from_version=version)


def read_session_note(line: str) -> dict:
    """Parse and migrate a session note record."""
    note = json.loads(line)
    version = note.get("v", 0)

    if version == SESSION_NOTES_VERSION:
        return note

    if version > SESSION_NOTES_VERSION:
        raise UnsupportedVersion("SessionNote", version, SESSION_NOTES_VERSION)

    return migrate_session_note(note, from_version=version)


# =============================================================================
# WRITE FUNCTIONS — always write current version
# =============================================================================

def write_message(msg: dict) -> str:
    """Serialize a message with current version."""
    msg["v"] = MESSAGES_VERSION
    return json.dumps(msg, ensure_ascii=False)


def write_insight(insight: dict) -> str:
    """Serialize an insight with current version."""
    insight["v"] = INSIGHTS_VERSION
    return json.dumps(insight, ensure_ascii=False)


def write_session_note(note: dict) -> str:
    """Serialize a session note with current version."""
    note["v"] = SESSION_NOTES_VERSION
    return json.dumps(note, ensure_ascii=False)


# =============================================================================
# MIGRATION UTILITIES — for CLI tool
# =============================================================================

@dataclass
class MigrationReport:
    """Result of scanning or migrating a file."""
    path: str
    record_type: str
    total: int
    outdated: int
    current_version: int
    versions_found: dict[int, int]  # version → count


def scan_file(path: str, record_type: str, current_version: int) -> MigrationReport:
    """
    Scan a JSONL file and report version distribution.

    Does not modify the file.
    """
    versions: dict[int, int] = {}
    total = 0

    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                v = record.get("v", 0)
                versions[v] = versions.get(v, 0) + 1
                total += 1
            except json.JSONDecodeError:
                continue

    outdated = sum(count for v, count in versions.items() if v < current_version)

    return MigrationReport(
        path=path,
        record_type=record_type,
        total=total,
        outdated=outdated,
        current_version=current_version,
        versions_found=versions,
    )
