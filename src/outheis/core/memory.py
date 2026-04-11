"""
Memory system for persistent user knowledge.

Separates meta-knowledge (about the user, working style) from
vault content (documents, notes, projects).

Memory types:
- user: Personal information (family, preferences, background) — permanent
- feedback: How the agent should work (style, format, behavior) — permanent
- context: Current focus, active projects, recent topics — 14 day decay

Memory is written by:
- Agents during interaction (relevant facts, intents, expressed wishes)
- Explicit "!" marker from user (shorthand for "remember this")
- Pattern agent (extracts from conversations during scheduled run)

All memory stays local, under user control, deletable, inspectable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal
import json
import os

from outheis.core.config import get_human_dir


# =============================================================================
# TYPES
# =============================================================================

MemoryType = Literal["user", "feedback", "context"]


@dataclass
class MemoryEntry:
    """A single memory entry."""
    
    content: str
    type: MemoryType
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    confidence: float = 1.0      # 0-1, how certain we are
    source_count: int = 1        # how many times this was mentioned
    decay_days: int | None = None  # None = permanent, number = days until expiry
    is_explicit: bool = False    # True if user used "!" marker
    
    @property
    def is_expired(self) -> bool:
        """Check if this entry has expired."""
        if self.decay_days is None:
            return False
        expiry = self.updated_at + timedelta(days=self.decay_days)
        return datetime.now() > expiry
    
    def to_dict(self) -> dict:
        return {
            "content": self.content,
            "type": self.type,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "confidence": self.confidence,
            "source_count": self.source_count,
            "decay_days": self.decay_days,
            "is_explicit": self.is_explicit,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "MemoryEntry":
        return cls(
            content=data["content"],
            type=data["type"],
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            confidence=data.get("confidence", 1.0),
            source_count=data.get("source_count", 1),
            decay_days=data.get("decay_days"),
            is_explicit=data.get("is_explicit", False),
        )


# =============================================================================
# MEMORY STORE
# =============================================================================

@dataclass
class MemoryStore:
    """
    Persistent memory storage.
    
    Stores user knowledge, feedback, and context separately.
    Each type is a list of entries that can be queried and updated.
    """
    
    base_path: Path = field(default_factory=get_human_dir)
    _entries: dict[MemoryType, list[MemoryEntry]] = field(default_factory=dict)
    _loaded: bool = False
    
    @property
    def memory_path(self) -> Path:
        return self.base_path / "memory"
    
    def _ensure_dir(self) -> None:
        """Ensure memory directory exists."""
        self.memory_path.mkdir(parents=True, exist_ok=True)
    
    def _file_path(self, memory_type: MemoryType) -> Path:
        """Get file path for a memory type."""
        return self.memory_path / f"{memory_type}.json"
    
    def load(self) -> None:
        """Load all memory from disk."""
        self._ensure_dir()
        self._entries = {"user": [], "feedback": [], "context": []}
        
        for memory_type in ["user", "feedback", "context"]:
            path = self._file_path(memory_type)
            if path.exists():
                try:
                    with open(path) as f:
                        data = json.load(f)
                    entries = []
                    for e in data.get("entries", []):
                        try:
                            entries.append(MemoryEntry.from_dict(e))
                        except (KeyError, ValueError, TypeError) as err:
                            print(f"[memory] skipping invalid entry in {memory_type}: {err}")
                    self._entries[memory_type] = entries
                except json.JSONDecodeError as err:
                    print(f"[memory] could not parse {memory_type}.json: {err}")
                    # Do NOT overwrite self._entries — leave previous value (empty list from init)
        
        self._loaded = True
    
    def save(self, memory_type: MemoryType | None = None) -> None:
        """Save memory to disk."""
        self._ensure_dir()
        
        types_to_save = [memory_type] if memory_type else ["user", "feedback", "context"]
        
        for mt in types_to_save:
            path = self._file_path(mt)
            data = {
                "type": mt,
                "updated_at": datetime.now().isoformat(),
                "entries": [e.to_dict() for e in self._entries.get(mt, [])]
            }
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
    
    def _ensure_loaded(self) -> None:
        """Ensure memory is loaded."""
        if not self._loaded:
            self.load()
    
    def get(self, memory_type: MemoryType, include_expired: bool = False) -> list[MemoryEntry]:
        """Get all entries of a type."""
        self._ensure_loaded()
        entries = self._entries.get(memory_type, [])
        if include_expired:
            return entries
        return [e for e in entries if not e.is_expired]
    
    def get_all(self, include_expired: bool = False) -> dict[MemoryType, list[MemoryEntry]]:
        """Get all memory entries."""
        self._ensure_loaded()
        if include_expired:
            return self._entries.copy()
        return {
            mt: [e for e in entries if not e.is_expired]
            for mt, entries in self._entries.items()
        }
    
    def add(
        self,
        content: str,
        memory_type: MemoryType,
        confidence: float = 1.0,
        decay_days: int | None = None,
        is_explicit: bool = False,
    ) -> MemoryEntry:
        """
        Add a new memory entry.
        
        Args:
            content: The memory content
            memory_type: user/feedback/context
            confidence: 0-1 confidence score
            decay_days: Days until expiry (None = permanent)
            is_explicit: True if user explicitly marked with "!"
        """
        self._ensure_loaded()
        
        # Default decay for context type — configurable via human.memory_context_decay_days
        if memory_type == "context" and decay_days is None and not is_explicit:
            try:
                from outheis.core.config import load_config
                decay_days = load_config().human.memory_context_decay_days
            except Exception:
                decay_days = 14
        
        entry = MemoryEntry(
            content=content,
            type=memory_type,
            confidence=confidence,
            decay_days=decay_days,
            is_explicit=is_explicit,
        )
        
        if memory_type not in self._entries:
            self._entries[memory_type] = []
        
        self._entries[memory_type].append(entry)
        self.save(memory_type)
        
        return entry
    
    def cleanup_expired(self) -> int:
        """Remove expired entries. Returns count of removed entries."""
        self._ensure_loaded()
        count = 0
        for memory_type in ["user", "feedback", "context"]:
            before = len(self._entries.get(memory_type, []))
            self._entries[memory_type] = [
                e for e in self._entries.get(memory_type, [])
                if not e.is_expired
            ]
            removed = before - len(self._entries[memory_type])
            if removed > 0:
                count += removed
                self.save(memory_type)
        return count
    
    def update(self, memory_type: MemoryType, index: int, content: str) -> MemoryEntry | None:
        """Update an existing memory entry."""
        self._ensure_loaded()
        
        entries = self._entries.get(memory_type, [])
        if 0 <= index < len(entries):
            entries[index].content = content
            entries[index].updated_at = datetime.now()
            entries[index].source_count += 1
            self.save(memory_type)
            return entries[index]
        
        return None
    
    def remove(self, memory_type: MemoryType, index: int) -> bool:
        """Remove a memory entry."""
        self._ensure_loaded()
        
        entries = self._entries.get(memory_type, [])
        if 0 <= index < len(entries):
            entries.pop(index)
            self.save(memory_type)
            return True
        
        return False
    
    def clear(self, memory_type: MemoryType) -> None:
        """Clear all entries of a type."""
        self._ensure_loaded()
        self._entries[memory_type] = []
        self.save(memory_type)
    
    def to_prompt_context(self) -> str:
        """
        Generate context string for agent prompts.
        
        Returns a formatted string summarizing all memory
        that agents can include in their system prompts.
        """
        self._ensure_loaded()
        
        sections = []
        
        # User info
        user_entries = self._entries.get("user", [])
        if user_entries:
            user_lines = [f"- {e.content}" for e in user_entries]
            sections.append(f"## About the user\n" + "\n".join(user_lines))
        
        # Feedback/preferences
        feedback_entries = self._entries.get("feedback", [])
        if feedback_entries:
            feedback_lines = [f"- {e.content}" for e in feedback_entries]
            sections.append(f"## Working preferences\n" + "\n".join(feedback_lines))
        
        # Current context
        context_entries = self._entries.get("context", [])
        if context_entries:
            context_lines = [f"- {e.content}" for e in context_entries]
            sections.append(f"## Current context\n" + "\n".join(context_lines))
        
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
    
    # Check for "!" prefix (must be followed by space and actual content)
    if not text.startswith("!") or len(text) < 3:
        return None, None, text
    
    # Remove the "!" and get content
    content = text[1:].strip()
    
    # Must have actual content after "!"
    if not content or content.startswith("!"):
        return None, None, text
    
    # Classify the memory type based on content
    content_lower = content.lower()
    
    # Feedback indicators (how to work)
    feedback_keywords = [
        "prefer", "please", "always", "never", "response", "format", "style",
        "short", "long", "formal", "casual",
    ]
    
    # Context indicators (current work)
    context_keywords = [
        "working", "project", "currently", "focus", "deadline", "this week",
    ]
    
    # Check for feedback
    if any(kw in content_lower for kw in feedback_keywords):
        return content, "feedback", ""
    
    # Check for context
    if any(kw in content_lower for kw in context_keywords):
        return content, "context", ""
    
    # Default to user info
    return content, "user", ""


def handle_explicit_memory(text: str) -> tuple[bool, str, MemoryType | None]:
    """
    Process explicit memory marker and store if found.
    
    Returns:
        (was_memory_command, content, memory_type)
        - was_memory_command: True if "!" prefix was found and processed
        - content: The stored content (without "!" prefix)
        - memory_type: user/feedback/context or None
    """
    content, memory_type, remaining = parse_explicit_memory(text)
    
    if content and memory_type:
        store = get_memory_store()
        store.add(content, memory_type, confidence=1.0, is_explicit=True)
        return True, content, memory_type
    
    return False, text, None

