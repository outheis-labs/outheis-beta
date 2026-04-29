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

def _build_facets(items: list[dict], existing: list[dict] | None = None) -> list[dict]:
    """Merge existing facet definitions (from agenda.json) with any new IDs found in items.

    Facets are defined exclusively in agenda.json. Existing entries take precedence.
    Unknown IDs that appear in items get a grey fallback. 'none' is always present.
    """
    seen: dict[str, dict] = {f["id"]: f for f in (existing or [])}
    for it in items:
        fid = it.get("facet") or "none"
        if fid == "none":
            # also check tags for #facet-X
            for tag in (it.get("tags") or []):
                m = re.match(r"^#facet-(\w+)$", tag)
                if m:
                    fid = m.group(1)
                    break
        if fid not in seen:
            seen[fid] = {"id": fid, "label": fid, "hex": "#7A7676"}
    if "none" not in seen:
        seen["none"] = {"id": "none", "label": "", "hex": "#7A7676"}
    return list(seen.values())

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
    return {
        "meta": {
            "version": "0.2",
            "generated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "facets": _build_facets([]),
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
    """Atomic write — update meta timestamps before writing.

    If base_date changes (e.g. day boundary), all relative `day` offsets are
    recalculated so items keep pointing to the same absolute dates.
    """
    import sys
    import traceback as _tb
    n = len(data.get("items", []))
    caller = "".join(_tb.format_stack()[:-1])
    print(f"[agenda_store] write_agenda_json: {n} items\n{caller}", file=sys.stderr, flush=True)

    path = _agenda_json_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data.setdefault("meta", {})
    data["meta"]["generated"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    data["meta"].pop("base_date", None)
    data["facets"] = _build_facets(data.get("items", []), data.get("facets", []))
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------------------
# Source-keyed item management
# ---------------------------------------------------------------------------

def replace_items_by_source(data: dict, source: str, new_items: list[dict]) -> dict:
    """Replace all items with a given source, preserving all others.

    Items carrying a #recurring-* tag are NEVER replaced regardless of source —
    the recurring tag is the authoritative protection flag.  Incoming new_items
    that match a protected recurring item by title are silently dropped.
    """
    # Build a lookup of recurring items keyed by normalized title
    recurring_by_title: dict[str, dict] = {}
    for it in data.get("items", []):
        if any(t.startswith("#recurring-") for t in (it.get("tags") or [])):
            recurring_by_title[_norm_title(it.get("title", ""))] = it

    # Filter out new items that would overwrite a recurring item
    merged_new = [
        ni for ni in new_items
        if _norm_title(ni.get("title", "")) not in recurring_by_title
    ]

    # Keep all items that are either: a different source, OR a recurring item of this source
    kept = [
        it for it in data.get("items", [])
        if it.get("source") != source
        or any(t.startswith("#recurring-") for t in (it.get("tags") or []))
    ]
    data["items"] = kept + merged_new
    return data


def _norm_title(title: str) -> str:
    """Lowercase, strip punctuation/whitespace for fuzzy title matching."""
    import unicodedata
    s = unicodedata.normalize("NFC", title).lower().strip()
    return re.sub(r"[\s\-–—_/\\.,;:!?()\"']+", " ", s).strip()


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
# Tag format → items  (two-line format for LLM context)
# ---------------------------------------------------------------------------

_DATE_RE      = re.compile(r"#date-(\d{4}-\d{2}-\d{2})")
_TIME_RE      = re.compile(r"#time-(\d{2}:\d{2})-(\d{2}:\d{2})")
_DURATION_RE  = re.compile(r"#time-(\d{2}:\d{2})(?!-\d)")  # single HH:MM = duration
# Structural tags stripped before extracting extra tags
_STRUCTURAL_RE = re.compile(
    r"#date-\d{4}-\d{2}-\d{2}"
    r"|#time-\d{2}:\d{2}(?:-\d{2}:\d{2})?"
    r"|#facet-\w+"
    r"|#id-[0-9a-zA-Z]+"
    r"|#density-(?:high|low)"
    r"|#size-(?:s|m|l)"
    r"|#done-\d{4}-\d{2}-\d{2}"
    r"|#layer-\d+"
    r"|#source-\w+"
)
_EXTRA_TAG_RE = re.compile(r"#[\w-]+")
_FACET_RE     = re.compile(r"#facet-(\w+)")
_ID_RE        = re.compile(r"#id-([0-9a-zA-Z]+)")
_DENSITY_RE   = re.compile(r"#density-(high|low)")
_SIZE_RE      = re.compile(r"#size-(s|m|l)")
_LAYER_RE     = re.compile(r"#layer-(\d+)")
_DONE_RE      = re.compile(r"#done-(\d{4}-\d{2}-\d{2})")

# Fields present in the old explicit-fields schema (v0.1) that are absent in v0.2
_OLD_SCHEMA_FIELDS = (
    "facet", "type", "day", "start", "end",
    "duration", "density", "size", "done", "layer", "date", "date_end",
)
# Tag prefixes that encode structural item metadata
_STRUCTURAL_PREFIXES = (
    "#date-", "#time-", "#facet-", "#density-", "#size-",
    "#done-", "#layer-", "#id-", "#source-",
)


def parse_tag_entries_to_items(text: str, source: str) -> list[dict]:
    """
    Parse two-line tag entries into agenda.json item dicts.

    Each entry:
        #date-YYYY-MM-DD [#time-HH:MM-HH:MM] [#facet-X] [#id-XXX] ...
        Plain text description

    Time tag variants:
        #time-HH:MM-HH:MM  → start/end times  → type=fixed
        #time-HH:MM         → duration only    → type=volatile, duration="HH:MM"

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
        dur_m   = None if time_m else _DURATION_RE.search(tag_line)
        facet_m = _FACET_RE.search(tag_line)
        id_m    = _ID_RE.search(tag_line)
        dens_m  = _DENSITY_RE.search(tag_line)
        size_m  = _SIZE_RE.search(tag_line)

        item: dict[str, Any] = {
            "id":     id_m.group(1) if id_m else new_id(),
            "title":  title,
            "source": source,
        }

        # Build tags array — structural tags first
        tags: list[str] = []
        if len(dates) == 2 and time_m:
            # Multi-day fixed
            tags.append(f"#date-{dates[0]}")
            tags.append(f"#date-{dates[1]}")
            tags.append(f"#time-{time_m.group(1)}-{time_m.group(2)}")
        elif len(dates) >= 1 and time_m:
            # Single-day fixed
            tags.append(f"#date-{dates[0]}")
            tags.append(f"#time-{time_m.group(1)}-{time_m.group(2)}")
        elif len(dates) >= 1 and dur_m:
            # Volatile with date and duration
            tags.append(f"#date-{dates[0]}")
            tags.append(f"#time-{dur_m.group(1)}")
        elif len(dates) >= 1:
            # Volatile with date only
            tags.append(f"#date-{dates[0]}")
        else:
            # Undated — today
            tags.append(f"#date-{date.today().isoformat()}")

        facet_val = facet_m.group(1) if facet_m else "none"
        if facet_val != "none":
            tags.append(f"#facet-{facet_val}")
        if dens_m:
            tags.append(f"#density-{dens_m.group(1)}")
        if size_m:
            s = size_m.group(1)
            if s != "m":
                tags.append(f"#size-{s}")

        # Extra tags (non-structural)
        extra = _EXTRA_TAG_RE.findall(_STRUCTURAL_RE.sub("", tag_line))
        tags.extend(extra)

        item["tags"] = tags
        items.append(item)

    return items


# ---------------------------------------------------------------------------
# Items → tag text  (for LLM context in agenda.py)
# ---------------------------------------------------------------------------

def items_to_tag_text(items: list[dict]) -> str:
    """
    Convert agenda.json items to two-line tag format for LLM context.

    Includes #id- so cato can write items back and merge() can match by ID.
    Groups items by source with <!-- BEGIN/END --> markers.
    Excludes soft-deleted items (deleted: true).
    """
    from collections import defaultdict
    today = date.today()

    groups: dict[str, list[dict]] = defaultdict(list)
    for it in items:
        # Skip soft-deleted items
        if it.get("deleted"):
            continue
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
            it_id = it.get("id", "")
            tag_parts = [f"#id-{it_id}"]

            # Build tag line from tags array (new schema) or legacy fields (compat)
            if it.get("tags"):
                for t in it["tags"]:
                    if not t.startswith("#done-") and not t.startswith("#source-") and not t.startswith("#id-"):
                        tag_parts.append(t)
                if it.get("done"):
                    tag_parts.append(f"#done-{it['done']}")
            else:
                # legacy fallback
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
                    if it.get("duration"):
                        tag_parts.append(f"#time-{it['duration']}")
                else:
                    tag_parts.append("#action-required")
                    if it.get("duration"):
                        tag_parts.append(f"#time-{it['duration']}")

                facet = it.get("facet", "none")
                if facet != "none":
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
# Merge — used by cato's write_file(file='agenda', content=...)
# ---------------------------------------------------------------------------

def merge_cato_write(data: dict, tag_text: str, default_source: str = "cato") -> dict:
    """
    Merge a tag-format write (from cato) back into agenda.json.

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
        # Apply done mark to any item that's marked done
        if item_id in done_ids:
            it = dict(it)
            done_tag = f"#done-{done_ids[item_id]}"
            tags = [t for t in (it.get("tags") or []) if not t.startswith("#done-")]
            tags.append(done_tag)
            it["tags"] = tags
            it.pop("done", None)

        if it.get("source") != default_source:
            # Vault items always kept
            result.append(it)
        else:
            # default_source items: keep only if seen in tag_text (will be updated below)
            if item_id in seen_ids or item_id in done_ids:
                result.append(it)

    # Update / add items from parsed content
    result_by_id = {it.get("id"): i for i, it in enumerate(result)}

    for p in parsed:
        if p.get("_done_date"):
            continue  # done items are handled above, not re-added
        item_id = p.get("id", "")
        if item_id in result_by_id:
            # Update in place, preserve source and recurring tags
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
    Outputs v0.2 tag-based schema: {id, title, source, tags, _done_date?}.
    """
    items: list[dict] = []
    for entry in re.split(r"\n\s*\n", text.strip()):
        lines = [l for l in entry.strip().splitlines() if l.strip()]
        if len(lines) < 2:
            continue
        tag_line, title = lines[0].strip(), lines[1].strip()
        if not tag_line.startswith("#"):
            continue

        id_m   = _ID_RE.search(tag_line)
        done_m = _DONE_RE.search(tag_line)

        item: dict[str, Any] = {
            "id":     id_m.group(1) if id_m else new_id(),
            "title":  title,
            "source": default_source,
        }

        if done_m:
            item["_done_date"] = done_m.group(1)

        # Build tags array from the tag line (same logic as parse_tag_entries_to_items)
        dates   = _DATE_RE.findall(tag_line)
        time_m  = _TIME_RE.search(tag_line)
        dur_m   = None if time_m else _DURATION_RE.search(tag_line)
        facet_m = _FACET_RE.search(tag_line)
        dens_m  = _DENSITY_RE.search(tag_line)
        size_m  = _SIZE_RE.search(tag_line)
        layer_m = _LAYER_RE.search(tag_line)

        tags: list[str] = []
        if len(dates) == 2 and time_m:
            tags.append(f"#date-{dates[0]}")
            tags.append(f"#date-{dates[1]}")
            tags.append(f"#time-{time_m.group(1)}-{time_m.group(2)}")
        elif len(dates) >= 1 and time_m:
            tags.append(f"#date-{dates[0]}")
            tags.append(f"#time-{time_m.group(1)}-{time_m.group(2)}")
        elif len(dates) >= 1 and dur_m:
            tags.append(f"#date-{dates[0]}")
            tags.append(f"#time-{dur_m.group(1)}")
        elif len(dates) >= 1:
            tags.append(f"#date-{dates[0]}")
        else:
            tags.append(f"#date-{date.today().isoformat()}")

        facet_val = facet_m.group(1) if facet_m else "none"
        if facet_val != "none":
            tags.append(f"#facet-{facet_val}")
        if dens_m:
            tags.append(f"#density-{dens_m.group(1)}")
        if size_m and size_m.group(1) != "m":
            tags.append(f"#size-{size_m.group(1)}")
        if layer_m and layer_m.group(1) != "0":
            tags.append(f"#layer-{layer_m.group(1)}")
        if done_m:
            tags.append(f"#done-{done_m.group(1)}")

        extra = _EXTRA_TAG_RE.findall(_STRUCTURAL_RE.sub("", tag_line))
        tags.extend(extra)

        item["tags"] = tags
        items.append(item)

    return items


# ---------------------------------------------------------------------------
# Retention cleanup
# ---------------------------------------------------------------------------

def prune_done_items(data: dict, retention_days: int) -> int:
    """
    Remove items where done date is older than retention_days.
    Checks both the #done-* tag (v0.2 schema) and the legacy done= field.
    Returns count of pruned items.
    """
    from datetime import timedelta
    cutoff = date.today() - timedelta(days=retention_days)

    def _done_date(it: dict) -> date | None:
        for t in (it.get("tags") or []):
            m = _DONE_RE.match(t)
            if m:
                return _parse_date(m.group(1))
        if it.get("done"):
            return _parse_date(it["done"])
        return None

    before = len(data.get("items", []))
    data["items"] = [
        it for it in data.get("items", [])
        if not (_done_date(it) and _done_date(it) < cutoff)
    ]
    return before - len(data["items"])


def _parse_date(s: str) -> date:
    try:
        return date.fromisoformat(s)
    except (ValueError, TypeError):
        return date.max


# ---------------------------------------------------------------------------
# Schema migration: v0.1 explicit fields → v0.2 tag-based
# ---------------------------------------------------------------------------

def migrate_to_tag_schema(data: dict) -> int:
    """Convert all items from the v0.1 explicit-fields schema to the v0.2
    tags-based schema ({id, title, source, note?, tags}).

    Items that already carry a #date-* tag are considered new-schema — their
    stale explicit fields (if any) are stripped but their tags are untouched.
    Items without any #date-* tag are converted: explicit fields are encoded
    as structural tags; any extra tags already present are preserved.

    Returns the number of items converted (already-new-schema items not counted).
    """
    today = date.today()
    converted = 0

    for item in data.get("items", []):
        existing_tags: list[str] = item.get("tags") or []
        has_tag_schema = any(_DATE_RE.search(t) for t in existing_tags)

        if has_tag_schema:
            # Already v0.2 — strip any leftover explicit fields
            for f in _OLD_SCHEMA_FIELDS:
                item.pop(f, None)
            continue

        # --- v0.1 → v0.2 conversion ---
        tags: list[str] = []

        d = item.get("day")
        s = item.get("start") or ""
        e = item.get("end") or ""

        if s and "T" in s:
            # Multi-day ISO: "2026-04-28T12:00" / "2026-04-30T18:00"
            start_date = s.split("T")[0]
            end_date   = e.split("T")[0] if e else start_date
            start_time = s.split("T")[1][:5]
            end_time   = e.split("T")[1][:5] if e and "T" in e else start_time
            tags.append(f"#date-{start_date}")
            if end_date != start_date:
                tags.append(f"#date-{end_date}")
            tags.append(f"#time-{start_time}-{end_time}")
        elif item.get("date"):
            date_str  = item["date"]
            date_end  = item.get("date_end")
            tags.append(f"#date-{date_str}")
            if date_end and date_end != date_str:
                tags.append(f"#date-{date_end}")
            if s:
                tags.append(f"#time-{s}-{e}" if e else f"#time-{s}")
        elif d is not None:
            target = date.fromordinal(today.toordinal() + d)
            tags.append(f"#date-{target.isoformat()}")
            if s:
                tags.append(f"#time-{s}-{e}" if e else f"#time-{s}")
            elif item.get("duration"):
                tags.append(f"#time-{item['duration']}")
        else:
            tags.append(f"#date-{today.isoformat()}")
            if item.get("duration"):
                tags.append(f"#time-{item['duration']}")

        facet = item.get("facet", "none")
        if facet and facet != "none":
            tags.append(f"#facet-{facet}")
        if item.get("density"):
            tags.append(f"#density-{item['density']}")
        size = item.get("size", "m")
        if size and size != "m":
            tags.append(f"#size-{size}")
        layer = item.get("layer", 0)
        if layer and layer > 0:
            tags.append(f"#layer-{layer}")
        if item.get("done"):
            tags.append(f"#done-{item['done']}")

        # Preserve extra (non-structural) tags already on the item
        for t in existing_tags:
            if not any(t.startswith(p) for p in _STRUCTURAL_PREFIXES):
                tags.append(t)

        item["tags"] = tags
        for f in _OLD_SCHEMA_FIELDS:
            item.pop(f, None)

        converted += 1

    if converted:
        data.setdefault("meta", {})["version"] = "0.2"
        data["meta"].pop("base_date", None)

    return converted
