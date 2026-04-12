"""
Memory system for persistent user knowledge.

Memory types:
- user: Personal information (family, preferences, background) — permanent
- feedback: How the agent should work (style, format, behavior) — permanent
- context: Current focus, active projects, recent topics — managed by rumi

Storage format: Markdown (.md), one line per entry with date comment.
Human-readable and editable directly in Obsidian or any text editor.

Format:
  - Entry content here  <!-- YYYY-MM-DD -->

Decay is handled semantically by the Pattern agent (rumi) during its
daily run. No programmatic timer is used.

All memory stays local, under user control, deletable, inspectable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

from outheis.core.config import get_human_dir


# =============================================================================
# TYPES
# =============================================================================

MemoryType = Literal["user", "feedback", "context"]

_COMMENT_RE = re.compile(r"\s*<!--\s*(\d{4}-\d{2}-\d{2})(?:\s+source:(\w+))?\s*-->")
_HEADERS = {
    "user": "# User Memory\n\n",
    "feedback": "# Feedback Memory\n\n",
    "context": "# Context Memory\n\n",
}

# Characters that are invisible/non-printable and have no legitimate use
# in memory entries. Stripped on write, not on read.
_INVISIBLE_RE = re.compile(
    "["
    "\x00-\x08"      # ASCII control: NUL–BS
    "\x0b\x0c"       # vertical tab, form feed
    "\x0e-\x1f"      # ASCII control: SO–US
    "\x7f"           # DEL
    "\u00ad"         # soft hyphen
    "\u200b-\u200f"  # zero-width spaces, joiners, marks
    "\u2028\u2029"   # line/paragraph separators
    "\u202a-\u202e"  # bidirectional overrides
    "\u2060-\u2064"  # word joiner, invisible operators
    "\ufeff"         # BOM
    "\ufff9-\ufffc"  # interlinear annotation anchors
    "]"
)


def _sanitize(text: str) -> str:
    """Strip all invisible and non-printable characters from text."""
    return _INVISIBLE_RE.sub("", text).strip()


def _format_entry_line(entry: "MemoryEntry") -> str:
    """Format a memory entry for inclusion in a prompt context string.

    External entries are wrapped in boundary markers to limit prompt injection
    surface area. Agent and user entries are rendered as plain bullet points.
    """
    if entry.source == "external":
        return (
            f"- <external_content>{entry.content}</external_content>"
        )
    return f"- {entry.content}"


def wrap_external_content(text: str) -> str:
    """Wrap externally-sourced text in boundary markers for safe prompt inclusion.

    Use this when including content from external sources (web pages, repos,
    user-supplied files) directly in a system or user prompt — not via memory.
    """
    return f"<external_content>{text}</external_content>"


@dataclass
class MemoryEntry:
    """A single memory entry."""

    content: str
    type: MemoryType
    created_at: datetime = field(default_factory=datetime.now)
    source: str = "agent"  # "user" | "agent" | "external"

    def to_line(self) -> str:
        """Render as a markdown list line with date comment."""
        date = self.created_at.strftime("%Y-%m-%d")
        suffix = f" source:{self.source}" if self.source != "agent" else ""
        return f"- {self.content}  <!-- {date}{suffix} -->\n"


def _parse_line(line: str, memory_type: MemoryType) -> MemoryEntry | None:
    """Parse a markdown list line into a MemoryEntry. Returns None if not a valid entry."""
    stripped = line.strip()
    if not stripped.startswith("- "):
        return None
    raw = stripped[2:]
    m = _COMMENT_RE.search(raw)
    if m:
        content = raw[: m.start()].strip()
        try:
            created_at = datetime.strptime(m.group(1), "%Y-%m-%d")
        except ValueError:
            created_at = datetime.now()
        source = m.group(2) or "agent"
    else:
        content = raw.strip()
        created_at = datetime.now()
        source = "agent"
    if not content:
        return None
    return MemoryEntry(content=content, type=memory_type, created_at=created_at, source=source)


# =============================================================================
# MEMORY STORE
# =============================================================================


@dataclass
class MemoryStore:
    """
    Persistent memory storage.

    Stores user knowledge, feedback, and context in human-readable
    Markdown files. One line per entry, with date comment.
    """

    base_path: Path = field(default_factory=get_human_dir)
    _entries: dict[str, list[MemoryEntry]] = field(default_factory=dict)
    _loaded: bool = False

    @property
    def memory_path(self) -> Path:
        return self.base_path / "memory"

    def _ensure_dir(self) -> None:
        self.memory_path.mkdir(parents=True, exist_ok=True)

    def _file_path(self, memory_type: MemoryType) -> Path:
        return self.memory_path / f"{memory_type}.md"

    def _migrate_from_json(self, memory_type: MemoryType) -> list[MemoryEntry]:
        """Read legacy JSON file and return entries. Does not delete the JSON."""
        import json
        json_path = self.memory_path / f"{memory_type}.json"
        if not json_path.exists():
            return []
        try:
            with open(json_path) as f:
                data = json.load(f)
            entries = []
            for e in data.get("entries", []):
                try:
                    content = e["content"]
                    created_at = datetime.fromisoformat(e.get("created_at", datetime.now().isoformat()))
                    entries.append(MemoryEntry(content=content, type=memory_type, created_at=created_at))
                except (KeyError, ValueError):
                    pass
            return entries
        except Exception as err:
            print(f"[memory] could not migrate {memory_type}.json: {err}")
            return []

    def load(self) -> None:
        """Load all memory from disk. Migrates from JSON if .md not present."""
        self._ensure_dir()
        self._entries = {"user": [], "feedback": [], "context": []}

        for memory_type in ("user", "feedback", "context"):
            md_path = self._file_path(memory_type)
            if not md_path.exists():
                # Migrate from legacy JSON
                migrated = self._migrate_from_json(memory_type)
                if migrated:
                    self._entries[memory_type] = migrated
                    self._write_file(memory_type, migrated)
                    print(f"[memory] migrated {len(migrated)} entries from {memory_type}.json → {memory_type}.md")
            else:
                entries = []
                for line in md_path.read_text(encoding="utf-8").splitlines():
                    entry = _parse_line(line, memory_type)
                    if entry:
                        entries.append(entry)
                self._entries[memory_type] = entries

        self._loaded = True

    def _write_file(self, memory_type: MemoryType, entries: list[MemoryEntry]) -> None:
        """Write all entries for a type to disk (full rewrite)."""
        self._ensure_dir()
        path = self._file_path(memory_type)
        header = _HEADERS[memory_type]
        path.write_text(header + "".join(e.to_line() for e in entries), encoding="utf-8")

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

    def get(self, memory_type: MemoryType) -> list[MemoryEntry]:
        """Get all entries of a type."""
        self._ensure_loaded()
        return list(self._entries.get(memory_type, []))

    def get_all(self, **_kwargs) -> dict[str, list[MemoryEntry]]:
        """Get all memory entries."""
        self._ensure_loaded()
        return {mt: list(entries) for mt, entries in self._entries.items()}

    def add(
        self,
        content: str,
        memory_type: MemoryType,
        source: str = "agent",
        # Legacy params accepted but ignored — kept for call-site compatibility
        confidence: float = 1.0,
        decay_days: int | None = None,
        is_explicit: bool = False,
    ) -> MemoryEntry:
        """Add a new memory entry."""
        self._ensure_loaded()

        content = _sanitize(content)
        entry = MemoryEntry(content=content, type=memory_type, source=source)

        if memory_type not in self._entries:
            self._entries[memory_type] = []
        self._entries[memory_type].append(entry)

        # Append to file directly — avoid full rewrite on every add
        path = self._file_path(memory_type)
        if not path.exists():
            path.write_text(_HEADERS[memory_type] + entry.to_line(), encoding="utf-8")
        else:
            with path.open("a", encoding="utf-8") as f:
                f.write(entry.to_line())

        return entry

    def rewrite(self, memory_type: MemoryType, entries: list[MemoryEntry]) -> None:
        """Replace all entries of a type (used by consolidation)."""
        self._ensure_loaded()
        self._entries[memory_type] = list(entries)
        self._write_file(memory_type, entries)

    def rewrite_from_markdown(self, memory_type: MemoryType, markdown: str) -> int:
        """
        Parse a markdown string and rewrite the file.
        Used by Pattern agent after LLM consolidation.
        Returns number of entries written.
        """
        entries = []
        for line in markdown.splitlines():
            entry = _parse_line(line, memory_type)
            if entry:
                entries.append(entry)
        self.rewrite(memory_type, entries)
        return len(entries)

    def remove_by_content(self, memory_type: MemoryType, content: str) -> bool:
        """Remove entry whose content matches (substring). Returns True if found."""
        self._ensure_loaded()
        entries = self._entries.get(memory_type, [])
        before = len(entries)
        self._entries[memory_type] = [e for e in entries if content not in e.content]
        if len(self._entries[memory_type]) < before:
            self._write_file(memory_type, self._entries[memory_type])
            return True
        return False

    # kept for backward compatibility with any call sites that still use index-based remove
    def remove(self, memory_type: MemoryType, index: int) -> bool:
        """Remove a memory entry by index."""
        self._ensure_loaded()
        entries = self._entries.get(memory_type, [])
        if 0 <= index < len(entries):
            entries.pop(index)
            self._write_file(memory_type, entries)
            return True
        return False

    def cleanup_expired(self) -> int:
        """No-op: decay is handled by rumi. Kept for call-site compatibility."""
        return 0

    def to_prompt_context(self) -> str:
        """Generate context string for agent prompts."""
        self._ensure_loaded()

        sections = []

        user_entries = self._entries.get("user", [])
        if user_entries:
            lines = [_format_entry_line(e) for e in user_entries]
            sections.append("## About the user\n" + "\n".join(lines))

        feedback_entries = self._entries.get("feedback", [])
        if feedback_entries:
            lines = [_format_entry_line(e) for e in feedback_entries]
            sections.append("## Working preferences\n" + "\n".join(lines))

        context_entries = self._entries.get("context", [])
        if context_entries:
            lines = [_format_entry_line(e) for e in context_entries]
            sections.append("## Current context\n" + "\n".join(lines))

        if not sections:
            return ""

        return "# Memory\n\n" + "\n\n".join(sections)


# =============================================================================
# SINGLETON ACCESS
# =============================================================================

_store: MemoryStore | None = None


def get_memory_store() -> MemoryStore:
    """Get the global memory store instance."""
    global _store
    if _store is None:
        _store = MemoryStore()
    return _store


def get_memory_context() -> str:
    """Get formatted memory context for prompts."""
    return get_memory_store().to_prompt_context()


def parse_explicit_memory(text: str) -> tuple[str | None, MemoryType | None, str]:
    """
    Parse explicit memory marker from user input.

    User can prefix with "!" to explicitly save to memory:
    - "! I prefer short answers" → feedback
    - "! my children are named Leo and Emma" → user
    - "! I am currently working on Project Alpha" → context

    Returns:
        (content, memory_type, remaining_text)
        If no marker found: (None, None, original_text)
    """
    text = text.strip()

    if not text.startswith("!") or len(text) < 3:
        return None, None, text

    content = text[1:].strip()

    if not content or content.startswith("!"):
        return None, None, text

    content_lower = content.lower()

    feedback_keywords = [
        "prefer", "please", "always", "never", "response", "format", "style",
        "short", "long", "formal", "casual",
    ]
    context_keywords = [
        "working", "project", "currently", "focus", "deadline", "this week",
    ]

    if any(kw in content_lower for kw in feedback_keywords):
        return content, "feedback", ""
    if any(kw in content_lower for kw in context_keywords):
        return content, "context", ""
    return content, "user", ""


def handle_explicit_memory(text: str) -> tuple[bool, str, MemoryType | None]:
    """
    Process explicit memory marker and store if found.

    Returns:
        (was_memory_command, content, memory_type)
    """
    content, memory_type, _ = parse_explicit_memory(text)

    if content and memory_type:
        store = get_memory_store()
        store.add(content, memory_type, is_explicit=True)
        return True, content, memory_type

    return False, text, None
