"""test_recurring_schema — unit tests for next_recurring_occurrence.

Tests the date advancement logic for all #recurring-* tag formats
without hitting any API or filesystem.
"""

import pytest
from datetime import date


def get_fn():
    """Import the function under test."""
    from outheis.agents.agenda import next_recurring_occurrence
    return next_recurring_occurrence


class TestRecurringDaily:

    def test_daily_advances_one_day(self):
        fn = get_fn()
        result = fn(date(2026, 4, 21), "#recurring-daily")
        assert result == date(2026, 4, 22)

    def test_daily_across_month_boundary(self):
        fn = get_fn()
        result = fn(date(2026, 4, 30), "#recurring-daily")
        assert result == date(2026, 5, 1)


class TestRecurringWeekly:

    def test_weekly_advances_seven_days(self):
        fn = get_fn()
        result = fn(date(2026, 4, 21), "#recurring-weekly")  # Tuesday
        assert result == date(2026, 4, 28)  # Tuesday next week

    def test_weekly_across_year_boundary(self):
        fn = get_fn()
        result = fn(date(2026, 12, 28), "#recurring-weekly")
        assert result == date(2027, 1, 4)


class TestRecurringMonthly:

    def test_monthly_same_day_next_month(self):
        fn = get_fn()
        result = fn(date(2026, 4, 15), "#recurring-monthly")
        assert result == date(2026, 5, 15)

    def test_monthly_end_of_month_clamps(self):
        fn = get_fn()
        # Jan 31 -> Feb 28 (2026 is not a leap year)
        result = fn(date(2026, 1, 31), "#recurring-monthly")
        assert result == date(2026, 2, 28)

    def test_monthly_december_to_january(self):
        fn = get_fn()
        result = fn(date(2026, 12, 10), "#recurring-monthly")
        assert result == date(2027, 1, 10)


class TestRecurringYearly:

    def test_yearly_same_month_day_next_year(self):
        fn = get_fn()
        result = fn(date(2026, 6, 15), "#recurring-yearly")
        assert result == date(2027, 6, 15)

    def test_yearly_december(self):
        fn = get_fn()
        result = fn(date(2026, 12, 25), "#recurring-yearly")
        assert result == date(2027, 12, 25)

    def test_yearly_feb29_clamps_on_non_leap(self):
        fn = get_fn()
        # 2028 is leap, next is 2029 which is not
        result = fn(date(2028, 2, 29), "#recurring-yearly")
        assert result == date(2029, 2, 28)


class TestRecurringSpecificWeekdays:

    def test_single_weekday(self):
        fn = get_fn()
        # Find next Monday from today — we just check it's a Monday
        result = fn(date(2026, 4, 21), "#recurring-mon")
        assert result is not None
        assert result.weekday() == 0  # Monday

    def test_mon_wed_thu_from_monday(self):
        fn = get_fn()
        # From Monday 2026-04-20, next in mon-wed-thu is Wednesday 2026-04-22
        result = fn(date(2026, 4, 20), "#recurring-mon-wed-thu")
        assert result is not None
        assert result.weekday() in (0, 2, 3)  # mon, wed, thu

    def test_canonical_codes_only(self):
        fn = get_fn()
        # Non-canonical codes return None
        result = fn(date(2026, 4, 21), "#recurring-mo-mi-do")
        assert result is None

    def test_unknown_tag_returns_none(self):
        fn = get_fn()
        result = fn(date(2026, 4, 21), "#recurring-invalid")
        assert result is None


class TestRecurringSpecificMonthDays:

    def test_monthly_specific_days_next_occurrence(self):
        fn = get_fn()
        # This test uses today internally, so just check it returns a date
        # on day 10 or 22
        result = fn(date(2026, 4, 1), "#recurring-monthly-10-22")
        assert result is not None
        assert result.day in (10, 22)

    def test_monthly_specific_days_is_future(self):
        fn = get_fn()
        from datetime import date as d
        result = fn(date(2026, 4, 1), "#recurring-monthly-10-22")
        assert result is not None
        assert result > d.today()


class TestI18nCanonicalMapping:

    def test_locale_abbrevs_to_canonical_de(self):
        from outheis.core.i18n import locale_abbrevs_to_canonical
        result = locale_abbrevs_to_canonical(["Mo", "Mi", "Do"], "de")
        assert result == ["mon", "wed", "thu"]

    def test_locale_abbrevs_to_canonical_en(self):
        from outheis.core.i18n import locale_abbrevs_to_canonical
        result = locale_abbrevs_to_canonical(["Mon", "Wed", "Thu"], "en")
        assert result == ["mon", "wed", "thu"]

    def test_locale_abbrevs_case_insensitive(self):
        from outheis.core.i18n import locale_abbrevs_to_canonical
        result = locale_abbrevs_to_canonical(["mo", "mi", "do"], "de")
        assert result == ["mon", "wed", "thu"]

    def test_recurring_weekday_codes_length(self):
        from outheis.core.i18n import RECURRING_WEEKDAY_CODES
        assert len(RECURRING_WEEKDAY_CODES) == 7
        assert RECURRING_WEEKDAY_CODES[0] == "mon"
        assert RECURRING_WEEKDAY_CODES[6] == "sun"
