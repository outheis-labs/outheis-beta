"""
Action agent (hiro).

Two responsibilities:
1. Task scheduling and execution
2. Code introspection — can read outheis source to explain behavior

When other agents can't do something, hiro can look at the code
to explain what's preventing it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from outheis.agents.base import BaseAgent
from outheis.agents.tasks import Task, TaskResult, get_registry
from outheis.core.config import get_human_dir
from outheis.core.message import Message


# =============================================================================
# CODE PATHS
# =============================================================================

def get_outheis_source_dir() -> Path:
    """Get outheis source directory."""
    return Path(__file__).parent.parent  # src/outheis/


# =============================================================================
# ACTION AGENT
# =============================================================================

@dataclass
class ActionAgent(BaseAgent):
    """
    Action agent — task execution AND code introspection.
    
    Responsibilities:
    1. Execute scheduled tasks
    2. Read outheis code to explain behavior/limitations
    
    Other agents can ask: "Why can't you do X?"
    Hiro looks at the code and explains.
    """

    name: str = "action"

    def get_system_prompt(self) -> str:
        """Minimal system prompt."""
        from outheis.core.memory import get_memory_context
        from outheis.agents.loader import load_skills, load_rules
        
        memory = get_memory_context()
        skills = load_skills("action")
        rules = load_rules("action")
        
        parts = [
            "# Action Agent (hiro)",
            "",
            "You have two responsibilities:",
            "1. Execute tasks (news, data fetching, etc.)",
            "2. Read code — explain what happens in the outheis codebase",
            "",
            "## Available Tools",
            "",
            "### Task Management",
            "- run_task(task_id) — run a task",
            "- list_tasks() — Alle Tasks auflisten",
            "- run_due_tasks() — run all due tasks",
            "",
            "### Code-Introspection",
            "- list_source_files() — list all source files",
            "- read_source(path) — read a source file",
            "- search_source(query) — In Source suchen",
            "- explain_behavior(question) — explain behavior from code",
            "",
            "## Principles",
            "- When asked 'why can't X do Y?' → read code and explain",
            "- Cite specific line numbers and function names",
            "- Suggest what would need to change",
        ]
        
        if skills:
            parts.append("")
            parts.append("## Skills")
            parts.append(skills)
        
        if rules:
            parts.append("")
            parts.append("## Rules")
            parts.append(rules)
        
        if memory:
            parts.append("")
            parts.append(memory)
        
        return "\n".join(parts)
    

    
    def _get_tools(self) -> list[dict]:
        """Define available tools."""
        return [
            # Task management
            {
                "name": "run_task",
                "description": "Run a specific task by ID",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string", "description": "Task ID to run"}
                    },
                    "required": ["task_id"]
                }
            },
            {
                "name": "list_tasks",
                "description": "List all registered tasks",
                "input_schema": {"type": "object", "properties": {}, "required": []}
            },
            {
                "name": "run_due_tasks",
                "description": "Run all tasks that are due now",
                "input_schema": {"type": "object", "properties": {}, "required": []}
            },
            # Code introspection
            {
                "name": "list_source_files",
                "description": "List all outheis source files",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "subdir": {"type": "string", "description": "Subdirectory to list (agents, core, cli), or empty for all"}
                    },
                    "required": []
                }
            },
            {
                "name": "read_source",
                "description": "Read a source file from outheis codebase",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path relative to src/outheis/, e.g. 'agents/relay.py'"}
                    },
                    "required": ["path"]
                }
            },
            {
                "name": "search_source",
                "description": "Search for a pattern in outheis source code",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search pattern (function name, keyword, etc.)"}
                    },
                    "required": ["query"]
                }
            },
        ]
    
    def _execute_tool(self, name: str, inputs: dict) -> str:
        """Execute a tool."""
        # Task management
        if name == "run_task":
            return self._tool_run_task(inputs.get("task_id", ""))
        elif name == "list_tasks":
            return self._tool_list_tasks()
        elif name == "run_due_tasks":
            return self._tool_run_due_tasks()
        
        # Code introspection
        elif name == "list_source_files":
            return self._tool_list_source_files(inputs.get("subdir", ""))
        elif name == "read_source":
            return self._tool_read_source(inputs.get("path", ""))
        elif name == "search_source":
            return self._tool_search_source(inputs.get("query", ""))
        
        else:
            return f"Unknown tool: {name}"
    
    # =========================================================================
    # TASK TOOLS
    # =========================================================================
    
    def _tool_run_task(self, task_id: str) -> str:
        """Run a specific task."""
        if not task_id:
            return "task_id required"
        
        registry = get_registry()
        task = registry.get(task_id)
        
        if not task:
            return f"Task not found: {task_id}"
        
        result = task.execute()
        registry.mark_completed(task)
        
        if result.success:
            return f"✓ Task {task_id} erfolgreich: {result.data}"
        else:
            return f"✗ Task {task_id} fehlgeschlagen: {result.error}"
    
    def _tool_list_tasks(self) -> str:
        """List all tasks."""
        registry = get_registry()
        if not registry.tasks:
            return "No tasks registered."
        
        lines = []
        for task in registry.tasks.values():
            lines.append(f"- {task.id}: {task.name} (next: {task.next_run})")
        return "\n".join(lines)
    
    def _tool_run_due_tasks(self) -> str:
        """Run all due tasks."""
        registry = get_registry()
        due_tasks = registry.get_due_tasks()
        
        if not due_tasks:
            return "No tasks due."
        
        results = []
        for task in due_tasks:
            result = task.execute()
            registry.mark_completed(task)
            status = "✓" if result.success else "✗"
            results.append(f"{status} {task.name}")
        
        return "\n".join(results)
    
    # =========================================================================
    # CODE INTROSPECTION TOOLS
    # =========================================================================
    
    def _tool_list_source_files(self, subdir: str = "") -> str:
        """List source files."""
        source_dir = get_outheis_source_dir()
        target = source_dir / subdir if subdir else source_dir
        
        if not target.exists():
            return f"Directory not found: {subdir}"
        
        files = []
        for path in sorted(target.rglob("*.py")):
            if "__pycache__" in str(path):
                continue
            rel_path = path.relative_to(source_dir)
            files.append(str(rel_path))
        
        # Also list .md files in agents/skills and agents/rules
        for md_path in sorted(target.rglob("*.md")):
            rel_path = md_path.relative_to(source_dir)
            files.append(str(rel_path))
        
        return "\n".join(files) if files else "No files found."
    
    def _tool_read_source(self, path: str) -> str:
        """Read a source file."""
        if not path:
            return "Path required"
        
        source_dir = get_outheis_source_dir()
        full_path = source_dir / path
        
        # Security: only allow reading within outheis source
        try:
            full_path.resolve().relative_to(source_dir.resolve())
        except ValueError:
            return "Access denied: only outheis source allowed."
        
        if not full_path.exists():
            return f"File not found: {path}"
        
        try:
            content = full_path.read_text(encoding="utf-8")
            # Add line numbers for reference
            lines = content.split("\n")
            numbered = [f"{i+1:4d} | {line}" for i, line in enumerate(lines)]
            return "\n".join(numbered)
        except Exception as e:
            return f"Error reading: {e}"
    
    def _tool_search_source(self, query: str) -> str:
        """Search in source files."""
        if not query:
            return "Search query required"
        
        source_dir = get_outheis_source_dir()
        results = []
        query_lower = query.lower()
        
        for path in source_dir.rglob("*.py"):
            if "__pycache__" in str(path):
                continue
            
            try:
                content = path.read_text(encoding="utf-8")
                lines = content.split("\n")
                
                for i, line in enumerate(lines, 1):
                    if query_lower in line.lower():
                        rel_path = path.relative_to(source_dir)
                        # Truncate long lines
                        display_line = line.strip()[:80]
                        results.append(f"{rel_path}:{i}: {display_line}")
                        
                        if len(results) >= 20:
                            results.append("... (weitere Treffer abgeschnitten)")
                            return "\n".join(results)
            except Exception:
                continue
        
        return "\n".join(results) if results else f"No matches for '{query}'."
    
    # =========================================================================
    # MESSAGE HANDLING
    # =========================================================================
    
    def handle(self, msg: Message) -> Message | None:
        """Handle incoming message."""
        import sys
        
        verbose = os.environ.get("OUTHEIS_VERBOSE")
        payload = msg.payload or {}
        
        # Legacy action-based handling for backwards compatibility
        action = payload.get("action")
        if action:
            return self._handle_legacy_action(msg, action, payload)
        
        # New: text-based queries
        query = payload.get("text", "")
        if query:
            answer = self._process_with_tools(query, verbose)
            return self.respond(
                to=msg.from_agent or "relay",
                payload={"text": answer},
                conversation_id=msg.conversation_id,
                reply_to=msg.id,
            )
        
        return None
    
    def handle_direct(self, query: str) -> str:
        """Direct query interface."""
        return self._process_with_tools(query)
    
    def _process_with_tools(self, query: str, verbose: bool = False) -> str:
        """Process query using tools."""
        import sys
        from outheis.core.llm import call_llm
        
        messages = [{"role": "user", "content": query}]
        tools = self._get_tools()
        
        max_iterations = 5
        system = self.get_system_prompt()
        for iteration in range(max_iterations):
            response = call_llm(
                model=self.model_alias,
                agent=self.name,
                system=system,
                messages=messages,
                tools=tools,
                max_tokens=4096,  # Larger for code reading
            )
            
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            
            if not tool_uses:
                text_parts = [b.text for b in response.content if hasattr(b, "text")]
                return "\n".join(text_parts) if text_parts else "No response."
            
            tool_results = []
            for tool in tool_uses:
                if verbose:
                    print(f"[action tool: {tool.name}({tool.input})]", file=sys.stderr)
                
                result = self._execute_tool(tool.name, tool.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool.id,
                    "content": result,
                })
            
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})
        
        return "Max iterations reached."
    
    def _handle_legacy_action(self, msg: Message, action: str, payload: dict) -> Message | None:
        """Handle legacy action-based messages."""
        if action == "run_task":
            result = self._tool_run_task(payload.get("task_id", ""))
        elif action == "run_due_tasks":
            result = self._tool_run_due_tasks()
        elif action == "list_tasks":
            result = self._tool_list_tasks()
        else:
            result = f"Unknown action: {action}"
        
        return self.respond(
            to=msg.from_agent or "relay",
            payload={"text": result},
            conversation_id=msg.conversation_id,
            reply_to=msg.id,
        )


# =============================================================================
# FACTORY
# =============================================================================

def create_action_agent(model_alias: str = "capable") -> ActionAgent:
    """Create an action agent instance."""
    return ActionAgent(model_alias=model_alias)
