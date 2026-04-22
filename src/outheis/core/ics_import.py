"""
ics_import — parse ICS files into agenda.json-compatible item lists.

No external dependencies. Handles:
  - DTSTART / DTEND with TZID or UTC (Z) suffix
  - All-day events (VALUE=DATE)
  - Multi-day events
  - RRULE events are imported as single-occurrence (first instance only)
  - SUMMARY → title, UID → stable ID prefix
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# ICS text parser
# ---------------------------------------------------------------------------

def _unfold(text: str) -> str:
    """Unfold continuation lines (RFC 5545 §3.1)."""
    return re.sub(r"\r?\n[ \t]", "", text)


def _parse_blocks(text: str, block_name: str) -> list[dict[str, list[str]]]:
    """Extract all BEGIN:block_name ... END:block_name sections as property dicts."""
    pattern = re.compile(
        rf"BEGIN:{block_name}\r?\n(.*?)END:{block_name}",
        re.DOTALL | re.IGNORECASE,
    )
    blocks = []
    for m in pattern.finditer(text):
        props: dict[str, list[str]] = {}
        for line in m.group(1).splitlines():
            if ":" not in line:
                continue
            key_part, _, val = line.partition(":")
            key = key_part.split(";")[0].strip().upper()
            props.setdefault(key, []).append(val.strip())
        blocks.append(props)
    return blocks


def _parse_dt(value: str, params: str = "") -> datetime | date | None:
    """
    Parse a DTSTART/DTEND value string.

    Handles:
      20260423          → date (all-day)
      20260423T090000   → naive datetime (local)
      20260423T090000Z  → UTC datetime
    Timezone offsets from TZID are ignored (treated as local).
    """
    value = value.strip()
    if re.match(r"^\d{8}$", value):
        return date(int(value[:4]), int(value[4:6]), int(value[6:8]))
    if re.match(r"^\d{8}T\d{6}Z$", value):
        dt = datetime(
            int(value[:4]), int(value[4:6]), int(value[6:8]),
            int(value[9:11]), int(value[11:13]), int(value[13:15]),
            tzinfo=timezone.utc,
        )
        return dt.astimezone().replace(tzinfo=None)
    if re.match(r"^\d{8}T\d{6}$", value):
        return datetime(
            int(value[:4]), int(value[4:6]), int(value[6:8]),
            int(value[9:11]), int(value[11:13]), int(value[13:15]),
        )
    return None


def _external_id(uid: str, dtstart: str) -> str:
    """Deterministic external key: SHA1(UID|DTSTART) — used for deduplication only."""
    raw = f"{uid}|{dtstart}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def _new_snowflake() -> str:
    from outheis.core.snowflake import generate_str
    return generate_str()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_ics(
    path: Path,
    facet: str = "misc",
    existing_ids: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """
    Parse an ICS file and return a list of agenda.json-compatible items.

    Args:
        path:         Path to the .ics file.
        facet:        Facet ID to assign to all imported items.
        existing_ids: Map of {external_id → snowflake_id} from a previous import.
                      Matching items keep their existing Snowflake ID.
    """
    if existing_ids is None:
        existing_ids = {}
    text = _unfold(path.read_text(encoding="utf-8", errors="replace"))
    vevents = _parse_blocks(text, "VEVENT")

    today = date.today()
    items: list[dict[str, Any]] = []

    for ev in vevents:
        summary_parts = ev.get("SUMMARY", [])
        title = summary_parts[0] if summary_parts else "(kein Titel)"
        # strip ICS escape sequences
        title = title.replace("\\,", ",").replace("\\;", ";").replace("\\n", " ").strip()

        uid = ev.get("UID", [""])[0]

        # --- DTSTART ---
        dtstart_raw = ev.get("DTSTART", [""])[0]
        dtstart = _parse_dt(dtstart_raw)
        if dtstart is None:
            continue

        # --- DTEND / DURATION ---
        dtend_raw = ev.get("DTEND", [""])[0]
        dtend = _parse_dt(dtend_raw) if dtend_raw else None

        ext_id = _external_id(uid, dtstart_raw)
        item_id = existing_ids.get(ext_id) or _new_snowflake()

        # All-day event (DTSTART is a date, not datetime)
        if isinstance(dtstart, date) and not isinstance(dtstart, datetime):
            day_off = (dtstart - today).days
            item: dict[str, Any] = {
                "id":          item_id,
                "external_id": ext_id,
                "title":       title,
                "facet":       facet,
                "source":      path.name,
                "type":        "volatile",
                "day":         day_off,
                "size":        "m",
            }
            if isinstance(dtend, date) and not isinstance(dtend, datetime):
                span = (dtend - dtstart).days
                if span > 1:
                    item["type"]  = "fixed"
                    item["start"] = dtstart.isoformat() + "T00:00"
                    item["end"]   = (dtend - timedelta(days=1)).isoformat() + "T23:59"
                    del item["day"]
                    del item["size"]
            items.append(item)
            continue

        # Timed event
        start_time = dtstart.strftime("%H:%M")
        end_time   = dtend.strftime("%H:%M") if isinstance(dtend, datetime) else None
        dtstart_date = dtstart.date()

        if isinstance(dtend, datetime) and dtend.date() != dtstart_date:
            item = {
                "id":          item_id,
                "external_id": ext_id,
                "title":       title,
                "facet":       facet,
                "source":      path.name,
                "type":        "fixed",
                "start":       dtstart.strftime("%Y-%m-%dT%H:%M"),
                "end":         dtend.strftime("%Y-%m-%dT%H:%M"),
            }
        else:
            day_off = (dtstart_date - today).days
            item = {
                "id":          item_id,
                "external_id": ext_id,
                "title":       title,
                "facet":       facet,
                "source":      path.name,
                "type":        "fixed",
                "day":         day_off,
                "start":       start_time,
                "end":         end_time or start_time,
            }

        items.append(item)

    return items


def import_ics_to_json(ics_path: Path, out_path: Path, facet: str = "misc") -> int:
    """
    Parse ics_path and write a standalone agenda-ics-*.json to out_path.

    Returns the number of items written.
    """
    from outheis.core.agenda_store import _build_facets

    # Preserve Snowflake IDs from previous import via external_id mapping
    existing_ids: dict[str, str] = {}
    if out_path.exists():
        try:
            old = json.loads(out_path.read_text(encoding="utf-8"))
            for it in old.get("items", []):
                if it.get("external_id") and it.get("id"):
                    existing_ids[it["external_id"]] = it["id"]
        except Exception:
            pass

    items = parse_ics(ics_path, facet=facet, existing_ids=existing_ids)
    today = date.today().isoformat()
    data = {
        "meta": {
            "version":     "0.1",
            "source_file": ics_path.name,
            "facet":       facet,
            "imported":    datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "base_date":   today,
        },
        "facets": _build_facets(items),
        "items":  items,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(items)
