"""Tests for token usage tracking (core/tokens.py)."""

import json
from datetime import datetime, timedelta

import pytest

from outheis.core.tokens import (
    _model_cost,
    get_stats_7days,
    get_usage_summary,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_usage(path, entries):
    """Write a list of usage dicts to a JSONL file."""
    with open(path, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def _entry(agent="relay", model="claude-haiku-4-5", input=100, output=50, ts=None):
    if ts is None:
        ts = datetime.now().isoformat(timespec="seconds")
    return {"ts": ts, "agent": agent, "model": model, "input": input, "output": output}


# ---------------------------------------------------------------------------
# _model_cost
# ---------------------------------------------------------------------------

class TestModelCost:
    def test_haiku(self):
        assert _model_cost("claude-haiku-4-5") == (0.80, 4.00)

    def test_sonnet(self):
        assert _model_cost("claude-sonnet-4-6") == (3.00, 15.00)

    def test_opus(self):
        assert _model_cost("claude-opus-4-6") == (15.00, 75.00)

    def test_case_insensitive(self):
        assert _model_cost("Claude-Haiku-4-5") == (0.80, 4.00)

    def test_unknown_falls_back_to_sonnet(self):
        assert _model_cost("gpt-4o") == (3.00, 15.00)


# ---------------------------------------------------------------------------
# get_stats_7days
# ---------------------------------------------------------------------------

class TestGetStats7Days:
    def test_no_file_returns_zero_totals(self, tmp_path, monkeypatch):
        monkeypatch.setattr("outheis.core.tokens.get_token_usage_path", lambda: tmp_path / "usage.jsonl")
        result = get_stats_7days()
        assert result["total_7d"] == 0
        assert len(result["days"]) == 7

    def test_counts_tokens_today(self, tmp_path, monkeypatch):
        path = tmp_path / "usage.jsonl"
        monkeypatch.setattr("outheis.core.tokens.get_token_usage_path", lambda: path)
        _write_usage(path, [_entry(input=200, output=100)])
        result = get_stats_7days()
        assert result["total_7d"] == 300

    def test_excludes_entries_older_than_7_days(self, tmp_path, monkeypatch):
        path = tmp_path / "usage.jsonl"
        monkeypatch.setattr("outheis.core.tokens.get_token_usage_path", lambda: path)
        old_ts = (datetime.now() - timedelta(days=8)).isoformat(timespec="seconds")
        _write_usage(path, [_entry(input=999, output=999, ts=old_ts)])
        result = get_stats_7days()
        assert result["total_7d"] == 0

    def test_period_bucketing(self, tmp_path, monkeypatch):
        path = tmp_path / "usage.jsonl"
        monkeypatch.setattr("outheis.core.tokens.get_token_usage_path", lambda: path)
        today = datetime.now().strftime("%Y-%m-%d")
        # period 0 = 00:00–05:59, period 2 = 12:00–17:59
        ts_p0 = f"{today}T03:00:00"
        ts_p2 = f"{today}T14:00:00"
        _write_usage(path, [
            _entry(input=10, output=0, ts=ts_p0),
            _entry(input=20, output=0, ts=ts_p2),
        ])
        result = get_stats_7days()
        today_entry = next(d for d in result["days"] if d["date"] == today)
        assert today_entry["periods"][0] == 10
        assert today_entry["periods"][2] == 20

    def test_always_returns_7_days(self, tmp_path, monkeypatch):
        path = tmp_path / "usage.jsonl"
        monkeypatch.setattr("outheis.core.tokens.get_token_usage_path", lambda: path)
        _write_usage(path, [_entry()])
        assert len(get_stats_7days()["days"]) == 7

    def test_skips_malformed_lines(self, tmp_path, monkeypatch):
        path = tmp_path / "usage.jsonl"
        monkeypatch.setattr("outheis.core.tokens.get_token_usage_path", lambda: path)
        path.write_text('not json\n{"ts":"bad-date","agent":"x","input":1,"output":1}\n' + json.dumps(_entry(input=50, output=50)) + "\n")
        result = get_stats_7days()
        assert result["total_7d"] == 100


# ---------------------------------------------------------------------------
# get_usage_summary
# ---------------------------------------------------------------------------

class TestGetUsageSummary:
    def test_no_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr("outheis.core.tokens.get_token_usage_path", lambda: tmp_path / "usage.jsonl")
        out = get_usage_summary()
        assert "No token data" in out

    def test_no_entries_in_window(self, tmp_path, monkeypatch):
        path = tmp_path / "usage.jsonl"
        monkeypatch.setattr("outheis.core.tokens.get_token_usage_path", lambda: path)
        old_ts = (datetime.now() - timedelta(days=30)).isoformat(timespec="seconds")
        _write_usage(path, [_entry(ts=old_ts)])
        out = get_usage_summary()
        assert "No token usage recorded" in out

    def test_summary_contains_total(self, tmp_path, monkeypatch):
        path = tmp_path / "usage.jsonl"
        monkeypatch.setattr("outheis.core.tokens.get_token_usage_path", lambda: path)
        _write_usage(path, [_entry(input=1000, output=500)])
        out = get_usage_summary()
        assert "1,500" in out

    def test_summary_lists_agent(self, tmp_path, monkeypatch):
        path = tmp_path / "usage.jsonl"
        monkeypatch.setattr("outheis.core.tokens.get_token_usage_path", lambda: path)
        _write_usage(path, [_entry(agent="pattern", input=100, output=50)])
        out = get_usage_summary()
        assert "pattern" in out

    def test_cost_calculation(self, tmp_path, monkeypatch):
        path = tmp_path / "usage.jsonl"
        monkeypatch.setattr("outheis.core.tokens.get_token_usage_path", lambda: path)
        # haiku: 1M input = $0.80, 1M output = $4.00
        # 1000 input + 500 output = $0.0008 + $0.002 = $0.0028
        _write_usage(path, [_entry(model="claude-haiku-4-5", input=1000, output=500)])
        out = get_usage_summary()
        assert "$0.0028" in out

    def test_date_filter_today(self, tmp_path, monkeypatch):
        path = tmp_path / "usage.jsonl"
        monkeypatch.setattr("outheis.core.tokens.get_token_usage_path", lambda: path)
        old_ts = (datetime.now() - timedelta(days=3)).isoformat(timespec="seconds")
        _write_usage(path, [
            _entry(input=999, output=0, ts=old_ts),
            _entry(input=100, output=50),
        ])
        out = get_usage_summary(date="today")
        assert "150" in out
        assert "999" not in out

    def test_date_filter_yesterday(self, tmp_path, monkeypatch):
        path = tmp_path / "usage.jsonl"
        monkeypatch.setattr("outheis.core.tokens.get_token_usage_path", lambda: path)
        yesterday_ts = (datetime.now() - timedelta(days=1)).replace(hour=10, minute=0, second=0).isoformat(timespec="seconds")
        _write_usage(path, [_entry(input=200, output=100, ts=yesterday_ts)])
        out = get_usage_summary(date="yesterday")
        assert "300" in out

    def test_date_filter_specific_date(self, tmp_path, monkeypatch):
        path = tmp_path / "usage.jsonl"
        monkeypatch.setattr("outheis.core.tokens.get_token_usage_path", lambda: path)
        _write_usage(path, [_entry(input=400, output=200, ts="2026-04-10T12:00:00")])
        out = get_usage_summary(date="2026-04-10")
        assert "600" in out

    def test_invalid_date_returns_error_message(self, tmp_path, monkeypatch):
        path = tmp_path / "usage.jsonl"
        monkeypatch.setattr("outheis.core.tokens.get_token_usage_path", lambda: path)
        _write_usage(path, [_entry()])
        out = get_usage_summary(date="not-a-date")
        assert "Invalid date format" in out

    def test_multiple_agents_sorted_by_volume(self, tmp_path, monkeypatch):
        path = tmp_path / "usage.jsonl"
        monkeypatch.setattr("outheis.core.tokens.get_token_usage_path", lambda: path)
        _write_usage(path, [
            _entry(agent="relay", input=100, output=50),
            _entry(agent="pattern", input=5000, output=2000),
        ])
        out = get_usage_summary()
        assert out.index("pattern") < out.index("relay")
