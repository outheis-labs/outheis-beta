"""
Search index for vault content.

Maintains a JSONL index of vault files for fast search.
Index is rebuilt on demand or when files change.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from outheis.core.vault import VaultFile, iter_vault_files


# =============================================================================
# INDEX ENTRY
# =============================================================================

@dataclass
class IndexEntry:
    """A single entry in the search index."""
    path: str  # Relative to vault root
    title: str
    tags: list[str]
    content_hash: str  # MD5 of content for change detection
    indexed_at: str  # ISO timestamp

    # Searchable text (title + tags + first N chars of body)
    searchable: str = ""

    # Access tracking for relevance ranking
    modified_at: str = ""  # File modification time (ISO)
    access_count: int = 0  # How often accessed via search
    last_accessed: str = ""  # Last access time (ISO)

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "title": self.title,
            "tags": self.tags,
            "content_hash": self.content_hash,
            "indexed_at": self.indexed_at,
            "searchable": self.searchable,
            "modified_at": self.modified_at,
            "access_count": self.access_count,
            "last_accessed": self.last_accessed,
        }

    @classmethod
    def from_dict(cls, data: dict) -> IndexEntry:
        return cls(
            path=data["path"],
            title=data["title"],
            tags=data.get("tags", []),
            content_hash=data["content_hash"],
            indexed_at=data["indexed_at"],
            searchable=data.get("searchable", ""),
            modified_at=data.get("modified_at", ""),
            access_count=data.get("access_count", 0),
            last_accessed=data.get("last_accessed", ""),
        )

    @classmethod
    def from_vault_file(cls, vf: VaultFile, vault_root: Path) -> IndexEntry:
        """Create index entry from vault file."""
        content_hash = hashlib.md5(vf.content.encode()).hexdigest()

        try:
            rel_path = str(vf.path.relative_to(vault_root))
        except ValueError:
            rel_path = str(vf.path)

        # Get file modification time
        try:
            mtime = vf.path.stat().st_mtime
            modified_at = datetime.fromtimestamp(mtime, timezone.utc).isoformat()
        except OSError:
            modified_at = ""

        # Build searchable text: path + title + tags + first 500 chars of body
        body_preview = vf.body[:500].replace("\n", " ").strip()
        searchable = f"{rel_path} {vf.title} {' '.join(vf.tags)} {body_preview}".lower()

        return cls(
            path=rel_path,
            title=vf.title,
            tags=vf.tags,
            content_hash=content_hash,
            indexed_at=datetime.now(timezone.utc).isoformat(),
            searchable=searchable,
            modified_at=modified_at,
            access_count=0,
            last_accessed="",
        )


# =============================================================================
# SEARCH INDEX
# =============================================================================

@dataclass
class SearchIndex:
    """
    In-memory search index backed by JSONL file.

    Supports incremental updates: only reindex changed files.
    """
    vault_root: Path
    index_path: Path
    entries: dict[str, IndexEntry] = field(default_factory=dict)  # path -> entry

    def load(self) -> None:
        """Load index from disk."""
        self.entries.clear()

        if not self.index_path.exists():
            return

        with open(self.index_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    entry = IndexEntry.from_dict(data)
                    self.entries[entry.path] = entry
                except (json.JSONDecodeError, KeyError):
                    continue

    def save(self) -> None:
        """Save index to disk."""
        self.index_path.parent.mkdir(parents=True, exist_ok=True)

        with open(self.index_path, "w", encoding="utf-8") as f:
            for entry in self.entries.values():
                f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")

    def rebuild(self) -> int:
        """
        Full rebuild of index from vault.

        Returns number of files indexed.
        """
        self.entries.clear()

        for vf in iter_vault_files(self.vault_root):
            entry = IndexEntry.from_vault_file(vf, self.vault_root)
            self.entries[entry.path] = entry

        self.save()
        return len(self.entries)

    def update(self) -> tuple[int, int, int]:
        """
        Incremental update: only reindex changed files.

        Returns (added, updated, removed) counts.
        """
        added = 0
        updated = 0
        removed = 0

        # Get current files
        current_files: dict[str, VaultFile] = {}
        for vf in iter_vault_files(self.vault_root):
            try:
                rel_path = str(vf.path.relative_to(self.vault_root))
            except ValueError:
                rel_path = str(vf.path)
            current_files[rel_path] = vf

        # Remove entries for deleted files
        for path in list(self.entries.keys()):
            if path not in current_files:
                del self.entries[path]
                removed += 1

        # Add/update entries, preserving access stats
        for path, vf in current_files.items():
            content_hash = hashlib.md5(vf.content.encode()).hexdigest()

            existing = self.entries.get(path)
            if existing is None:
                # New file
                self.entries[path] = IndexEntry.from_vault_file(vf, self.vault_root)
                added += 1
            elif existing.content_hash != content_hash:
                # Changed file — preserve access stats
                new_entry = IndexEntry.from_vault_file(vf, self.vault_root)
                new_entry.access_count = existing.access_count
                new_entry.last_accessed = existing.last_accessed
                self.entries[path] = new_entry
                updated += 1

        self.save()
        return added, updated, removed

    def search(self, query: str, limit: int = 10, track_access: bool = True) -> list[IndexEntry]:
        """
        Search index for matching entries.

        Ranking combines:
        - Term matches (primary)
        - Recency (file modification time)
        - Frequency (access count)

        If track_access=True, increments access_count for returned results.
        """
        query_terms = query.lower().split()
        if not query_terms:
            return []

        results: list[tuple[float, IndexEntry]] = []
        now = datetime.now(timezone.utc)

        for entry in self.entries.values():
            # Base score: matching terms
            term_score = sum(1 for term in query_terms if term in entry.searchable)
            if term_score == 0:
                continue

            # Recency bonus (0-1): files modified in last 7 days get boost
            recency_score = 0.0
            if entry.modified_at:
                try:
                    modified = datetime.fromisoformat(entry.modified_at.replace('Z', '+00:00'))
                    days_old = (now - modified).days
                    if days_old < 7:
                        recency_score = 1.0 - (days_old / 7)
                except (ValueError, TypeError):
                    pass

            # Frequency bonus (0-1): based on access count, capped
            frequency_score = min(entry.access_count / 10, 1.0)

            # Combined score: terms are primary, recency/frequency are secondary
            # Term matches: weight 10, Recency: weight 2, Frequency: weight 1
            combined_score = (term_score * 10) + (recency_score * 2) + (frequency_score * 1)

            results.append((combined_score, entry))

        # Sort by combined score descending
        results.sort(key=lambda x: -x[0])

        # Get top results
        top_entries = [entry for _, entry in results[:limit]]

        # Track access
        if track_access and top_entries:
            for entry in top_entries:
                entry.access_count += 1
                entry.last_accessed = now.isoformat()
            self.save()

        return top_entries

    def record_access(self, path: str) -> None:
        """Record that a file was accessed (e.g., opened, read)."""
        if path in self.entries:
            self.entries[path].access_count += 1
            self.entries[path].last_accessed = datetime.now(timezone.utc).isoformat()
            self.save()

    def search_by_tag(self, tag: str) -> list[IndexEntry]:
        """Find all entries with a specific tag."""
        tag_lower = tag.lower()
        return [
            entry for entry in self.entries.values()
            if any(t.lower() == tag_lower for t in entry.tags)
        ]

    def get_all_tags(self) -> dict[str, int]:
        """Get all tags with their counts."""
        tag_counts: dict[str, int] = {}
        for entry in self.entries.values():
            for tag in entry.tags:
                tag_lower = tag.lower()
                tag_counts[tag_lower] = tag_counts.get(tag_lower, 0) + 1
        return tag_counts

    def get_tag_analysis(self) -> dict:
        """
        Analyze tag usage patterns.

        Returns:
            - all_tags: {tag: count}
            - singular_tags: tags used only once (candidates for removal)
            - prefixes: {prefix: [tags]} for hierarchical tags
            - suggestions: potential new tags based on patterns
        """
        all_tags = self.get_all_tags()

        # Singular tags (used only once)
        singular = [tag for tag, count in all_tags.items() if count == 1]

        # Analyze prefixes (tags with - or / separator)
        prefixes: dict[str, list[str]] = {}
        for tag in all_tags:
            if '-' in tag:
                prefix = tag.split('-')[0]
                if prefix not in prefixes:
                    prefixes[prefix] = []
                prefixes[prefix].append(tag)
            elif '/' in tag:
                prefix = tag.split('/')[0]
                if prefix not in prefixes:
                    prefixes[prefix] = []
                prefixes[prefix].append(tag)

        # Only keep prefixes with multiple tags (actual hierarchies)
        prefixes = {k: v for k, v in prefixes.items() if len(v) > 1}

        return {
            "all_tags": all_tags,
            "singular_tags": singular,
            "prefixes": prefixes,
            "total_unique": len(all_tags),
            "total_singular": len(singular),
        }

    def suggest_tag_cleanup(self) -> list[str]:
        """
        Generate suggestions for tag cleanup.

        Returns list of human-readable suggestions.
        """
        analysis = self.get_tag_analysis()
        suggestions = []

        # Warn about singular tags
        if analysis["singular_tags"]:
            singular = analysis["singular_tags"][:5]
            more = len(analysis["singular_tags"]) - 5
            tag_list = ", ".join(f"#{t}" for t in singular)
            if more > 0:
                suggestions.append(f"Singular tags (used only once): {tag_list} (+{more} more)")
            else:
                suggestions.append(f"Singular tags (used only once): {tag_list}")

        return suggestions

    def list_path(self, path: str = "") -> dict:
        """
        List contents of a path in the vault.

        Returns:
            {
                "exists": bool,
                "is_dir": bool,
                "files": [str],      # If directory
                "dirs": [str],       # If directory  
                "content": str,      # If file
            }
        """
        target = self.vault_root / path if path else self.vault_root

        if not target.exists():
            return {"exists": False}

        if target.is_file():
            return {
                "exists": True,
                "is_dir": False,
                "path": str(target.relative_to(self.vault_root)),
            }

        # It's a directory
        files = []
        dirs = []

        for item in sorted(target.iterdir()):
            if item.name.startswith("."):
                continue
            rel = str(item.relative_to(self.vault_root))
            if item.is_dir():
                dirs.append(rel)
            else:
                files.append(rel)

        return {
            "exists": True,
            "is_dir": True,
            "path": path or "/",
            "dirs": dirs,
            "files": files,
        }

    def find_by_path(self, pattern: str) -> list[IndexEntry]:
        """Find entries where path contains pattern."""
        pattern_lower = pattern.lower()
        return [
            entry for entry in self.entries.values()
            if pattern_lower in entry.path.lower()
        ]


# =============================================================================
# FACTORY
# =============================================================================

def get_index_cache_dir() -> Path:
    """Get cache directory for search indices."""
    from outheis.core.config import get_human_dir
    cache_dir = get_human_dir() / "cache" / "index"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def create_index(vault_root: Path, index_path: Path | None = None) -> SearchIndex:
    """Create a search index for a vault."""
    if index_path is None:
        # Store index in cache, not in vault
        # Use vault name as filename to support multiple vaults
        vault_name = vault_root.name or "vault"
        index_path = get_index_cache_dir() / f"{vault_name}.jsonl"

    index = SearchIndex(vault_root=vault_root, index_path=index_path)
    index.load()
    return index
