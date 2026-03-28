#!/usr/bin/env python3
"""
Zeno quality comparison test.

Runs a fixed set of zeno-type queries on a local Ollama model and the
configured cloud model, then scores each result against a ground truth.
Produces a side-by-side quality report.

Usage:
    python tools/test_zeno_quality.py
    python tools/test_zeno_quality.py --local gemma4:26b
    python tools/test_zeno_quality.py --local gemma4:26b --timeout 120
    python tools/test_zeno_quality.py --no-cloud   # local model only

Scoring per query (0–3):
    0  no tool calls made (hallucinated or refused)
    1  tool calls made but wrong target / answer incorrect
    2  correct tool calls, answer partially correct
    3  correct tool calls, answer matches ground truth

Requires: pip install openai anthropic
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

SRC_ROOT = str(Path(__file__).parent.parent / "src" / "outheis")

SYSTEM_PROMPT = """You are zeno, the data agent for outheis.
Source root: {src_root}
Use list_files to explore directories. Use search_code to find patterns in Python source.
Always use tools — never guess or hallucinate file paths or counts."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files in a directory",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute directory path"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": "Search for a text pattern in Python source files",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Pattern to search for"},
                    "path": {"type": "string", "description": "Directory to search in (optional)"},
                },
                "required": ["query"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Ground-truth test cases
# Each case:
#   question     : what the user asks
#   expected_tools: tool names that must appear in the call sequence
#   check        : callable(tool_calls, answer) → (score 0-3, note)
# ---------------------------------------------------------------------------

def _count_py_files(path: str) -> int:
    try:
        return len([f for f in os.listdir(path) if f.endswith(".py") and not f.startswith("_")])
    except Exception:
        return -1


AGENTS_DIR = os.path.join(SRC_ROOT, "agents")
CORE_DIR = os.path.join(SRC_ROOT, "core")


def _check_agent_count(tool_calls: list[str], answer: str) -> tuple[int, str]:
    real_count = _count_py_files(AGENTS_DIR)
    used_tool = any("list_files" in c for c in tool_calls)
    if not used_tool:
        return 0, f"no tool call (real count: {real_count})"
    answer_lower = answer.lower()
    if str(real_count) in answer:
        return 3, f"correct ({real_count})"
    for n in range(real_count - 2, real_count + 3):
        if str(n) in answer:
            return 2, f"close (said ~{n}, real {real_count})"
    return 1, f"tool called but count not found in answer (real {real_count})"


def _check_billing_location(tool_calls: list[str], answer: str) -> tuple[int, str]:
    used_search = any("search_code" in c for c in tool_calls)
    if not used_search:
        return 0, "no search_code call"
    if "daemon.py" in answer or "daemon" in answer.lower():
        if "_enter_fallback" in answer or "fallback" in answer.lower():
            return 3, "found daemon.py + fallback reference"
        return 2, "found daemon.py"
    if "fallback" in answer.lower():
        return 1, "mentioned fallback but wrong file"
    return 1, "searched but didn't find daemon.py"


def _check_billing_error_raises(tool_calls: list[str], answer: str) -> tuple[int, str]:
    used_search = any("search_code" in c for c in tool_calls)
    if not used_search:
        return 0, "no search_code call"
    if "llm.py" in answer or "llm" in answer.lower():
        if "BillingError" in answer or "billing" in answer.lower():
            return 3, "found llm.py + BillingError"
        return 2, "found llm.py"
    if "BillingError" in answer or "billing" in answer.lower():
        return 1, "mentioned BillingError but file unclear"
    return 1, "searched but missed llm.py"


def _check_relay_imports(tool_calls: list[str], answer: str) -> tuple[int, str]:
    used_tool = bool(tool_calls)
    if not used_tool:
        return 0, "no tool call"
    # relay.py should import from core (config, llm, i18n, etc.)
    core_imports = ["config", "llm", "i18n", "queue", "message"]
    found = [k for k in core_imports if k in answer.lower()]
    if "relay.py" in answer or "relay" in answer.lower():
        if len(found) >= 3:
            return 3, f"relay.py + core imports: {found}"
        if len(found) >= 1:
            return 2, f"relay.py found, partial imports: {found}"
        return 1, "found relay.py but no core imports listed"
    if found:
        return 1, f"imports mentioned but relay.py not clearly identified"
    return 1, "tool called but answer unhelpful"


def _check_agent_list(tool_calls: list[str], answer: str) -> tuple[int, str]:
    used_tool = any("list_files" in c for c in tool_calls)
    if not used_tool:
        return 0, "no list_files call"
    agents = ["relay", "agenda", "pattern", "data"]
    found = [a for a in agents if a in answer.lower()]
    if len(found) == 4:
        return 3, "all core agents listed"
    if len(found) >= 2:
        return 2, f"partial: {found}"
    return 1, f"tool called but agents missing (found: {found})"


TEST_CASES: list[dict[str, Any]] = [
    {
        "id": "agent-count",
        "question": f"How many Python agent files are in {AGENTS_DIR}? List them.",
        "expected_tools": ["list_files"],
        "check": _check_agent_count,
    },
    {
        "id": "billing-location",
        "question": "In which file is the fallback mode for billing failures implemented? What is the function called?",
        "expected_tools": ["search_code"],
        "check": _check_billing_location,
    },
    {
        "id": "billing-error-raises",
        "question": "Where is BillingError raised in the codebase?",
        "expected_tools": ["search_code"],
        "check": _check_billing_error_raises,
    },
    {
        "id": "relay-imports",
        "question": f"What does the relay agent import from the core module? Look at {SRC_ROOT}/agents/relay.py",
        "expected_tools": ["search_code", "list_files"],
        "check": _check_relay_imports,
    },
    {
        "id": "agent-list",
        "question": f"List all agents in {AGENTS_DIR}/",
        "expected_tools": ["list_files"],
        "check": _check_agent_list,
    },
]


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------

def execute_tool(name: str, args: dict) -> str:
    if name == "list_files":
        path = args.get("path", ".")
        try:
            items = sorted(os.listdir(path))
            visible = [f for f in items if not f.startswith("__")]
            return "\n".join(visible) if visible else "(empty)"
        except Exception as e:
            return f"Error: {e}"
    elif name == "search_code":
        query = args.get("query", "")
        path = args.get("path") or SRC_ROOT
        try:
            result = subprocess.run(
                ["grep", "-r", "-n", "--include=*.py", query, path],
                capture_output=True, text=True, timeout=10,
            )
            lines = [l for l in result.stdout.strip().split("\n") if l]
            if not lines:
                return f"No matches for '{query}'"
            return "\n".join(lines[:20])
        except Exception as e:
            return f"Search error: {e}"
    return f"Unknown tool: {name}"


# ---------------------------------------------------------------------------
# Model runner — works for both Ollama (OpenAI-compat) and Anthropic
# ---------------------------------------------------------------------------

def run_query_ollama(client, model: str, question: str, timeout: int) -> tuple[list[str], str, float]:
    t0 = time.time()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT.format(src_root=SRC_ROOT)},
        {"role": "user", "content": question},
    ]
    tool_calls_made = []
    for _ in range(6):
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=TOOLS,
            max_tokens=400,
            timeout=timeout,
        )
        choice = resp.choices[0]
        if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
            tc = choice.message.tool_calls[0]
            args = json.loads(tc.function.arguments)
            result = execute_tool(tc.function.name, args)
            tool_calls_made.append(tc.function.name)
            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }],
            })
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
        else:
            return tool_calls_made, (choice.message.content or "").strip(), time.time() - t0
    return tool_calls_made, "(max iterations)", time.time() - t0


def run_query_anthropic(model: str, question: str, timeout: int) -> tuple[list[str], str, float]:
    import anthropic
    # Load API key from outheis config
    config_path = Path.home() / ".outheis" / "human" / "config.json"
    api_key = json.loads(config_path.read_text())["llm"]["providers"]["anthropic"]["api_key"]

    client = anthropic.Anthropic(api_key=api_key)
    anthr_tools = [
        {
            "name": t["function"]["name"],
            "description": t["function"]["description"],
            "input_schema": t["function"]["parameters"],
        }
        for t in TOOLS
    ]
    messages = [{"role": "user", "content": question}]
    tool_calls_made = []
    t0 = time.time()

    for _ in range(6):
        resp = client.messages.create(
            model=model,
            system=SYSTEM_PROMPT.format(src_root=SRC_ROOT),
            messages=messages,
            tools=anthr_tools,
            max_tokens=400,
        )
        if resp.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": resp.content})
            tool_results = []
            for block in resp.content:
                if block.type == "tool_use":
                    result = execute_tool(block.name, block.input)
                    tool_calls_made.append(block.name)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })
            messages.append({"role": "user", "content": tool_results})
        else:
            text = "".join(
                b.text for b in resp.content if hasattr(b, "text")
            ).strip()
            return tool_calls_made, text, time.time() - t0

    return tool_calls_made, "(max iterations)", time.time() - t0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def score_label(s: int) -> str:
    return ["✗ 0", "~ 1", "◑ 2", "✓ 3"][s]


def run_model(label: str, runner, cases: list[dict]) -> list[dict]:
    results = []
    for case in cases:
        try:
            calls, answer, elapsed = runner(case["question"])
            score, note = case["check"](calls, answer)
            results.append({
                "id": case["id"],
                "score": score,
                "note": note,
                "calls": calls,
                "elapsed": elapsed,
                "answer": answer[:120].replace("\n", " "),
            })
        except Exception as e:
            results.append({
                "id": case["id"],
                "score": 0,
                "note": f"ERROR: {e}",
                "calls": [],
                "elapsed": 0.0,
                "answer": "",
            })
        print(f"  [{score_label(results[-1]['score'])}] {case['id']}  ({results[-1]['elapsed']:.1f}s)  {results[-1]['note']}", flush=True)
    return results


def main():
    parser = argparse.ArgumentParser(description="Zeno quality comparison: local vs cloud")
    parser.add_argument("--local", default="gemma4:26b", help="Local Ollama model")
    parser.add_argument("--cloud", default="claude-haiku-4-5-20251001", help="Cloud model (Anthropic)")
    parser.add_argument("--ollama-url", default="http://localhost:11434", help="Ollama base URL")
    parser.add_argument("--timeout", type=int, default=120, help="Per-query timeout (seconds)")
    parser.add_argument("--no-cloud", action="store_true", help="Skip cloud model")
    parser.add_argument("--no-local", action="store_true", help="Skip local model")
    args = parser.parse_args()

    try:
        from openai import OpenAI
    except ImportError:
        print("ERROR: pip install openai anthropic")
        sys.exit(1)

    ollama_client = OpenAI(base_url=f"{args.ollama_url}/v1", api_key="ollama")

    all_results = {}

    if not args.no_local:
        print(f"\n── Local: {args.local} ──────────────────────────────────")
        def local_runner(q):
            return run_query_ollama(ollama_client, args.local, q, args.timeout)
        all_results["local"] = run_model(args.local, local_runner, TEST_CASES)

    if not args.no_cloud:
        print(f"\n── Cloud: {args.cloud} ──────────────────────────────────")
        def cloud_runner(q):
            return run_query_anthropic(args.cloud, q, args.timeout)
        all_results["cloud"] = run_model(args.cloud, cloud_runner, TEST_CASES)

    # Summary table
    print(f"\n{'':─<70}")
    print(f"{'Query ID':<20} ", end="")
    for label in all_results:
        print(f"{label:>12} ", end="")
    print()
    print(f"{'':─<70}")

    for case in TEST_CASES:
        print(f"{case['id']:<20} ", end="")
        for label, results in all_results.items():
            r = next(r for r in results if r["id"] == case["id"])
            print(f"{score_label(r['score']):>12} ", end="")
        print()

    print(f"{'':─<70}")
    print(f"{'TOTAL (max ' + str(3 * len(TEST_CASES)) + ')':<20} ", end="")
    for label, results in all_results.items():
        total = sum(r["score"] for r in results)
        print(f"{total:>12} ", end="")
    print()
    print()


if __name__ == "__main__":
    main()
