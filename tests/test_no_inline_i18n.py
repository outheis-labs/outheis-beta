"""
Enforce that source files contain no inline non-English letter characters.

Rule: Unicode letters outside the ASCII range (umlauts, accented letters,
non-Latin scripts, etc.) must live exclusively in
  src/outheis/core/i18n.py

All other source files must use English-only identifiers and string
literals.  Non-letter Unicode (arrows →, bullets •, em-dashes —, emoji
🧘) are intentional UI/log elements and are NOT flagged by this test.

Exclusions:
  - src/outheis/core/i18n.py  — designated home for translated strings
  - tests/fixtures/            — fixture files may contain user data in any language
  - __pycache__/               — byte-compiled artefacts
"""

import unicodedata
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
_SRC_ROOT = _REPO_ROOT / "src"
_TESTS_ROOT = _REPO_ROOT / "tests"
_I18N_FILE = _SRC_ROOT / "outheis" / "core" / "i18n.py"
# Holiday names are locale-specific data, not translatable UI strings
_HOLIDAYS_FILE = _SRC_ROOT / "outheis" / "core" / "holidays" / "_builtin.py"


def _has_non_ascii_letter(line: str) -> bool:
    """Return True if `line` contains a Unicode letter outside ASCII (a-z A-Z)."""
    for ch in line:
        if ord(ch) > 127 and unicodedata.category(ch).startswith("L"):
            return True
    return False


def _collect_violations() -> list[tuple[Path, int, str]]:
    violations: list[tuple[Path, int, str]] = []

    def _scan(root: Path, exclude_dirs: set[str]) -> None:
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix not in {".py", ".md"}:
                continue
            if path == _I18N_FILE or path == _HOLIDAYS_FILE:
                continue
            parts = path.relative_to(root).parts
            if any(p in exclude_dirs for p in parts):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                if "# noqa: i18n" in line:
                    continue
                if _has_non_ascii_letter(line):
                    violations.append((path.relative_to(_REPO_ROOT), lineno, line.rstrip()))

    _scan(_SRC_ROOT, exclude_dirs={"__pycache__"})
    _scan(_TESTS_ROOT, exclude_dirs={"__pycache__", "fixtures"})
    return violations


def test_no_inline_non_english_letters_outside_i18n() -> None:
    """Non-English letter characters in source files must live in i18n.py."""
    violations = _collect_violations()
    if not violations:
        return
    lines = "\n".join(
        f"  {path}:{lineno}: {line}" for path, lineno, line in violations[:30]
    )
    suffix = f"\n  ... and {len(violations) - 30} more" if len(violations) > 30 else ""
    raise AssertionError(
        f"Non-English letters found in {len(violations)} source line(s) outside i18n.py.\n"
        f"Move these strings to src/outheis/core/i18n.py:\n{lines}{suffix}"
    )
