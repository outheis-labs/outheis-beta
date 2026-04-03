"""
Vault reader.

Reads markdown files with optional YAML frontmatter.
Extracts inline #tags from body text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# =============================================================================
# FRONTMATTER PARSING
# =============================================================================

FRONTMATTER_PATTERN = re.compile(
    r"^---\s*\n(.*?)\n---\s*\n",
    re.DOTALL,
)

# Inline tag pattern: #word, #word-word, #word/word, #word-YYYY-MM-DD
# Must start with # followed by word chars, can contain - or /
INLINE_TAG_PATTERN = re.compile(
    r'#([a-zA-Z][a-zA-Z0-9_]*(?:[-/][a-zA-Z0-9_]+)*)',
)


@dataclass
class VaultFile:
    """A file from the vault with parsed frontmatter."""
    path: Path
    content: str
    frontmatter: dict[str, Any] = field(default_factory=dict)

    @property
    def title(self) -> str:
        """Get title from frontmatter or filename."""
        if "title" in self.frontmatter:
            return self.frontmatter["title"]
        return self.path.stem

    @property
    def tags(self) -> list[str]:
        """
        Get tags from frontmatter AND inline #tags in body.
        
        Supports formats:
        - #tag
        - #level-sublevel (e.g. #status-active)
        - #level/sublevel (e.g. #date/today)
        - #date-YYYY-MM-DD
        
        Returns deduplicated list, preserving order of first occurrence.
        """
        all_tags = []
        seen = set()
        
        # 1. Frontmatter tags (if any)
        fm_tags = self.frontmatter.get("tags", [])
        if isinstance(fm_tags, str):
            fm_tags = [fm_tags]
        for tag in (fm_tags or []):
            tag_lower = tag.lower()
            if tag_lower not in seen:
                seen.add(tag_lower)
                all_tags.append(tag)
        
        # 2. Inline tags from body
        body = self.body
        for match in INLINE_TAG_PATTERN.finditer(body):
            tag = match.group(1)
            tag_lower = tag.lower()
            if tag_lower not in seen:
                seen.add(tag_lower)
                all_tags.append(tag)
        
        return all_tags

    @property
    def body(self) -> str:
        """Get content without frontmatter."""
        match = FRONTMATTER_PATTERN.match(self.content)
        if match:
            return self.content[match.end():]
        return self.content


def extract_inline_tags(text: str) -> list[str]:
    """
    Extract inline #tags from text.
    
    Utility function for parsing tags from any text.
    """
    tags = []
    seen = set()
    for match in INLINE_TAG_PATTERN.finditer(text):
        tag = match.group(1)
        tag_lower = tag.lower()
        if tag_lower not in seen:
            seen.add(tag_lower)
            tags.append(tag)
    return tags


def read_file(path: Path) -> VaultFile:
    """Read a vault file with frontmatter parsing."""
    content = path.read_text(encoding="utf-8")
    frontmatter = {}

    match = FRONTMATTER_PATTERN.match(content)
    if match:
        try:
            frontmatter = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError:
            pass

    return VaultFile(
        path=path,
        content=content,
        frontmatter=frontmatter,
    )


# =============================================================================
# VAULT TRAVERSAL
# =============================================================================

def iter_vault_files(
    vault_path: Path,
    extensions: tuple[str, ...] = (".md",),
) -> list[VaultFile]:
    """
    Iterate over all files in a vault.

    Respects conventions:
    - Ignores hidden files/directories (except .git)
    - Only includes specified extensions
    """
    files = []

    for path in vault_path.rglob("*"):
        # Skip hidden files/directories
        if any(part.startswith(".") and part != ".git" for part in path.parts):
            continue

        # Skip non-files
        if not path.is_file():
            continue

        # Skip wrong extensions
        if path.suffix.lower() not in extensions:
            continue

        try:
            files.append(read_file(path))
        except Exception:
            # Skip unreadable files
            continue

    return files


def find_by_tag(
    vault_path: Path,
    tag: str,
) -> list[VaultFile]:
    """Find all files with a specific tag."""
    tag_lower = tag.lower()
    results = []

    for vf in iter_vault_files(vault_path):
        if any(t.lower() == tag_lower for t in vf.tags):
            results.append(vf)

    return results


def find_by_title(
    vault_path: Path,
    query: str,
) -> list[VaultFile]:
    """Find files by title (case-insensitive substring match)."""
    query_lower = query.lower()
    results = []

    for vf in iter_vault_files(vault_path):
        if query_lower in vf.title.lower():
            results.append(vf)

    return results


def search_content(
    vault_path: Path,
    query: str,
) -> list[VaultFile]:
    """Search file contents (case-insensitive)."""
    query_lower = query.lower()
    results = []

    for vf in iter_vault_files(vault_path):
        if query_lower in vf.content.lower():
            results.append(vf)

    return results
