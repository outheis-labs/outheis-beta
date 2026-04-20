"""test_holidays_coverage — ensure holiday data is available for all configured regions.

Rule: every region in REGIONS must have public holiday (Feiertage) data for the
current year and the next two full calendar years.

School holidays (Schulferien) are explicitly excluded from this coverage check:
they are typically only published around 1 July each year for the following
school year, making it impossible to guarantee 2-year coverage programmatically.
"""

from __future__ import annotations

from datetime import date

import pytest


def _current_and_next_two_years() -> list[int]:
    today = date.today()
    return [today.year, today.year + 1, today.year + 2]


# ---------------------------------------------------------------------------
# Feiertage coverage — all regions, 2 years ahead
# ---------------------------------------------------------------------------

class TestFeiertageCoverage:

    def test_all_regions_have_feiertage_callable(self):
        """Every region must supply a feiertage callable."""
        from outheis.core.holidays._builtin import REGIONS
        for key, region in REGIONS.items():
            assert callable(region.get("feiertage")), (
                f"Region {key} is missing a 'feiertage' callable"
            )

    def test_feiertage_returns_nonempty_dict_for_each_year(self):
        """feiertage(year) must return at least one holiday for current+2 years."""
        from outheis.core.holidays._builtin import REGIONS
        for key, region in REGIONS.items():
            fn = region["feiertage"]
            for year in _current_and_next_two_years():
                result = fn(year)
                assert isinstance(result, dict), (
                    f"Region {key}: feiertage({year}) did not return a dict"
                )
                assert len(result) > 0, (
                    f"Region {key}: feiertage({year}) returned an empty dict — "
                    f"holiday data missing for year {year}"
                )

    def test_feiertage_keys_are_date_objects(self):
        """All keys returned by feiertage() must be date objects."""
        from outheis.core.holidays._builtin import REGIONS
        for key, region in REGIONS.items():
            fn = region["feiertage"]
            for year in _current_and_next_two_years():
                for d in fn(year).keys():
                    assert isinstance(d, date), (
                        f"Region {key}: feiertage({year}) contains non-date key {d!r}"
                    )

    def test_feiertage_values_are_nonempty_strings(self):
        """All values returned by feiertage() must be non-empty strings."""
        from outheis.core.holidays._builtin import REGIONS
        for key, region in REGIONS.items():
            fn = region["feiertage"]
            for year in _current_and_next_two_years():
                for d, name in fn(year).items():
                    assert isinstance(name, str) and name.strip(), (
                        f"Region {key}: feiertage({year})[{d}] is not a non-empty string"
                    )

    def test_feiertage_dates_fall_in_correct_year(self):
        """All dates returned by feiertage(year) must belong to that year."""
        from outheis.core.holidays._builtin import REGIONS
        for key, region in REGIONS.items():
            fn = region["feiertage"]
            for year in _current_and_next_two_years():
                for d in fn(year).keys():
                    assert d.year == year, (
                        f"Region {key}: feiertage({year}) contains date {d} "
                        f"which belongs to year {d.year}, not {year}"
                    )


# ---------------------------------------------------------------------------
# Schulferien — presence check only for current year (not coverage guarantee)
# ---------------------------------------------------------------------------

class TestSchulferienStructure:

    def test_schulferien_is_dict(self):
        """schulferien must be a dict (year → list of tuples)."""
        from outheis.core.holidays._builtin import REGIONS
        for key, region in REGIONS.items():
            sf = region.get("schulferien", {})
            assert isinstance(sf, dict), (
                f"Region {key}: 'schulferien' must be a dict, got {type(sf)}"
            )

    def test_schulferien_entries_are_valid_tuples(self):
        """Each Schulferien entry must be (date, date, str) with start <= end."""
        from outheis.core.holidays._builtin import REGIONS
        for key, region in REGIONS.items():
            for year, periods in region.get("schulferien", {}).items():
                for entry in periods:
                    assert len(entry) == 3, (
                        f"Region {key} year {year}: entry {entry!r} must have 3 elements"
                    )
                    start, end, name = entry
                    assert isinstance(start, date), (
                        f"Region {key} year {year}: start {start!r} is not a date"
                    )
                    assert isinstance(end, date), (
                        f"Region {key} year {year}: end {end!r} is not a date"
                    )
                    assert isinstance(name, str) and name.strip(), (
                        f"Region {key} year {year}: name {name!r} is not a non-empty string"
                    )
                    assert start <= end, (
                        f"Region {key} year {year}: start {start} > end {end} in '{name}'"
                    )


# ---------------------------------------------------------------------------
# get_feiertag public API
# ---------------------------------------------------------------------------

class TestGetFeiertag:

    def test_returns_none_when_no_country(self):
        from outheis.core.holidays import get_feiertag
        assert get_feiertag(date(2026, 1, 1), "", "") is None

    def test_returns_name_for_known_holiday(self):
        from outheis.core.holidays import get_feiertag
        # Neujahr is always 1 January for DE
        result = get_feiertag(date(2026, 1, 1), "DE", "")
        assert result == "Neujahr"

    def test_returns_none_for_non_holiday(self):
        from outheis.core.holidays import get_feiertag
        # A random mid-week date unlikely to be a holiday
        result = get_feiertag(date(2026, 3, 4), "DE", "")
        assert result is None

    def test_state_specific_holiday_visible_with_state(self):
        from outheis.core.holidays import get_feiertag
        # Heilige Drei Koenige (Jan 6) is only in Bayern (BY), not federal DE  # noqa: i18n
        result_federal = get_feiertag(date(2026, 1, 6), "DE", "")
        result_by = get_feiertag(date(2026, 1, 6), "DE", "BY")
        assert result_federal is None
        assert result_by is not None

    def test_unknown_region_returns_none(self):
        from outheis.core.holidays import get_feiertag
        result = get_feiertag(date(2026, 12, 25), "XX", "YY")
        # No data for XX → falls back to country-only XX → also None
        assert result is None
