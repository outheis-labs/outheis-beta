"""
Token usage tracking.

Records per-call usage to ~/.outheis/human/token_usage.jsonl.
Provides 7-day stats grouped into 4×6h periods per day,
and a human-readable usage/cost summary for any time window.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

# Approximate cost per 1M tokens (input, output) in USD — Anthropic list prices
_MODEL_COSTS: dict[str, tuple[float, float]] = {
    "haiku":  (0.80,  4.00),   # claude-haiku-4-5*
    "sonnet": (3.00,  15.00),  # claude-sonnet-4-5*, claude-sonnet-4-6*
    "opus":   (15.00, 75.00),  # claude-opus-4*
}


def _model_cost(model: str) -> tuple[float, float]:
    """Return (input_$/MTok, output_$/MTok) for a given model name."""
    m = model.lower()
    for key, costs in _MODEL_COSTS.items():
        if key in m:
            return costs
    return (3.00, 15.00)  # fallback: sonnet pricing


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


def get_usage_summary(days: int = 7, date: str | None = None) -> str:
    """
    Return a human-readable token usage and estimated cost summary.

    Args:
        days: rolling look-back window in days (ignored when date is set)
        date: specific calendar day as YYYY-MM-DD (e.g. "2026-04-04")
              "today" and "yesterday" are also accepted
    """
    from datetime import date as date_type

    path = get_token_usage_path()
    now = datetime.now()

    # Resolve date → calendar-day boundaries
    if date:
        d = date.strip().lower()
        if d in ("today", "today"):
            target = now.date()
        elif d in ("yesterday", "yesterday"):
            target = (now - timedelta(days=1)).date()
        else:
            try:
                target = date_type.fromisoformat(d)
            except ValueError:
                return f"Invalid date format: '{date}'. Use YYYY-MM-DD."
        cutoff_low  = datetime(target.year, target.month, target.day, 0, 0, 0)
        cutoff_high = datetime(target.year, target.month, target.day, 23, 59, 59)
        label = target.strftime("%d.%m.%Y")
        no_data_label = f"am {label}"
    else:
        cutoff_low  = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
        cutoff_high = now
        label = "today" if days == 1 else f"last {days} days"
        no_data_label = "today" if days == 1 else f"last {days} days"

    if not path.exists():
        return f"No token data for {no_data_label}."

    total_input = 0
    total_output = 0
    total_cost = 0.0
    by_agent: dict[str, dict] = {}

    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                ts = datetime.fromisoformat(entry["ts"])
                if ts < cutoff_low or ts > cutoff_high:
                    continue
                inp = entry.get("input", 0)
                out = entry.get("output", 0)
                model = entry.get("model", "unknown")
                agent = entry.get("agent", "unknown")
                input_rate, output_rate = _model_cost(model)
                cost = (inp * input_rate + out * output_rate) / 1_000_000

                total_input += inp
                total_output += out
                total_cost += cost

                if agent not in by_agent:
                    by_agent[agent] = {"input": 0, "output": 0, "cost": 0.0}
                by_agent[agent]["input"] += inp
                by_agent[agent]["output"] += out
                by_agent[agent]["cost"] += cost
            except (json.JSONDecodeError, KeyError, ValueError):
                continue

    total_tokens = total_input + total_output
    if total_tokens == 0:
        return f"No token usage recorded for {no_data_label}."

    lines = [
        f"Token usage ({label})",
        f"Total: {total_tokens:,} tokens  (input: {total_input:,} / output: {total_output:,})",
        f"Estimated cost: ${total_cost:.4f}  (approximate, Anthropic list prices)",
        "",
        "By agent:",
    ]
    for agent, s in sorted(by_agent.items(), key=lambda x: -(x[1]["input"] + x[1]["output"])):
        t = s["input"] + s["output"]
        lines.append(f"  {agent:10s}  {t:>8,} Tokens  ${s['cost']:.4f}")

    return "\n".join(lines)
