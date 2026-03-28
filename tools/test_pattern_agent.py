#!/usr/bin/env python3
from __future__ import annotations
"""
Pattern agent (rumi) capability test for Ollama models.

Tests the five phases of run_scheduled() with realistic inputs:
  1. extract   — conversation → typed memory entries
  2. consolidate — memory store → remove duplicates/contradictions
  3. distill   — memory → condensed skills  (THE CENTRAL MECHANISM)
  4. promote   — memory → stable rules
  5. validate  — meta-learning reflection

All prompts mirror what pattern.py actually sends to the LLM.
Output quality is judged, not just JSON validity.

Usage:
  python tools/test_pattern_agent.py --models gemma4:26b mistral-nemo:12b
  python tools/test_pattern_agent.py  (tests all models in config)
"""

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Any

BASE_URL = "http://localhost:11434/v1"
TIMEOUT = 300


# =============================================================================
# OLLAMA CLIENT
# =============================================================================

def call_model(model: str, system: str, user: str, *, temperature: float = 0.2) -> str:
    try:
        from openai import OpenAI
    except ImportError:
        print("ERROR: openai package not installed. Run: pip3 install openai")
        sys.exit(1)

    client = OpenAI(base_url=BASE_URL, api_key="ollama")
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
        timeout=TIMEOUT,
    )
    return resp.choices[0].message.content or ""


def parse_json(text: str) -> dict | None:
    """Strip optional markdown fences and parse JSON."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    if text.startswith("json"):
        text = text[4:].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


# =============================================================================
# SYSTEM PROMPT (minimal, matches rumi's actual context at cold start)
# =============================================================================

RUMI_SYSTEM = """You are rumi, the Pattern Agent of outheis.

Your role: observe, distill, promote.
- Extract memorable information from conversations
- Consolidate memory (remove duplicates, resolve contradictions)
- Distill skills: condense many observations into few principles
- Promote stable constraints to rules
- Learn how to learn

Always respond with valid JSON only — no markdown fences, no extra text."""


# =============================================================================
# SCENARIO DEFINITIONS
# =============================================================================

@dataclass
class Scenario:
    name: str
    phase: str          # extract | consolidate | distill | promote | validate
    prompt: str         # user-turn content
    verdict_fn: Any     # callable(data: dict) -> tuple[str, str]  (verdict, detail)
    description: str = ""


def verdict(sym: str, detail: str = "") -> tuple[str, str]:
    return sym, detail


# ---------------------------------------------------------------------------
# PHASE 1 — EXTRACT
# ---------------------------------------------------------------------------

EXTRACT_PROMPT = """\
Current memory (don't repeat this):
(empty)

---

Recent conversation:
User: I'm Alice. I work on outheis, a privacy-focused AI assistant.
User: Please keep your responses short and direct — no fluff.
User: I have a hard deadline for the outheis-beta release this Friday.

---

Extract any NEW information worth remembering. Use your judgment — don't be mechanical.

Respond with JSON:
{
  "extractions": [
    {"type": "user|feedback|context", "content": "...", "confidence": 0.0-1.0, "decay_days": null}
  ],
  "reasoning": "Brief explanation"
}"""


def check_extract_basic(data: dict) -> tuple[str, str]:
    exts = data.get("extractions", [])
    if not exts:
        return verdict("✗", "no extractions")
    types = {e.get("type") for e in exts}
    has_user = "user" in types
    has_feedback = "feedback" in types
    has_context = "context" in types
    contents = " ".join(e.get("content", "").lower() for e in exts)
    has_name = "alice" in contents
    has_pref = any(w in contents for w in ["short", "concise", "brief", "direct"])
    has_deadline = any(w in contents for w in ["deadline", "friday", "release"])
    hits = sum([has_user and has_name, has_feedback and has_pref, has_context and has_deadline])
    if hits == 3:
        return verdict("✓", f"{len(exts)} extractions, all 3 types correct")
    if hits >= 2:
        return verdict("~", f"{len(exts)} extractions, {hits}/3 correct")
    return verdict("✗", f"only {hits}/3 correctly classified")


EXTRACT_EMPTY_PROMPT = """\
Current memory (don't repeat this):
(empty)

---

Recent conversation:
User: what is 2 + 2?
User: thanks
User: can you recommend a good movie?

---

Extract any NEW information worth remembering. Use your judgment — don't be mechanical.

Respond with JSON:
{
  "extractions": [
    {"type": "user|feedback|context", "content": "...", "confidence": 0.0-1.0, "decay_days": null}
  ],
  "reasoning": "Brief explanation"
}"""


def check_extract_empty(data: dict) -> tuple[str, str]:
    exts = data.get("extractions", [])
    if not exts:
        return verdict("✓", "correctly returned empty")
    # Allow low-confidence / low-content entries as partial
    high_conf = [e for e in exts if e.get("confidence", 1.0) >= 0.7]
    if not high_conf:
        return verdict("~", f"{len(exts)} low-confidence entries (acceptable)")
    return verdict("✗", f"{len(high_conf)} high-confidence extractions from casual chat (hallucination risk)")


# ---------------------------------------------------------------------------
# PHASE 2 — CONSOLIDATE
# ---------------------------------------------------------------------------

CONSOLIDATE_DUPLICATE_PROMPT = """\
Review this memory for consolidation. Look for:
- Duplicates (same information stated differently)
- Contradictions (conflicting facts)
- Superseded entries (newer info makes older obsolete)
- Expired or no longer relevant context

CURRENT MEMORY:
{
  "user": [
    [0, {"content": "User is named Alice", "created_at": "2026-03-01", "confidence": 0.9}],
    [1, {"content": "The user's name is Alice Smith", "created_at": "2026-03-05", "confidence": 0.95}],
    [2, {"content": "User goes by Alice", "created_at": "2026-03-10", "confidence": 0.8}],
    [3, {"content": "User is a software developer", "created_at": "2026-03-01", "confidence": 0.9}]
  ],
  "feedback": [],
  "context": []
}

For each action needed, respond with:
{
  "actions": [
    {"type": "remove", "memory_type": "user", "index": 0, "reason": "Duplicate of index 1"}
  ],
  "reasoning": "Brief explanation of what you consolidated"
}

If nothing needs consolidation:
{"actions": [], "reasoning": "Memory is clean"}

Be conservative - only remove entries when clearly redundant or wrong."""


def check_consolidate_duplicates(data: dict) -> tuple[str, str]:
    actions = data.get("actions", [])
    removals = [a for a in actions if a.get("type") == "remove" and a.get("memory_type") == "user"]
    # Should remove 2 of the 3 name duplicates (indices 0,1,2) — keep 1
    removed_indices = {a.get("index") for a in removals}
    name_indices = {0, 1, 2}
    removed_name = removed_indices & name_indices
    dev_removed = 3 in removed_indices  # should NOT remove the developer entry
    if len(removed_name) == 2 and not dev_removed:
        return verdict("✓", f"removed {sorted(removed_name)} (2 name duplicates, kept 1 + dev entry)")
    if len(removed_name) >= 1 and not dev_removed:
        return verdict("~", f"removed {sorted(removed_name)} name duplicates (expected 2), kept dev entry")
    if dev_removed:
        return verdict("✗", "incorrectly removed non-duplicate developer entry")
    return verdict("✗", f"no name duplicates removed (actions: {actions})")


CONSOLIDATE_CONTRADICTION_PROMPT = """\
Review this memory for consolidation. Look for:
- Duplicates (same information stated differently)
- Contradictions (conflicting facts)
- Superseded entries (newer info makes older obsolete)

CURRENT MEMORY:
{
  "user": [],
  "feedback": [
    [0, {"content": "User prefers verbose, detailed responses with full explanations", "created_at": "2026-02-01", "confidence": 0.7}],
    [1, {"content": "User explicitly asked for short, concise replies — no fluff", "created_at": "2026-03-15", "confidence": 0.95}]
  ],
  "context": []
}

Respond with JSON (same format as before). Be conservative."""


def check_consolidate_contradiction(data: dict) -> tuple[str, str]:
    actions = data.get("actions", [])
    removals = [a for a in actions if a.get("type") == "remove" and a.get("memory_type") == "feedback"]
    removed = {a.get("index") for a in removals}
    if 0 in removed and 1 not in removed:
        return verdict("✓", "removed older contradicted entry (index 0), kept newer (index 1)")
    if removed == {0, 1}:
        return verdict("~", "removed both — could keep the newer one")
    if 1 in removed and 0 not in removed:
        return verdict("✗", "removed newer entry, kept contradicted older one")
    if not removed:
        return verdict("~", "no action — contradiction unresolved (acceptable if conservative)")
    return verdict("~", f"partial: removed {sorted(removed)}")


CONSOLIDATE_CLEAN_PROMPT = """\
Review this memory for consolidation.

CURRENT MEMORY:
{
  "user": [
    [0, {"content": "User is a software developer working on outheis", "created_at": "2026-03-01", "confidence": 0.9}],
    [1, {"content": "User's primary language is German", "created_at": "2026-03-01", "confidence": 0.9}]
  ],
  "feedback": [
    [0, {"content": "User prefers concise responses", "created_at": "2026-03-10", "confidence": 0.95}]
  ],
  "context": []
}

Respond with JSON. Be conservative - only remove entries when clearly redundant or wrong."""


def check_consolidate_clean(data: dict) -> tuple[str, str]:
    actions = data.get("actions", [])
    if not actions:
        return verdict("✓", "correctly took no action on clean memory")
    removals = [a for a in actions if a.get("type") == "remove"]
    if removals:
        return verdict("✗", f"removed {len(removals)} entries from clean memory (over-aggressive)")
    return verdict("~", f"non-removal actions on clean memory: {actions}")


# ---------------------------------------------------------------------------
# PHASE 3 — DISTILL  (central mechanism)
# ---------------------------------------------------------------------------

DISTILL_READY_PROMPT = """\
You are the Pattern Agent — the learning engine of outheis.

Your task: DISTILL SKILLS from observations.

## The Attention Hierarchy

Skills > Memory > Rules

- **Skills** (highest density): Condensed principles that direct attention.
  A good skill makes 10 memory entries obsolete.

- **Memory** (medium density): Facts and observations.
  Raw material for skill distillation.

## Current State

### Memory (raw observations):
[feedback] User corrected the date format from DD.MM.YYYY to ISO (2026-02-10)
[feedback] User changed "15. March" to "2026-03-15" and asked to always use ISO dates (2026-02-18)
[feedback] User explicitly asked for ISO date format again after agent used "March 20th" (2026-03-20)
[feedback] Agent used "next Monday" — user corrected to explicit date (2026-03-25)
[user] User is a software developer (2026-03-01)

### Current Skills:
(none yet)

### Current Rules:
(none)

## Your Task

Look for patterns that can be DISTILLED into skills.
Example: 3+ corrections about same topic → extract the principle.

Respond with JSON:
{
  "skill_updates": [
    {
      "agent": "common|relay|data|agenda|action",
      "action": "add|update|merge",
      "content": "The skill principle (one clear line)",
      "reasoning": "Why this distillation",
      "obsoletes_memory": ["list of memory entries this replaces"]
    }
  ],
  "no_distillation_reason": "If nothing to distill, explain why"
}

If nothing is ready: {"skill_updates": [], "no_distillation_reason": "..."}"""


def check_distill_ready(data: dict) -> tuple[str, str]:
    updates = data.get("skill_updates", [])
    if not updates:
        return verdict("✗", f"no distillation: {data.get('no_distillation_reason', '')[:60]}")
    u = updates[0]
    content = u.get("content", "").lower()
    has_iso = any(w in content for w in ["iso", "yyyy-mm-dd", "yyyy", "date format"])
    obsoletes = u.get("obsoletes_memory", [])
    agent = u.get("agent", "")
    if has_iso and len(obsoletes) >= 2 and agent in ("common", "relay", "data", "agenda", "action"):
        return verdict("✓", f"skill: '{u['content'][:60]}', obsoletes {len(obsoletes)}")
    if has_iso:
        return verdict("~", f"skill content ok ('{u['content'][:50]}') but obsoletes={len(obsoletes)}, agent='{agent}'")
    return verdict("✗", f"skill doesn't capture ISO date principle: '{u.get('content','')[:60]}'")


DISTILL_NOT_READY_PROMPT = """\
You are the Pattern Agent — the learning engine of outheis.

## Current State

### Memory (raw observations):
[user] User mentioned they drink coffee in the morning (2026-03-20)
[user] User is named Alice (2026-03-01)
[context] User is currently working on a release deadline (2026-04-01)

### Current Skills:
(none yet)

### Current Rules:
(none)

## Your Task

Look for patterns ready for skill distillation. Only distill when pattern is clear (3+ instances).

Respond with JSON:
{
  "skill_updates": [...],
  "no_distillation_reason": "If nothing to distill, explain why"
}"""


def check_distill_not_ready(data: dict) -> tuple[str, str]:
    updates = data.get("skill_updates", [])
    reason = data.get("no_distillation_reason", "")
    if not updates and reason:
        return verdict("✓", f"correctly held back: '{reason[:60]}'")
    if not updates:
        return verdict("~", "no distillation but no reason given")
    # Check if any update is based on single instances (hallucinated pattern)
    return verdict("✗", f"distilled {len(updates)} skill(s) from single observations (premature)")


DISTILL_QUALITY_PROMPT = """\
You are the Pattern Agent — the learning engine of outheis.

## Current State

### Memory (raw observations):
[feedback] User said "too long" and asked for shorter answer (2026-02-05)
[feedback] User: "please be more concise, I don't need the background" (2026-02-12)
[feedback] User cut off a long explanation and said "just the answer" (2026-02-20)
[feedback] User: "shorter please" (2026-03-01)
[feedback] User explicitly praised a short, direct answer (2026-03-10)

### Current Skills:
(none yet)

### Current Rules:
(none)

## Your Task

Distill these observations into a single actionable skill principle.
The skill should be GENERAL (applies to all future interactions), not a paraphrase of one entry.
A good skill: "Responses: keep short and direct — no background unless asked"
A bad skill: "User said 'too long' on 2026-02-05" (too specific, just a copy)

Respond with JSON (same format as before)."""


def check_distill_quality(data: dict) -> tuple[str, str]:
    updates = data.get("skill_updates", [])
    if not updates:
        return verdict("✗", f"no distillation: {data.get('no_distillation_reason', '')[:60]}")
    u = updates[0]
    content = u.get("content", "")
    content_lower = content.lower()
    # Bad: just copies a specific memory entry verbatim
    specific_copies = [
        "too long", "2026-02-05", "just the answer", "shorter please"
    ]
    is_copy = any(s in content_lower for s in specific_copies) and len(content) < 40
    # Good: general principle about brevity
    is_general = any(w in content_lower for w in ["concise", "short", "brief", "direct", "terse"])
    is_principle = len(content) > 15 and ":" in content or len(content.split()) >= 5
    if is_general and is_principle and not is_copy:
        return verdict("✓", f"general principle: '{content[:70]}'")
    if is_general and is_copy:
        return verdict("~", f"correct topic but too specific: '{content[:60]}'")
    if not is_general:
        return verdict("✗", f"skill doesn't capture brevity principle: '{content[:60]}'")
    return verdict("~", f"'{content[:60]}'")


# ---------------------------------------------------------------------------
# PHASE 4 — PROMOTE TO RULES
# ---------------------------------------------------------------------------

PROMOTE_PROMPT = """\
Review this Memory and consider if any patterns are stable enough to become User Rules.

CURRENT MEMORY:
[feedback] User corrected date format to ISO three times — always use YYYY-MM-DD (confidence: 0.95)
[feedback] User asked for short responses repeatedly (confidence: 0.95)
[feedback] User mentioned once that they like jazz (confidence: 0.6)
[context] User is working on a release this week (confidence: 0.8)

CURRENT USER RULES:
(none)

User Rules are persistent behavioral guidelines. They should be:
- Clearly established and stable
- Genuinely helpful for future interactions
- Not contradicted by the user

Respond with JSON:
{
  "new_rules": [
    {"agent": "relay|data|agenda|common", "rule": "Clear, actionable statement"}
  ],
  "reasoning": "Why these are worth promoting"
}

If nothing is ready: {"new_rules": [], "reasoning": "Why not"}"""


def check_promote(data: dict) -> tuple[str, str]:
    rules = data.get("new_rules", [])
    if not rules:
        return verdict("✗", "no rules promoted from clearly stable patterns")
    rule_texts = " ".join(r.get("rule", "").lower() for r in rules)
    has_date = any(w in rule_texts for w in ["iso", "yyyy", "date"])
    has_brevity = any(w in rule_texts for w in ["short", "concise", "brief", "direct"])
    has_jazz = "jazz" in rule_texts  # should NOT be promoted (low confidence, irrelevant)
    has_deadline = any(w in rule_texts for w in ["deadline", "release", "this week"])  # context, not rule
    if has_jazz:
        return verdict("✗", "promoted low-confidence irrelevant preference (jazz) as rule")
    if has_deadline:
        return verdict("✗", "promoted temporary context (deadline) as permanent rule")
    promoted = sum([has_date, has_brevity])
    if promoted == 2:
        return verdict("✓", f"{len(rules)} rules: date format + brevity (no false positives)")
    if promoted >= 1:
        return verdict("~", f"{len(rules)} rules, {promoted}/2 correct (date={has_date}, brevity={has_brevity})")
    return verdict("✗", f"rules don't capture stable patterns: {[r.get('rule','')[:40] for r in rules]}")


# ---------------------------------------------------------------------------
# PHASE 5 — VALIDATE (meta-learning)
# ---------------------------------------------------------------------------

VALIDATE_PROMPT = """\
Reflect on your extraction strategies.

YOUR CURRENT STRATEGIES/LEARNINGS:
(none yet)

CURRENT USER MEMORY STATE:
[user] User is named Alice (confidence: 0.9)
[feedback] User prefers concise responses (confidence: 0.95)
[feedback] User uses ISO date format (confidence: 0.95)

Consider:
- What extraction approaches have worked well?
- What should you pay more attention to?
- What should you ignore?

If you have insights worth recording, respond with:
{
  "insight": "Your learning or strategy refinement",
  "should_record": true
}

If nothing new:
{
  "insight": "",
  "should_record": false
}"""


def check_validate(data: dict) -> tuple[str, str]:
    should = data.get("should_record", False)
    insight = data.get("insight", "").strip()
    # Both true and false are acceptable — just needs valid JSON and non-hallucinated insight
    if should and insight:
        # Check it's not obviously hallucinated (doesn't reference things not in input)
        hallucination_markers = ["python", "github", "outheis-beta", "signal", "vault"]
        if any(m in insight.lower() for m in hallucination_markers):
            return verdict("~", f"insight references undisclosed context: '{insight[:60]}'")
        return verdict("✓", f"recorded insight: '{insight[:60]}'")
    if not should and not insight:
        return verdict("✓", "correctly found nothing new to record")
    if not should and insight:
        return verdict("~", "has insight but chose not to record (acceptable)")
    return verdict("✗", "should_record=true but no insight content")


# ---------------------------------------------------------------------------
# JSON VALIDITY CHECK (applied to all scenarios)
# ---------------------------------------------------------------------------

def check_json(raw: str) -> bool:
    return parse_json(raw) is not None


# =============================================================================
# SCENARIO REGISTRY
# =============================================================================

SCENARIOS: list[Scenario] = [
    Scenario("extract_basic",            "extract",     EXTRACT_PROMPT,                  check_extract_basic,
             "conversation → 3 typed extractions (user/feedback/context)"),
    Scenario("extract_empty",            "extract",     EXTRACT_EMPTY_PROMPT,            check_extract_empty,
             "casual chat → no memorable content"),
    Scenario("consolidate_duplicates",   "consolidate", CONSOLIDATE_DUPLICATE_PROMPT,    check_consolidate_duplicates,
             "3 duplicate name entries → remove 2, keep distinct entry"),
    Scenario("consolidate_contradiction","consolidate", CONSOLIDATE_CONTRADICTION_PROMPT, check_consolidate_contradiction,
             "contradiction → remove older conflicting entry"),
    Scenario("consolidate_clean",        "consolidate", CONSOLIDATE_CLEAN_PROMPT,        check_consolidate_clean,
             "clean memory → no action (conservative)"),
    Scenario("distill_ready",            "distill",     DISTILL_READY_PROMPT,            check_distill_ready,
             "4 date-format corrections → distill ISO date skill"),
    Scenario("distill_not_ready",        "distill",     DISTILL_NOT_READY_PROMPT,        check_distill_not_ready,
             "single observations → hold back, not ready"),
    Scenario("distill_quality",          "distill",     DISTILL_QUALITY_PROMPT,          check_distill_quality,
             "5 brevity corrections → general principle, not instance copy"),
    Scenario("promote_rules",            "promote",     PROMOTE_PROMPT,                  check_promote,
             "stable patterns → promote 2 rules, skip low-confidence/context"),
    Scenario("validate_meta",            "validate",    VALIDATE_PROMPT,                 check_validate,
             "meta-learning reflection → valid insight or nothing"),
]


# =============================================================================
# RUNNER
# =============================================================================

VERDICT_SYMBOLS = {"✓": "OK", "~": "partial", "✗": "fail", "J": "json_err"}


def run_model(model: str, verbose: bool = False) -> None:
    width = 26
    print(f"\n{'='*80}")
    print(f"Model: {model}")
    print(f"{'='*80}")
    header = f"  {'Scenario':<{width}} {'V':<3} {'Phase':<12} {'Time':>5}  Detail"
    print(header)
    print("-" * 80)

    ok = partial = fail = json_err = 0

    for sc in SCENARIOS:
        t0 = time.time()
        try:
            raw = call_model(model, RUMI_SYSTEM, sc.prompt)
        except Exception as e:
            elapsed = time.time() - t0
            print(f"  {sc.name:<{width}} {'E':<3} {sc.phase:<12} {elapsed:>4.0f}s  ERROR: {e}")
            fail += 1
            continue

        elapsed = time.time() - t0

        if not check_json(raw):
            sym, detail = "J", f"invalid JSON — raw: {raw[:60]!r}"
            json_err += 1
        else:
            data = parse_json(raw)
            sym, detail = sc.verdict_fn(data)
            if sym == "✓":
                ok += 1
            elif sym == "~":
                partial += 1
            else:
                fail += 1

        print(f"  {sc.name:<{width}} {sym:<3} {sc.phase:<12} {elapsed:>4.0f}s  {detail[:55]}")

        if verbose:
            print(f"    raw: {raw[:120]!r}")

    total = len(SCENARIOS)
    print(f"\n  Summary: {ok}/{total} OK, {partial} partial, {fail} fail"
          + (f", {json_err} json_err" if json_err else ""))


# =============================================================================
# MAIN
# =============================================================================

def available_models() -> list[str]:
    try:
        import subprocess
        out = subprocess.check_output(["ollama", "list"], text=True)
        models = []
        for line in out.strip().splitlines()[1:]:
            name = line.split()[0]
            if name:
                models.append(name)
        return models
    except Exception:
        return []


def main() -> None:
    parser = argparse.ArgumentParser(description="Pattern agent capability test")
    parser.add_argument("--models", nargs="*", help="Models to test (default: all local)")
    parser.add_argument("--url", default=None, help="Ollama API URL")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    global BASE_URL
    if args.url:
        BASE_URL = args.url

    models = args.models or available_models()
    if not models:
        print("No models found. Pass --models <name> or make sure ollama is running.")
        sys.exit(1)

    for model in models:
        run_model(model, verbose=args.verbose)

    print()


if __name__ == "__main__":
    main()
