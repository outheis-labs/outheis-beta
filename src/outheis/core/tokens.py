"""
Token usage tracking.

Records per-call usage to ~/.outheis/human/token_usage.jsonl.
Provides 7-day stats grouped into 4×6h periods per day.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path


def get_token_usage_path() -> Path:
    from outheis.core.config import get_human_dir
    return get_human_dir() / "token_usage.jsonl"


def record_usage(agent: str, model: str, input_tokens: int, output_tokens: int) -> None:
    """Append one usage record."""
    path = get_token_usage_path()
    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "agent": agent,
        "model": model,
        "input": input_tokens,
        "output": output_tokens,
    }
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def get_stats_7days() -> dict:
    """
    Return token usage for the last 7 days, each day split into 4×6h periods.

    Returns:
        {
          "days": [{"date": "YYYY-MM-DD", "label": "Mon", "periods": [t0, t1, t2, t3]}, ...],
          "total_7d": int
        }
    """
    now = datetime.now()
    days = []
    for d in range(6, -1, -1):
        day = now - timedelta(days=d)
        days.append({
            "date": day.strftime("%Y-%m-%d"),
            "label": day.strftime("%a"),
            "periods": [0, 0, 0, 0],
        })

    path = get_token_usage_path()
    if not path.exists():
        return {"days": days, "total_7d": 0}

    cutoff = now - timedelta(days=7)
    total = 0

    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                ts = datetime.fromisoformat(entry["ts"])
                if ts < cutoff:
                    continue
                tokens = entry.get("input", 0) + entry.get("output", 0)
                total += tokens
                period = ts.hour // 6
                date_str = ts.strftime("%Y-%m-%d")
                for day in days:
                    if day["date"] == date_str:
                        day["periods"][period] += tokens
                        break
            except (json.JSONDecodeError, KeyError, ValueError):
                continue

    return {"days": days, "total_7d": total}
