"""
Built-in holiday data for supported regions.

Structure per region:
  holidays(year) -> dict[date, str]   — public holidays for that year
  school_holidays -> list of (start, end, name) per year

To add a new region, add an entry to REGIONS below.
"""

from __future__ import annotations

from datetime import date, timedelta

# =============================================================================
# GAUSSIAN EASTER FORMULA
# =============================================================================

def _easter(year: int) -> date:
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    return date(year, month, day)


# =============================================================================
# DE — federal holidays (all German states)
# Source: https://www.bmi.bund.de/DE/themen/verfassung/feiertage/feiertage-node.html
# =============================================================================

def _holidays_DE(year: int) -> dict[date, str]:
    e = _easter(year)
    return {
        date(year, 1, 1):   "Neujahr",
        e - timedelta(2):   "Karfreitag",
        e + timedelta(1):   "Ostermontag",
        date(year, 5, 1):   "Tag der Arbeit",
        e + timedelta(39):  "Christi Himmelfahrt",
        e + timedelta(50):  "Pfingstmontag",
        date(year, 10, 3):  "Tag der Deutschen Einheit",
        date(year, 12, 25): "1. Weihnachtstag",
        date(year, 12, 26): "2. Weihnachtstag",
    }


# =============================================================================
# DE-BY — Bayern additions on top of DE
# Source: https://www.stmi.bayern.de/staat-und-verfassung/feiertage/
# =============================================================================

def _holidays_DE_BY(year: int) -> dict[date, str]:
    e = _easter(year)
    extra: dict[date, str] = {
        date(year, 1, 6):   "Heilige Drei Könige",  # noqa: i18n
        e:                   "Ostersonntag",
        e + timedelta(49):  "Pfingstsonntag",
        e + timedelta(60):  "Fronleichnam",
        date(year, 8, 15):  "Mariä Himmelfahrt",  # noqa: i18n
        date(year, 11, 1):  "Allerheiligen",
    }
    return {**_holidays_DE(year), **extra}


# Schulferien Bayern
# Source: https://www.schulferien.org/deutschland/ferien/bayern/
# Update annually.
_SCHOOL_HOLIDAYS_DE_BY: dict[int, list[tuple[date, date, str]]] = {
    2026: [
        (date(2026, 2, 16), date(2026, 2, 20), "Frühjahrsferien"),  # noqa: i18n
        (date(2026, 3, 30), date(2026, 4, 10), "Osterferien"),
        (date(2026, 5, 26), date(2026, 6, 5),  "Pfingstferien"),
        (date(2026, 8, 3),  date(2026, 9, 14), "Sommerferien"),
        (date(2026, 11, 2), date(2026, 11, 6), "Allerheiligenferien"),
        (date(2026, 12, 24), date(2027, 1, 8), "Weihnachtsferien"),
    ],
    2027: [
        (date(2027, 2, 8),  date(2027, 2, 12), "Frühjahrsferien"),  # noqa: i18n
        (date(2027, 3, 22), date(2027, 4, 2),  "Osterferien"),
        (date(2027, 5, 18), date(2027, 5, 28), "Pfingstferien"),
        (date(2027, 8, 2),  date(2027, 9, 13), "Sommerferien"),
        (date(2027, 11, 2), date(2027, 11, 5), "Allerheiligenferien"),
        (date(2027, 12, 24), date(2028, 1, 7), "Weihnachtsferien"),
    ],
}


# =============================================================================
# REGISTRY
# key: (country, state)  — state="" means country-level only
# =============================================================================

REGIONS: dict[tuple[str, str], dict] = {
    ("DE", ""): {
        "holidays": _holidays_DE,
        "school_holidays": {},          # school holidays are state-specific
    },
    ("DE", "BY"): {
        "holidays": _holidays_DE_BY,
        "school_holidays": _SCHOOL_HOLIDAYS_DE_BY,
    },
}
