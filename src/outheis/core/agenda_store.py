"""
agenda_store — shared read/write utilities for agenda.json.

Single source of truth: ~/.outheis/human/webui/pages/agenda.json

Used by:
  - data.py  (zeno)  — writes items from vault scans, source=filepath
  - agenda.py (cato) — reads items as context; writes source="cato" items
  - server.py        — PUT /api/agenda-item writes source="webui"
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Path
# ---------------------------------------------------------------------------

def _agenda_json_path() -> Path:
    from outheis.core.config import get_human_dir
    return get_human_dir() / "webui" / "pages" / "agenda.json"


# ---------------------------------------------------------------------------
# Default structure
# ---------------------------------------------------------------------------

_DEFAULT_FACETS = [
    {"id": "cato", "label": "Arbeit",   "hex": "#FF2E00"},
    {"id": "hiro", "label": "senswork", "hex": "#FFB400"},
    {"id": "rumi", "label": "Self",     "hex": "#460A46"},
    {"id": "zeno", "label": "OFC",      "hex": "#97EAD2"},
    {"id": "ou",   "label": "Privat",   "hex": "#218380"},
    {"id": "misc", "label": "Misc",     "hex": "#7A7676"},
]

_DEFAULT_VIEW: dict[str, Any] = {
    "range": 7,
    "params": {
        "peak_amp": 0.9,
        "decay": 10.0,
        "ghost_pull": 0.04,
        "overlay_alpha": 0.09,
    },
}


def _empty_agenda() -> dict:
    today = date.today().isoformat()
    return {
        "meta": {
            "version": "0.1",
            "generated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "base_date": today,
        },
        "facets": _DEFAULT_FACETS,
        "view": _DEFAULT_VIEW,
        "items": [],
    }


# ---------------------------------------------------------------------------
# Read / write
# ---------------------------------------------------------------------------

def read_agenda_json() -> dict:
    path = _agenda_json_path()
    if not path.exists():
        return _empty_agenda()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _empty_agenda()


def write_agenda_json(data: dict) -> None:
    """Atomic write — update meta timestamps before writing."""
    path = _agenda_json_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data.setdefault("meta", {})
    data["meta"]["generated"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    data["meta"]["base_date"] = date.today().isoformat()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------------------
# Source-keyed item management
# ---------------------------------------------------------------------------

def replace_items_by_source(data: dict, source: str, new_items: list[dict]) -> dict:
    """Replace all items with a given source, preserving all others."""
    kept = [it for it in data.get("items", []) if it.get("source") != source]
    data["items"] = kept + new_items
    return data


def remove_items_by_source(data: dict, source: str) -> dict:
    """Remove all items with a given source."""
    data["items"] = [it for it in data.get("items", []) if it.get("source") != source]
    return data


# ---------------------------------------------------------------------------
# ID generation
# ---------------------------------------------------------------------------

def new_id() -> str:
    from outheis.core.snowflake import generate_str
    return generate_str()


# ---------------------------------------------------------------------------
# Day offset helpers
# ---------------------------------------------------------------------------

def day_offset(date_str: str) -> int | None:
    """Days from today for a 'YYYY-MM-DD' string. Negative = past."""
    try:
        return (date.fromisoformat(date_str) - date.today()).days
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Tag format → items  (Shadow two-line format)
# ---------------------------------------------------------------------------

_DATE_RE      = re.compile(r"#date-(\d{4}-\d{2}-\d{2})")
_TIME_RE      = re.compile(r"#time-(\d{2}:\d{2})-(\d{2}:\d{2})")
_FACET_RE     = re.compile(r"#facet-(\w+)")
_ID_RE        = re.compile(r"#id-([0-9a-zA-Z]+)")
_DENSITY_RE   = re.compile(r"#density-(high|low)")
_SIZE_RE      = re.compile(r"#size-(s|m|l)")
_DONE_RE      = re.compile(r"#done-(\d{4}-\d{2}-\d{2})")


def parse_tag_entries_to_items(text: str, source: str) -> list[dict]:
    """
    Parse Shadow-format two-line tag entries into agenda.json item dicts.

    Each entry:
        #date-YYYY-MM-DD [#time-HH:MM-HH:MM] [#facet-X] [#id-XXX] ...
        Plain text description

    Blank lines separate entries. Done items (#done-*) are skipped.
    """
    items: list[dict] = []
    for entry in re.split(r"\n\s*\n", text.strip()):
        lines = [l for l in entry.strip().splitlines() if l.strip()]
        if len(lines) < 2:
            continue
        tag_line, title = lines[0].strip(), lines[1].strip()
        if not tag_line.startswith("#"):
            continue
        # Skip done items
        if _DONE_RE.search(tag_line):
            continue

        dates   = _DATE_RE.findall(tag_line)
        time_m  = _TIME_RE.search(tag_line)
        facet_m = _FACET_RE.search(tag_line)
        id_m    = _ID_RE.search(tag_line)
        dens_m  = _DENSITY_RE.search(tag_line)
        size_m  = _SIZE_RE.search(tag_line)

        item: dict[str, Any] = {
            "id":     id_m.group(1) if id_m else new_id(),
            "title":  title,
            "facet":  facet_m.group(1) if facet_m else "misc",
            "source": source,
        }

        if dens_m:
            item["density"] = dens_m.group(1)

        if len(dates) == 2 and time_m:
            # Multi-day fixed
            item["type"]  = "fixed"
            item["start"] = f"{dates[0]}T{time_m.group(1)}"
            item["end"]   = f"{dates[1]}T{time_m.group(2)}"
        elif len(dates) >= 1 and time_m:
            # Single-day fixed
            item["type"]  = "fixed"
            item["day"]   = day_offset(dates[0])
            item["start"] = time_m.group(1)
            item["end"]   = time_m.group(2)
        elif len(dates) >= 1:
            # Volatile with date
            item["type"] = "volatile"
            item["day"]  = day_offset(dates[0])
            item["size"] = size_m.group(1) if size_m else "m"
        else:
            # Undated volatile (#action-required etc.)
            item["type"] = "volatile"
            item["day"]  = None
            item["size"] = size_m.group(1) if size_m else "m"

        items.append(item)

    return items


# ---------------------------------------------------------------------------
# Items → Shadow tag text  (for LLM context in agenda.py)
# ---------------------------------------------------------------------------

def items_to_shadow_text(items: list[dict]) -> str:
    """
    Convert agenda.json items to Shadow-format two-line tag text.

    Includes #id- so cato can write items back and merge() can match by ID.
    Groups items by source with <!-- BEGIN/END --> markers (like Shadow.md).
    """
    from collections import defaultdict
    today = date.today()

    groups: dict[str, list[dict]] = defaultdict(list)
    for it in items:
        groups[it.get("source", "misc")].append(it)

    parts: list[str] = [
        "# agenda.json — Vault Chronological Index",
        f"*{today.isoformat()}*",
        "",
    ]

    for source in sorted(groups):
        parts.append(f"<!-- BEGIN: {source} -->")
        parts.append(f"## {source}")
        for it in groups[source]:
            tag_parts = [f"#id-{it['id']}"]

            # Date / time tags
            start = it.get("start", "")
            end   = it.get("end", "")
            d     = it.get("day")

            if start and "T" in start:
                # Multi-day
                start_date = start.split("T")[0]
                end_date   = end.split("T")[0] if end else start_date
                start_time = start.split("T")[1]
                end_time   = end.split("T")[1] if end and "T" in end else "23:59"
                tag_parts.append(f"#date-{start_date}")
                tag_parts.append(f"#date-{end_date}")
                tag_parts.append(f"#time-{start_time}-{end_time}")
            elif start and d is not None:
                target = today.__class__.fromordinal(today.toordinal() + d)
                tag_parts.append(f"#date-{target.isoformat()}")
                tag_parts.append(f"#time-{start}-{end}")
            elif d is not None:
                target = today.__class__.fromordinal(today.toordinal() + d)
                tag_parts.append(f"#date-{target.isoformat()}")
            else:
                tag_parts.append("#action-required")

            facet = it.get("facet", "misc")
            if facet != "misc":
                tag_parts.append(f"#facet-{facet}")

            if it.get("density"):
                tag_parts.append(f"#density-{it['density']}")
            if it.get("size") and it["size"] != "m":
                tag_parts.append(f"#size-{it['size']}")
            if it.get("done"):
                tag_parts.append(f"#done-{it['done']}")

            parts.append(" ".join(tag_parts))
            parts.append(it.get("title", "(untitled)"))
            parts.append("")

        parts.append(f"<!-- END: {source} -->")
        parts.append("")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Merge — used by cato's write_file(file='shadow', content=...)
# ---------------------------------------------------------------------------

def merge_shadow_write(data: dict, tag_text: str, default_source: str = "cato") -> dict:
    """
    Merge a Shadow-format write (from cato) back into agenda.json.

    Rules:
    - Items with #id-: update the matching item in data, preserve its source.
      If #done-YYYY-MM-DD is present: set done= on the item.
    - Items without #id-: new item, source=default_source.
    - Items in data with source=default_source that are NOT in tag_text:
      removed (LLM intentionally dropped them).
    - Items with other sources: never removed by this operation.
    """
    parsed = _parse_tag_entries_with_done(tag_text, default_source)

    seen_ids: set[str] = set()
    done_ids: dict[str, str] = {}  # id → done-date

    # First pass: collect IDs from written content
    for p in parsed:
        if p.get("id"):
            seen_ids.add(p["id"])
        if p.get("_done_date") and p.get("id"):
            done_ids[p["id"]] = p["_done_date"]

    existing_by_id: dict[str, dict] = {
        it["id"]: it for it in data.get("items", []) if "id" in it
    }

    result: list[dict] = []

    # Keep all items not owned by default_source, apply done-marks
    for it in data.get("items", []):
        item_id = it.get("id", "")
        if it.get("source") != default_source:
            if item_id in done_ids:
                it = dict(it)
                it["done"] = done_ids[item_id]
            result.append(it)
        else:
            # default_source items: keep only if seen in tag_text
            if item_id in seen_ids:
                result.append(it)  # will be updated below

    # Update / add items from parsed content
    result_by_id = {it.get("id"): i for i, it in enumerate(result)}

    for p in parsed:
        if p.get("_done_date"):
            continue  # done items are handled above, not re-added
        item_id = p.get("id", "")
        if item_id in result_by_id:
            # Update in place, preserve source
            idx = result_by_id[item_id]
            orig = result[idx]
            updated = {**orig, **{k: v for k, v in p.items() if not k.startswith("_")}}
            updated["source"] = orig.get("source", default_source)
            result[idx] = updated
        else:
            # New item
            clean = {k: v for k, v in p.items() if not k.startswith("_")}
            result.append(clean)

    data["items"] = result
    return data


def _parse_tag_entries_with_done(text: str, default_source: str) -> list[dict]:
    """
    Like parse_tag_entries_to_items but also returns done items with _done_date set.
    """
    items: list[dict] = []
    for entry in re.split(r"\n\s*\n", text.strip()):
        lines = [l for l in entry.strip().splitlines() if l.strip()]
        if len(lines) < 2:
            continue
        tag_line, title = lines[0].strip(), lines[1].strip()
        if not tag_line.startswith("#"):
            continue

        dates   = _DATE_RE.findall(tag_line)
        time_m  = _TIME_RE.search(tag_line)
        facet_m = _FACET_RE.search(tag_line)
        id_m    = _ID_RE.search(tag_line)
        dens_m  = _DENSITY_RE.search(tag_line)
        size_m  = _SIZE_RE.search(tag_line)
        done_m  = _DONE_RE.search(tag_line)

        item: dict[str, Any] = {
            "id":     id_m.group(1) if id_m else new_id(),
            "title":  title,
            "facet":  facet_m.group(1) if facet_m else "misc",
            "source": default_source,
        }

        if done_m:
            item["_done_date"] = done_m.group(1)
            # Strip done dates from the dates list for position calc
            dates_no_done = dates  # #done- is not a #date-, so dates is unaffected

        if dens_m:
            item["density"] = dens_m.group(1)

        if len(dates) == 2 and time_m:
            item["type"]  = "fixed"
            item["start"] = f"{dates[0]}T{time_m.group(1)}"
            item["end"]   = f"{dates[1]}T{time_m.group(2)}"
        elif len(dates) >= 1 and time_m:
            item["type"]  = "fixed"
            item["day"]   = day_offset(dates[0])
            item["start"] = time_m.group(1)
            item["end"]   = time_m.group(2)
        elif len(dates) >= 1:
            item["type"] = "volatile"
            item["day"]  = day_offset(dates[0])
            item["size"] = size_m.group(1) if size_m else "m"
        else:
            item["type"] = "volatile"
            item["day"]  = None
            item["size"] = size_m.group(1) if size_m else "m"

        items.append(item)

    return items


# ---------------------------------------------------------------------------
# Retention cleanup
# ---------------------------------------------------------------------------

def prune_done_items(data: dict, retention_days: int) -> int:
    """
    Remove items where done= date is older than retention_days.
    Returns count of pruned items.
    """
    from datetime import timedelta
    cutoff = date.today() - timedelta(days=retention_days)
    before = len(data.get("items", []))
    data["items"] = [
        it for it in data.get("items", [])
        if not (it.get("done") and _parse_date(it["done"]) < cutoff)
    ]
    return before - len(data["items"])


def _parse_date(s: str) -> date:
    try:
        return date.fromisoformat(s)
    except (ValueError, TypeError):
        return date.max
