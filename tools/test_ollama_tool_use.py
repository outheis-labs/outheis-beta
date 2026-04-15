#!/usr/bin/env python3
"""
Tool-use capability test for Ollama models.

Tests whether a model correctly calls tools via the OpenAI-compatible
Ollama API, rather than outputting tool calls as plain text.

Usage:
    python tools/test_ollama_tool_use.py
    python tools/test_ollama_tool_use.py --models llama3.1:8b devstral-small-2:24b
    python tools/test_ollama_tool_use.py --url http://localhost:11434 --full

Requires: pip install openai
"""

import argparse
import json
import os
import time


SYSTEM_PROMPT = """You are a code analysis assistant for the outheis project.
Source root: {src_root}
Use list_files to explore directories. Use search_code to find patterns.
Always use tools — do not guess or hallucinate file paths."""

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
                    "path": {"type": "string", "description": "Directory to search in"},
                },
                "required": ["query"],
            },
        },
    },
]


def list_files_real(path: str) -> str:
    try:
        items = sorted(os.listdir(path))
        visible = [f for f in items if not f.startswith("__")]
        return "\n".join(visible) if visible else "(empty)"
    except Exception as e:
        return f"Error: {e}"


def search_code_real(query: str, path: str | None = None) -> str:
    import subprocess
    target = path or os.getcwd()
    try:
        result = subprocess.run(
            ["grep", "-r", "-n", "--include=*.py", "-l", query, target],
            capture_output=True, text=True, timeout=5,
        )
        files = [f for f in result.stdout.strip().split("\n") if f]
        if not files:
            return f"No matches for '{query}'"
        return "\n".join(files[:10])
    except Exception as e:
        return f"Search error: {e}"


def execute_tool(name: str, args: dict) -> str:
    if name == "list_files":
        return list_files_real(args.get("path", "."))
    elif name == "search_code":
        return search_code_real(args.get("query", ""), args.get("path"))
    return f"Unknown tool: {name}"


def run_single_call(client, model: str, src_root: str, question: str, timeout: int = 45, no_think: bool = False) -> tuple[bool, str, float]:
    """
    Single LLM call. Returns (called_tool, tool_name_or_text, elapsed).
    """
    t0 = time.time()
    kwargs = dict(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT.format(src_root=src_root)},
            {"role": "user", "content": question},
        ],
        tools=TOOLS,
        max_tokens=150,
        timeout=timeout,
    )
    if no_think:
        kwargs["extra_body"] = {"think": False}
    resp = client.chat.completions.create(**kwargs)
    elapsed = time.time() - t0
    choice = resp.choices[0]
    if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
        tc = choice.message.tool_calls[0]
        return True, f"{tc.function.name}({tc.function.arguments[:60]})", elapsed
    else:
        text = (choice.message.content or "").strip()[:80].replace("\n", " ")
        return False, text, elapsed


def run_full_loop(client, model: str, src_root: str, question: str, timeout: int = 45, no_think: bool = False) -> tuple[list[str], str, float]:
    """
    Full tool loop: call → execute → call again → final answer.
    Returns (tool_calls_made, final_answer, total_elapsed).
    """
    t0 = time.time()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT.format(src_root=src_root)},
        {"role": "user", "content": question},
    ]
    tool_calls_made = []
    extra = {"extra_body": {"think": False}} if no_think else {}

    for _ in range(5):
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=TOOLS,
            **extra,
            max_tokens=300,
            timeout=timeout,
        )
        choice = resp.choices[0]

        if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
            tc = choice.message.tool_calls[0]
            args = json.loads(tc.function.arguments)
            tool_name = tc.function.name
            result = execute_tool(tool_name, args)
            tool_calls_made.append(f"{tool_name}({tc.function.arguments[:40]})")

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
                "content": result,
            })
        else:
            final = (choice.message.content or "").strip()[:200].replace("\n", " ")
            return tool_calls_made, final, time.time() - t0

    return tool_calls_made, "(max iterations reached)", time.time() - t0


def get_default_models(client) -> list[str]:
    """List models available in Ollama."""
    try:
        import httpx
        r = httpx.get("http://localhost:11434/api/tags", timeout=5)
        data = r.json()
        return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


def main():
    parser = argparse.ArgumentParser(description="Test Ollama models for tool-use capability")
    parser.add_argument("--models", nargs="*", help="Models to test (default: all available)")
    parser.add_argument("--url", default="http://localhost:11434", help="Ollama base URL")
    parser.add_argument("--api-key", default="ollama", help="API key (required for cloud)")
    parser.add_argument("--src", default=None, help="Source root to use in prompts")
    parser.add_argument("--full", action="store_true", help="Run full tool loop (not just first call)")
    parser.add_argument("--timeout", type=int, default=60, help="Per-model timeout in seconds")
    parser.add_argument("--no-think", action="store_true", help="Disable thinking mode (qwen3 etc.)")
    args = parser.parse_args()

    try:
        from openai import OpenAI
    except ImportError:
        print("ERROR: openai package not installed. Run: pip install openai")
        return

    client = OpenAI(base_url=f"{args.url}/v1", api_key=args.api_key)

    src_root = args.src or os.path.expanduser("~/outheis-beta/src/outheis")
    question = f"How many Python files are in {src_root}/agents/?"

    models = args.models or get_default_models(client)
    if not models:
        print("No models found. Pass --models explicitly or check Ollama is running.")
        return

    if args.full:
        print(f"\n{'Model':<32} {'Tool calls':<40} {'Answer'}")
        print("-" * 100)
        for model in models:
            try:
                calls, answer, elapsed = run_full_loop(client, model, src_root, question, args.timeout, no_think=args.no_think)
                calls_str = " → ".join(calls) if calls else "none"
                verdict = "✓" if calls else "✗"
                print(f"{verdict} {model:<30} {calls_str:<40} {answer[:40]}  ({elapsed:.1f}s)")
            except Exception as e:
                print(f"  {model:<30} ERROR: {str(e)[:60]}")
    else:
        print(f"\n{'Model':<32} {'Tool?':<8} {'Details'}")
        print("-" * 90)
        for model in models:
            try:
                called, detail, elapsed = run_single_call(client, model, src_root, question, args.timeout, no_think=args.no_think)
                verdict = "✓ YES" if called else "✗ NO "
                print(f"{verdict}  {model:<30} {detail:<60}  ({elapsed:.1f}s)")
            except Exception as e:
                print(f"ERR   {model:<30} {str(e)[:60]}")

    print()


if __name__ == "__main__":
    main()
