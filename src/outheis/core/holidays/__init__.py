"""
Holiday lookup for Agenda.md scaffold and get_weekday tool.

Behaviour:
  country=""             → nothing shown (no config = no holidays)
  country="DE", state="" → federal DE holidays only, no school holidays
  country="DE", state="BY" → federal + Bayern + Bayern school holidays

User overrides: place ~/.outheis/human/holidays/DE-BY.md (or DE.md)
to add custom holidays.  Format: one entry per line: YYYY-MM-DD Name
Lines starting with '#' are comments.
"""

from __future__ import annotations

from datetime import date

from outheis.core.holidays._builtin import REGIONS

# =============================================================================
# USER OVERRIDE LOADER
# =============================================================================

def _load_user_overrides(country: str, state: str) -> dict[date, str]:
    """Load custom holidays from ~/.outheis/human/holidays/<country>[-<state>].md"""
    try:
        from outheis.core.config import get_human_dir
        base = get_human_dir() / "holidays"
        candidates = []
        if state:
            candidates.append(base / f"{country}-{state}.md")
        candidates.append(base / f"{country}.md")
        entries: dict[date, str] = {}
        for path in candidates:
            if path.exists():
                for line in path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split(None, 1)
                    if len(parts) == 2:
                        try:
                            entries[date.fromisoformat(parts[0])] = parts[1]
                        except ValueError:
                            pass
        return entries
    except Exception:
        return {}


# =============================================================================
# PUBLIC API
# =============================================================================

def get_holiday(d: date, country: str, state: str) -> str | None:
    """
    Return the public holiday name for date d, or None.
    Returns None if country is empty (no holidays configured).
    User overrides (~/.outheis/human/holidays/) take precedence.
    """
    if not country:
        return None

    # User override (exact date match)
    overrides = _load_user_overrides(country, state)
    if d in overrides:
        return overrides[d]

    # Built-in: prefer country+state, fall back to country-only
    for key in ((country, state), (country, "")):
        region = REGIONS.get(key)
        if region:
            return region["holidays"](d.year).get(d)

    return None


def get_school_holiday(d: date, country: str, state: str) -> str | None:
    """
    Return the school holiday name if d falls within a holiday period, or None.
    Only available when state is configured (school holidays are state-specific).
    """
    if not country or not state:
        return None

    region = REGIONS.get((country, state))
    if not region:
        return None

    school_holidays = region.get("school_holidays", {})
    for year in (d.year, d.year - 1):
        for start, end, name in school_holidays.get(year, []):
            if start <= d <= end:
                return name

    return None


def get_day_label(d: date, weekday_name: str, country: str, state: str) -> str:
    """
    Return the display label for the Agenda.md header line.
    Holiday name replaces weekday name; plain weekday if no holiday.
    """
    holiday = get_holiday(d, country, state)
    return holiday if holiday else weekday_name
