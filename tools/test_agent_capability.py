#!/usr/bin/env python3
from __future__ import annotations
"""
Agent capability test for Ollama models.

Tests models under realistic outheis agent conditions:
full system prompts with user memory and vault context,
multi-turn tool chains, error recovery, hallucination detection.

Complements test_ollama_tool_use.py (minimal prompt, single call).
Use this to find the lower bound for usable local models.

Usage:
    python tools/test_agent_capability.py
    python tools/test_agent_capability.py --models llama3.1:8b devstral-small-2:24b
    python tools/test_agent_capability.py --agents relay data agenda
    python tools/test_agent_capability.py --verbose
    python tools/test_agent_capability.py --timeout 120
"""

import argparse
import json
import time

# =============================================================================
# FAKE USER CONTEXT  (realistic but non-personal)
# =============================================================================

FAKE_MEMORY = """\
## Traits
- prefers concise responses
- works on outheis, a local privacy-first AI assistant system
- speaks German, responds in German by default

## Context
- currently developing the action agent (hiro) with MCP integration
- hardware migration to Apple M5 planned for summer 2026
- tests local models to find the lower capability bound
"""

FAKE_VAULT_STRUCTURE = """\
Vault root: /Users/alice/Documents/Vault

Directory listing:
  Daily/
    2026-04-04.md
    2026-04-03.md
    2026-04-02.md
  Projects/
    outheis-dev.md        (tags: project, dev, active)
    research-notes.md     (tags: research, active)
    budget-2025.md        (tags: finance, archived)
  People/
    contacts.md           (tags: contacts)
  Archive/
    2025/
"""

FAKE_DAILY_2026_04_04 = """\
# 2026-04-04

## Appointments
- 10:00 Call with Stefan (Infra-Review)
- 14:00 outheis Architecture-Review

## Tasks
- [ ] MCP integration for hiro
- [ ] Test local models
- [x] Relay interim messages

## Notes
RAM for M5: at least 32 GB planned.
"""

FAKE_PROJECT_FILE = """\
# outheis-dev

Status: active
Tags: project, dev, active

## Status
- relay: done
- data, agenda: done
- action (hiro): in progress — MCP integration pending
- pattern: done

## Next Steps
- Implement MCP client in hiro
- Dispatcher manages server lifecycle
"""


# =============================================================================
# TOOL DEFINITIONS  (OpenAI format, per agent type)
# =============================================================================

RELAY_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "ask_data",
            "description": "Delegate a question about vault files or content to the data agent (zeno).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Question about vault content"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_agenda",
            "description": "Delegate a schedule or calendar question to the agenda agent (cato).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Question about schedule, agenda, or daily note"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": "Save a piece of information to persistent user memory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "type": {"type": "string", "enum": ["fact", "preference", "context"]},
                },
                "required": ["content", "type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_token_usage",
            "description": "Return token usage statistics for agents.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "Date in YYYY-MM-DD, or 'heute', 'gestern'"},
                },
                "required": [],
            },
        },
    },
]

DATA_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_vault_files",
            "description": "List files in a vault directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "directory": {"type": "string", "description": "Subdirectory relative to vault root (e.g. 'Projects/')"},
                },
                "required": ["directory"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_vault_file",
            "description": "Read the content of a vault file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path relative to vault root"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_vault",
            "description": "Search vault files by text pattern or tags.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Text pattern to search for"},
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Filter by tags",
                    },
                    "directory": {"type": "string", "description": "Limit search to this directory"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "scan_tags",
            "description": "Return all tags used in the vault with file counts.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]

AGENDA_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_daily",
            "description": "Read the daily note for a given date.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "Date in YYYY-MM-DD format"},
                },
                "required": ["date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_daily",
            "description": "Write or update the daily note for a given date.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["date", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_event",
            "description": "Add an event to the daily note.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string"},
                    "time": {"type": "string"},
                    "title": {"type": "string"},
                },
                "required": ["date", "time", "title"],
            },
        },
    },
]


# =============================================================================
# SYSTEM PROMPTS  (per agent type)
# =============================================================================

def relay_system(today: str = "2026-04-04") -> str:
    return f"""\
You are ou, the relay agent of outheis — a local, privacy-first multi-agent system.
You are the communication interface between the user and specialist agents.
Route requests to the appropriate agent using the available tools.
Today's date: {today}
Default language: German

---

# Memory

{FAKE_MEMORY}"""


def data_system() -> str:
    return f"""\
You are zeno, the data agent of outheis.
You manage vault content: files, tags, full-text search.
Use tools to explore and retrieve vault data. Never guess file contents.

# Vault structure

{FAKE_VAULT_STRUCTURE}"""


def agenda_system(today: str = "2026-04-04") -> str:
    return f"""\
You are cato, the agenda agent of outheis.
You manage the user's schedule via daily notes in the vault.
Today: {today}
Use read_daily to retrieve the current schedule before answering."""


# =============================================================================
# SIMULATED TOOL EXECUTION
# =============================================================================

def execute_tool(name: str, args: dict, scenario_state: dict) -> str:
    """Return simulated tool results."""

    if name == "ask_agenda":
        return FAKE_DAILY_2026_04_04

    if name == "ask_data":
        return (
            "Active projects found:\n"
            "- Projects/outheis-dev.md (tags: project, dev, active)\n"
            "- Projects/research-notes.md (tags: research, active)"
        )

    if name == "save_memory":
        return f"Saved: {args.get('content', '')} (type={args.get('type', '')})"

    if name == "check_token_usage":
        return "Today: relay 12k tokens, data 3k tokens, agenda 2k tokens."

    if name == "list_vault_files":
        d = args.get("directory", "")
        if "Projects" in d:
            return "outheis-dev.md\nresearch-notes.md\nbudget-2025.md"
        if "Daily" in d:
            return "2026-04-04.md\n2026-04-03.md\n2026-04-02.md"
        return "Daily/\nProjects/\nPeople/\nArchive/"

    if name == "read_vault_file":
        path = args.get("path", "")
        # First call with wrong path triggers error (for recovery test)
        if scenario_state.get("force_error_once") and not scenario_state.get("error_done"):
            scenario_state["error_done"] = True
            return f"Error: file not found: {path}"
        if "outheis-dev" in path:
            return FAKE_PROJECT_FILE
        if "research-notes" in path:
            return "# Research Notes\n\nStatus: active\nTags: research, active\n\nNotes on temporalization of memory."
        if "daily" in path.lower() or "2026-04-04" in path:
            return FAKE_DAILY_2026_04_04
        return f"Error: file not found: {path}"

    if name == "search_vault":
        tags = args.get("tags", [])
        query = args.get("query", "")
        if "budget" in tags or "budget" in query.lower():
            return "No files found with tag 'budget' (budget-2025.md is tagged 'archived', not 'budget')."
        if "active" in tags:
            return "Projects/outheis-dev.md\nProjects/research-notes.md"
        if query:
            return f"Found in: Projects/outheis-dev.md, Daily/2026-04-04.md"
        return "No matches."

    if name == "scan_tags":
        return "active: 2 files\ndev: 1 file\nproject: 1 file\nresearch: 1 file\nfinance: 1 file\narchived: 1 file\ncontacts: 1 file"

    if name == "read_daily":
        return FAKE_DAILY_2026_04_04

    if name == "write_daily":
        return f"Updated daily note for {args.get('date', '?')}."

    if name == "add_event":
        return f"Added event '{args.get('title', '')}' at {args.get('time', '')} on {args.get('date', '')}."

    return f"Unknown tool: {name}"


# =============================================================================
# SCENARIO DEFINITIONS
# =============================================================================

class Scenario:
    def __init__(
        self,
        name: str,
        agent: str,
        system: str,
        tools: list,
        user_message: str,
        expected_tool: str | None,        # None = no tool call expected
        verify_keywords: list[str],       # keywords expected in final answer
        reject_keywords: list[str],       # keywords that indicate hallucination
        description: str,
        force_error_once: bool = False,   # simulate tool error on first call
    ):
        self.name = name
        self.agent = agent
        self.system = system
        self.tools = tools
        self.user_message = user_message
        self.expected_tool = expected_tool
        self.verify_keywords = verify_keywords
        self.reject_keywords = reject_keywords
        self.description = description
        self.force_error_once = force_error_once


SCENARIOS = [
    Scenario(
        name="relay_route_agenda",
        agent="relay",
        system=relay_system(),
        tools=RELAY_TOOLS,
        user_message="Was steht heute an?",
        expected_tool="ask_agenda",
        verify_keywords=["10:00", "stefan", "14:00"],
        reject_keywords=[],
        description="Relay routes agenda query to cato",
    ),
    Scenario(
        name="relay_route_data",
        agent="relay",
        system=relay_system(),
        tools=RELAY_TOOLS,
        user_message="Which projects are active?",
        expected_tool="ask_data",
        verify_keywords=["outheis-dev", "research"],
        reject_keywords=[],
        description="Relay routes vault query to zeno",
    ),
    Scenario(
        name="relay_no_tool_needed",
        agent="relay",
        system=relay_system(),
        tools=RELAY_TOOLS,
        user_message="What exactly do you do?",
        expected_tool=None,
        verify_keywords=[],
        reject_keywords=[],
        description="Relay answers identity question directly (no tool)",
    ),
    Scenario(
        name="data_search_by_tag",
        agent="data",
        system=data_system(),
        tools=DATA_TOOLS,
        user_message="Which notes are tagged 'active'?",
        expected_tool="search_vault",
        verify_keywords=["outheis-dev", "research"],
        reject_keywords=[],
        description="Data agent searches by tag",
    ),
    Scenario(
        name="data_read_file",
        agent="data",
        system=data_system(),
        tools=DATA_TOOLS,
        user_message="Show me the content of Projects/outheis-dev.md",
        expected_tool="read_vault_file",
        verify_keywords=["hiro", "mcp", "relay"],
        reject_keywords=[],
        description="Data agent reads a specific file",
    ),
    Scenario(
        name="data_error_recovery",
        agent="data",
        system=data_system(),
        tools=DATA_TOOLS,
        user_message="Show me Projects/outheis-dev.md",
        expected_tool="read_vault_file",
        verify_keywords=["hiro", "mcp"],
        reject_keywords=[],
        description="Data agent recovers from file-not-found error",
        force_error_once=True,
    ),
    Scenario(
        name="data_hallucination_check",
        agent="data",
        system=data_system(),
        tools=DATA_TOOLS,
        user_message="Show me all files with tag 'budget'.",
        expected_tool="search_vault",
        verify_keywords=["not found", "no files", "no results", "archived"],
        reject_keywords=["budget-2025.md", "budget.md"],
        description="Data agent reports no results instead of inventing files",
    ),
    Scenario(
        name="agenda_read_today",
        agent="agenda",
        system=agenda_system(),
        tools=AGENDA_TOOLS,
        user_message="What is on my agenda today?",
        expected_tool="read_daily",
        verify_keywords=["10:00", "stefan", "14:00"],
        reject_keywords=[],
        description="Agenda agent reads today's daily note",
    ),
    Scenario(
        name="agenda_add_event",
        agent="agenda",
        system=agenda_system(),
        tools=AGENDA_TOOLS,
        user_message="Add an appointment 'Team meeting' tomorrow at 09:00.",
        expected_tool="add_event",
        verify_keywords=["teammeeting", "09:00", "2026-04-05"],
        reject_keywords=[],
        description="Agenda agent adds an event to the next day",
    ),
]


# =============================================================================
# TEST RUNNER
# =============================================================================

class ScenarioResult:
    def __init__(self, scenario: Scenario):
        self.scenario = scenario
        self.tool_called: bool = False
        self.correct_tool: bool = False
        self.tool_chain: list[str] = []
        self.final_answer: str = ""
        self.keywords_found: list[str] = []
        self.keywords_missing: list[str] = []
        self.hallucination: bool = False
        self.recovered_from_error: bool = False
        self.elapsed: float = 0.0
        self.error: str | None = None

    @property
    def verdict(self) -> str:
        if self.error:
            return "ERR"
        if not self.tool_called and self.scenario.expected_tool is not None:
            return " NO "
        if self.scenario.expected_tool is None and not self.tool_called:
            # No tool expected, no tool called — check if answer is sensible
            return "  OK" if self.final_answer else " NO "
        if not self.correct_tool:
            return "TOOL"  # Called wrong tool
        if self.hallucination:
            return "HALL"
        if self.scenario.expected_tool and self.keywords_missing:
            return " ~OK"  # Tool called correctly but answer incomplete
        return "  OK"

    @property
    def verdict_symbol(self) -> str:
        v = self.verdict
        if v == "  OK": return "✓"
        if v == " ~OK": return "~"
        if v in (" NO ", "TOOL"): return "✗"
        if v == "HALL": return "H"
        if v == "ERR":  return "E"
        return "?"


def run_scenario(client, model: str, scenario: Scenario, timeout: int, verbose: bool) -> ScenarioResult:
    result = ScenarioResult(scenario)
    t0 = time.time()
    state = {"force_error_once": scenario.force_error_once, "error_done": False}

    messages = [{"role": "user", "content": scenario.user_message}]

    try:
        for iteration in range(6):
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": scenario.system}] + messages,
                tools=scenario.tools,
                max_tokens=400,
                timeout=timeout,
            )
            choice = resp.choices[0]

            if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
                result.tool_called = True
                tc = choice.message.tool_calls[0]
                tool_name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}

                result.tool_chain.append(f"{tool_name}({tc.function.arguments[:40].strip()})")

                if tool_name == scenario.expected_tool:
                    result.correct_tool = True
                if tool_name == "read_vault_file" and state.get("error_done"):
                    result.recovered_from_error = True

                tool_result = execute_tool(tool_name, args, state)

                if verbose:
                    print(f"    [{iteration+1}] {tool_name}({tc.function.arguments[:60]}) → {tool_result[:60]}")

                messages.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tool_name, "arguments": tc.function.arguments},
                    }],
                })
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": tool_result,
                })

            else:
                result.final_answer = (choice.message.content or "").strip()
                answer_lower = result.final_answer.lower()

                # Keyword checks
                result.keywords_found = [k for k in scenario.verify_keywords if k.lower() in answer_lower]
                result.keywords_missing = [k for k in scenario.verify_keywords if k.lower() not in answer_lower]
                result.hallucination = any(k.lower() in answer_lower for k in scenario.reject_keywords)

                if verbose:
                    print(f"    [{iteration+1}] Final: {result.final_answer[:120]}")
                break

        # If expected_tool was called, correct_tool might be True even if not in final iteration
        if result.tool_called and scenario.expected_tool and not result.correct_tool:
            result.correct_tool = scenario.expected_tool in [
                t.split("(")[0] for t in result.tool_chain
            ]

    except Exception as e:
        result.error = str(e)[:80]

    result.elapsed = time.time() - t0
    return result


# =============================================================================
# MAIN
# =============================================================================

def get_available_models(client) -> list[str]:
    try:
        import httpx
        r = httpx.get("http://localhost:11434/api/tags", timeout=5)
        return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        return []


def print_model_summary(model: str, results: list[ScenarioResult]) -> None:
    ok = sum(1 for r in results if r.verdict_symbol == "✓")
    partial = sum(1 for r in results if r.verdict_symbol == "~")
    fail = sum(1 for r in results if r.verdict_symbol in ("✗", "H", "E"))
    total = len(results)
    elapsed = sum(r.elapsed for r in results)
    print(f"  Summary: {ok}/{total} OK, {partial} partial, {fail} fail — {elapsed:.0f}s total")


def main():
    parser = argparse.ArgumentParser(description="Test Ollama models under realistic outheis agent conditions")
    parser.add_argument("--models", nargs="*", help="Models to test (default: all available)")
    parser.add_argument("--agents", nargs="*", choices=["relay", "data", "agenda"],
                        help="Agent types to test (default: all)")
    parser.add_argument("--url", default="http://localhost:11434", help="Ollama base URL")
    parser.add_argument("--timeout", type=int, default=90, help="Per-call timeout in seconds")
    parser.add_argument("--verbose", action="store_true", help="Show tool call details")
    args = parser.parse_args()

    try:
        from openai import OpenAI
    except ImportError:
        print("ERROR: openai package not installed. Run: pip install openai")
        return

    client = OpenAI(base_url=f"{args.url}/v1", api_key="ollama")

    models = args.models or get_available_models(client)
    if not models:
        print("No models found. Pass --models explicitly or check Ollama is running.")
        return

    agent_filter = set(args.agents) if args.agents else {"relay", "data", "agenda"}
    scenarios = [s for s in SCENARIOS if s.agent in agent_filter]

    col_w = max(len(s.name) for s in scenarios) + 2

    for model in models:
        print(f"\n{'='*80}")
        print(f"Model: {model}")
        print(f"{'='*80}")

        header = f"  {'Scenario':<{col_w}} {'V':<3} {'Tools':<50} {'Time':>5}  {'Answer / Error'}"
        print(header)
        print("-" * 100)

        results = []
        for scenario in scenarios:
            if args.verbose:
                print(f"\n  [{scenario.agent}] {scenario.description}")
            result = run_scenario(client, model, scenario, args.timeout, args.verbose)
            results.append(result)

            chain_str = " → ".join(result.tool_chain) if result.tool_chain else "—"
            if result.error:
                detail = f"ERROR: {result.error}"
            elif result.keywords_missing:
                detail = f"missing: {', '.join(result.keywords_missing[:3])}"
            elif result.hallucination:
                detail = f"HALLUCINATION: {', '.join(r for r in scenario.reject_keywords if r.lower() in result.final_answer.lower())}"
            else:
                detail = result.final_answer[:50].replace("\n", " ") if result.final_answer else ""

            print(f"  {scenario.name:<{col_w}} {result.verdict_symbol:<3} {chain_str:<50} {result.elapsed:>4.0f}s  {detail}")

        print()
        print_model_summary(model, results)

    print()


if __name__ == "__main__":
    main()
