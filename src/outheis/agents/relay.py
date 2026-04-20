"""
Relay agent (ou).

The communication interface. Routes messages, composes responses,
formats output for each channel.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from outheis.agents.base import BaseAgent
from outheis.core.message import Message
from outheis.core.tools import tool_error


# =============================================================================
# SIGNAL FORMATTING
# =============================================================================

# Bullet used for schedule items (📅 Today, 🗓️ This Week, 💶 Cashflow).
# Change here to try alternatives, e.g. "•", "➤", "🔹".
_SIGNAL_BULLET = "▸"

# Sections that receive a bullet prefix on each content line.
_SIGNAL_BULLET_SECTIONS = {"📅", "🗓️", "💶"}

# Sections where markdown checkboxes are converted to Unicode glyphs.
_SIGNAL_CHECKBOX_SECTIONS = {"🧘"}

_SIGNAL_CHECKBOX_OPEN = "🟩"
_SIGNAL_CHECKBOX_DONE = "✅"


def _format_agenda_for_signal(text: str) -> str:
    """
    Signal-specific agenda formatting.

    - 📅 Heute / 🗓️ Diese Woche / 💶 Cashflow: prefix each content line with ▸
    - 🧘 Personal: convert - [x] → ✅, - [ ] → 🟩  (no bullet — has checkboxes)
    - All other content: passed through unchanged.
    """
    lines = text.split("\n")
    result = []
    mode: str | None = None  # "bullet" | "checkbox" | None

    for line in lines:
        stripped = line.strip()

        # Section header: determine mode for lines that follow.
        if stripped.startswith("##"):
            if any(e in stripped for e in _SIGNAL_BULLET_SECTIONS):
                mode = "bullet"
            elif any(e in stripped for e in _SIGNAL_CHECKBOX_SECTIONS):
                mode = "checkbox"
            else:
                mode = None
            result.append(line)
            continue

        # Horizontal rule separates sections — reset until next header.
        if stripped == "---":
            mode = None
            result.append(line)
            continue

        if mode == "bullet" and stripped:
            line = f"{_SIGNAL_BULLET} {stripped}"
        elif mode == "checkbox":
            if stripped.startswith("- [x]"):
                line = f"{_SIGNAL_CHECKBOX_DONE} {stripped[5:].strip()}"
            elif stripped.startswith("- [ ]"):
                line = f"{_SIGNAL_CHECKBOX_OPEN} {stripped[5:].strip()}"

        result.append(line)

    return "\n".join(result)


# =============================================================================
# RELAY AGENT
# =============================================================================

@dataclass
class RelayAgent(BaseAgent):
    """
    Relay agent handles all user communication.

    Routes user messages and delegates to specialist agents via dispatcher.
    All inter-agent calls go through dispatch_sync() for full queue logging.
    No direct agent references — agents are managed by the dispatcher.
    """

    name: str = "relay"
    _dispatcher: any = field(default=None, repr=False)  # Dispatcher reference, set at startup

    def get_system_prompt(self) -> str:
        # Relay is a routing agent — it does not need behavioral rules (common.md).
        # Keep the system prompt minimal to reduce input token count for local models.
        from outheis.agents.loader import _load_user_rule
        from outheis.core.config import load_config
        from outheis.core.memory import get_memory_store

        config = load_config()
        relay_rules = _load_user_rule("relay")

        store = get_memory_store()
        store._ensure_loaded() if hasattr(store, "_ensure_loaded") else None
        user_entries = store._entries.get("user", [])
        feedback_entries = store._entries.get("feedback", [])
        context_entries = store._entries.get("context", [])

        from datetime import date as _date
        today_iso = _date.today().isoformat()

        parts = [
            f"You are {config.human.name}'s personal assistant. "
            f"Language: {config.human.language}. "
            f"Today: {today_iso}. "
            "Route requests to the correct agent via tools. Respond concisely. "
            "When the user mentions personal facts about people or relationships (family, names, roles) "
            "call save_to_memory proactively. "
            "When the user mentions completed work or decisions with lasting relevance (invoice sent, payment received, appointment confirmed) "
            "call save_to_vault proactively. "
            "Never just acknowledge verbally — persist.",
        ]
        if relay_rules:
            parts.append(f"# Routing rules\n\n{relay_rules}")
        if user_entries:
            lines = [f"- {e.content}" for e in user_entries]
            parts.append("# User\n\n" + "\n".join(lines))
        if feedback_entries:
            lines = [f"- {e.content}" for e in feedback_entries]
            parts.append("# Feedback\n\n" + "\n".join(lines))
        if context_entries:
            lines = [f"- {e.content}" for e in context_entries]
            parts.append("# Context\n\n" + "\n".join(lines))

        return "\n\n".join(parts)






    def handle(self, msg: Message) -> Message | None:
        """Handle an incoming message."""
        import os
        import sys

        verbose = os.environ.get("OUTHEIS_VERBOSE")
        text = msg.payload.get("text", "")

        if not text:
            return None

        # Check for explicit memory marker "!"
        # This stores AND continues processing - agent knows it immediately
        from outheis.core.memory import handle_explicit_memory
        was_memory, stored_content, memory_type = handle_explicit_memory(text)

        if was_memory:
            if verbose:
                print(f"[memory: {memory_type}] {stored_content}", file=sys.stderr)
            # Continue with the stored content as the message
            # The agent now knows this information (it's in context)
            text = stored_content

        text_lower = text.lower().strip()

        # Interim timer: fires after 10s if relay or any sub-agent uses a slow local model.
        # Cancelled as soon as a response is ready. Covers ALL paths including _generate_response.
        _interim_timer = self._schedule_interim(msg, "relay")

        # Fast pre-routing: agenda read requests bypass relay LLM entirely.
        # Requires BOTH an agenda keyword AND explicit read/display intent (or ≤4 words).
        # Mere mention of "agenda" in a discussion must NOT trigger this path.
        from outheis.core.i18n import AGENDA_WRITE_STEMS, AGENDA_READ_INTENT_STEMS
        from outheis.core.config import load_config as _lc
        try:
            _lang = _lc().human.language[:2].lower()
        except Exception:
            _lang = "en"
        _agenda_keywords = ("agenda", "daily", "schedule", "calendar", "appointments")
        # Merge user language + English so read-intent verbs work regardless of input language.
        _read_intent_keywords = tuple(
            set(AGENDA_READ_INTENT_STEMS.get(_lang, []))
            | set(AGENDA_READ_INTENT_STEMS.get("en", []))
        )
        _write_keywords = tuple(
            ["update", "write", "create", "add", "change", "modify", "refresh", "process", "review"]
            + AGENDA_WRITE_STEMS.get(_lang, AGENDA_WRITE_STEMS["en"])
        )
        _has_agenda_kw = any(kw in text_lower for kw in _agenda_keywords)
        _has_read_intent = (
            len(text_lower.split()) <= 4
            or any(kw in text_lower for kw in _read_intent_keywords)
        )
        _negation_keywords = ("nein", "nicht", "no ", "don't", "dont", "kein", "nicht in")
        _has_negation = any(kw in text_lower for kw in _negation_keywords)
        _is_agenda_read = (
            _has_agenda_kw
            and _has_read_intent
            and not _has_negation
            and not any(kw in text_lower for kw in _write_keywords)
        )
        _is_agenda_write = (
            _has_agenda_kw
            and any(kw in text_lower for kw in _write_keywords)
            and not _has_negation
            and not _is_agenda_read
        )

        # Check for @ prefix: "@ ..." means "write this to the agenda"
        _at_prefix = text.lstrip().startswith("@ ")
        _at_text = text.lstrip()[2:].strip() if _at_prefix else text

        response_source = "relay"
        if _at_prefix:
            if verbose:
                print(f"[@ prefix → agenda]", file=sys.stderr)
            response_text = self._handle_with_agenda_agent(f"add to agenda: {_at_text}", msg)
            response_source = "cato"
        elif "@zeno" in text_lower:
            if verbose:
                print("[explicit @zeno → data]", file=sys.stderr)
            response_text = self._handle_with_data_agent(text, msg)
            response_source = "zeno"
        elif "@cato" in text_lower:
            if verbose:
                print("[explicit @cato → agenda]", file=sys.stderr)
            response_text = self._handle_with_agenda_agent(text, msg)
            response_source = "cato"
        elif "@alan" in text_lower:
            if verbose:
                print("[explicit @alan → code]", file=sys.stderr)
            response_text = self._handle_with_code_agent(text, msg)
            response_source = "alan"
        elif _is_agenda_read:
            if verbose:
                print(f"[fast-route agenda-read → agenda]", file=sys.stderr)
            response_text = self._handle_with_agenda_agent(text, msg)
            response_source = "cato"
        elif _is_agenda_write:
            if verbose:
                print(f"[fast-route agenda-write → agenda]", file=sys.stderr)
            response_text = self._handle_with_agenda_agent(text, msg)
            response_source = "cato"
        else:
            # Let Relay handle with tools - it decides when to delegate
            # Use session context for continuity across restarts
            session_context = self.get_session_context(max_messages=30)
            # Also get conversation-specific context
            conv_context = self.get_conversation_context(msg.conversation_id)
            # Merge: session context first, then conversation (to prioritize recent)
            context = self._merge_contexts(session_context, conv_context)
            response_text = self._generate_response(text, context, msg)

        _interim_timer.cancel()

        if msg.from_user and msg.from_user.channel == "signal":
            response_text = _format_agenda_for_signal(response_text)

        return self.respond(
            to="transport",
            payload={"text": response_text, "source": response_source},
            conversation_id=msg.conversation_id,
            reply_to=msg.id,
        )

    def _is_ollama_agent(self, agent_name: str) -> bool:
        """Return True if the agent's configured model uses the Ollama provider."""
        try:
            from outheis.core.config import load_config
            from outheis.core.llm import resolve_model
            config = load_config()
            agent_cfg = config.agents.get(agent_name)
            if not agent_cfg:
                return False
            return resolve_model(agent_cfg.model).provider == "ollama"
        except Exception:
            return False

    def _send_interim(self, msg: Message, agent_name: str) -> None:
        """Write a 'please wait' notification to transport (called by timer)."""
        if not self._is_ollama_agent(agent_name):
            return
        try:
            from outheis.core.config import get_messages_path, load_config
            from outheis.core.message import create_agent_message
            from outheis.core.queue import append
            try:
                lang = load_config().human.language
            except Exception:
                lang = "en"
            from outheis.core.i18n import INTERIM_LOCAL_MODEL, t
            lang_key = lang[:2].lower()
            text = t(INTERIM_LOCAL_MODEL, lang_key)
            interim = create_agent_message(
                from_agent="relay",
                to="transport",
                type="response",
                payload={"text": text},
                conversation_id=msg.conversation_id,
                reply_to=msg.id,
                intent="interim",
            )
            append(get_messages_path(), interim)
        except Exception:
            pass

    def _schedule_interim(self, msg: Message, agent_name: str, delay: float = 10.0):
        """Send interim after delay seconds �� cancel the returned timer if response arrives first."""
        import threading
        timer = threading.Timer(delay, self._send_interim, args=[msg, agent_name])
        timer.daemon = True
        timer.start()
        return timer

    def _handle_with_data_agent(self, text: str, msg: Message) -> str:
        """Delegate to Data agent (zeno) via dispatcher."""
        if self._dispatcher is None:
            return "Dispatcher not available."
        timer = self._schedule_interim(msg, "data")
        result = self._dispatcher.dispatch_sync("data", text, msg.conversation_id)
        timer.cancel()
        return result

    def _handle_with_agenda_agent(self, text: str, msg: Message) -> str:
        """Delegate to Agenda agent via dispatcher."""
        if self._dispatcher is None:
            return "Dispatcher not available."
        timer = self._schedule_interim(msg, "agenda")
        result = self._dispatcher.dispatch_sync("agenda", text, msg.conversation_id)
        timer.cancel()
        return result

    def _handle_with_code_agent(self, text: str, msg: Message) -> str:
        """Delegate to Code agent (alan) via dispatcher."""
        if self._dispatcher is None:
            return "Dispatcher not available."
        timer = self._schedule_interim(msg, "code")
        result = self._dispatcher.dispatch_sync("code", text, msg.conversation_id)
        timer.cancel()
        if result.startswith("Agent 'code' not available"):
            return "Code agent (alan) is not enabled. Enable it in config.json under agents.code.enabled: true."
        return result

    def _merge_contexts(
        self,
        session_context: list[Message],
        conv_context: list[Message],
    ) -> list[Message]:
        """
        Merge session context with conversation context.

        Removes duplicates, keeps conversation messages at the end
        for recency, limits total to avoid token bloat.
        """
        seen_ids = set()
        merged = []

        # Add session context first (older)
        for msg in session_context:
            if msg.id not in seen_ids:
                seen_ids.add(msg.id)
                merged.append(msg)

        # Add conversation context (newer, overwrites order)
        for msg in conv_context:
            if msg.id not in seen_ids:
                seen_ids.add(msg.id)
                merged.append(msg)

        # Sort by timestamp and limit
        merged.sort(key=lambda m: m.timestamp or 0)
        return merged[-10:]  # Keep last 10 for context

    def _generate_response(
        self,
        text: str,
        context: list[Message],
        original_msg: Message,
    ) -> str:
        """Generate a response using LLM with tools."""
        from outheis.core.llm import BillingError
        try:
            return self._call_llm_with_tools(text, context, original_msg.conversation_id, original_msg)
        except BillingError as e:
            # Trigger fallback mode via dispatcher so next requests use local model
            if self._dispatcher is not None:
                self._dispatcher._enter_fallback_mode(str(e), original_msg.conversation_id)
            return "API credit balance exhausted. Switching to local fallback model — please resend your message."
        except Exception as e:
            return tool_error(str(e))

    def _call_llm_with_tools(self, text: str, context: list[Message], conversation_id: str = "relay", original_msg: Message | None = None) -> str:
        """Call LLM API with tool support for vault/agenda access."""
        import os
        import sys

        verbose = os.environ.get("OUTHEIS_VERBOSE")

        # Define tools — descriptions are intentionally terse to minimize input tokens
        tools = [
            {
                "name": "search_vault",
                "description": "Search vault for personal info not in memory (contacts, projects, health, files).",
                "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}
            },
            {
                "name": "check_agenda",
                "description": "Return current Agenda.md verbatim. Use when user asks to see agenda/schedule/daily. Do NOT use for update requests.",
                "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": []}
            },
            {
                "name": "refresh_agenda",
                "description": "Regenerate Agenda.md. ONLY when user explicitly says update/refresh/regenerate.",
                "input_schema": {"type": "object", "properties": {}, "required": []}
            },
            {
                "name": "get_config",
                "description": "Get system config (vault paths, models, agents, signal). aspect: vault|signal|agents|models|all",
                "input_schema": {"type": "object", "properties": {"aspect": {"type": "string"}}, "required": ["aspect"]}
            },
            {
                "name": "memory_migrate",
                "description": "Process vault/Migration/ files → Migration/Exchange.md proposals. Use when user says 'memory migrate'.",
                "input_schema": {"type": "object", "properties": {}, "required": []}
            },
            {
                "name": "memory_traits",
                "description": "Show memory summary / user profile. Use for 'what do you know about me', 'memory traits'.",
                "input_schema": {"type": "object", "properties": {}, "required": []}
            },
            {
                "name": "memory_traits_write",
                "description": "Write rule directly to agent rules file. Use when user says 'add rule', 'remember always', 'write rule'.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "agent": {"type": "string", "description": "relay|data|agenda|pattern|common"},
                        "trait": {"type": "string"}
                    },
                    "required": ["agent", "trait"]
                }
            },
            {
                "name": "analyze_tags",
                "description": "Show vault tag statistics. Use for 'which tags', 'tag analysis'.",
                "input_schema": {"type": "object", "properties": {}, "required": []}
            },
            {
                "name": "add_to_daily",
                "description": "Add task/note/item to Agenda.md. Agenda determines placement automatically — never pass a section name.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string"}
                    },
                    "required": ["content"]
                }
            },
            {
                "name": "explain_code",
                "description": "Answer questions about outheis source code. Use for 'how is X implemented', 'what does agent Y do', 'show me the code'.",
                "input_schema": {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]}
            },
            {
                "name": "check_token_usage",
                "description": "Show token usage and API costs. date: today|yesterday|YYYY-MM-DD. days: rolling window. Forward output verbatim.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "days": {"type": "integer"},
                        "date": {"type": "string"}
                    },
                    "required": []
                }
            },
            {
                "name": "delegate_to_agent",
                "description": "PRIMARY TOOL. Delegate to specialist: data (vault), agenda (daily/exchange), action (tasks), pattern (memory/learning).",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "agent": {"type": "string", "enum": ["data", "agenda", "action", "pattern"]},
                        "task": {"type": "string"}
                    },
                    "required": ["agent", "task"]
                }
            },
            {
                "name": "save_to_vault",
                "description": (
                    "Persist a fact from this conversation to the vault. "
                    "Use when the user mentions something worth keeping across sessions: "
                    "a task completed, an invoice sent, a payment received, an appointment, "
                    "a decision made, a status update on an ongoing project. "
                    "zeno will find the right existing vault file via the index and append the fact there, "
                    "then update Shadow.md immediately so cato sees it at the next hourly review."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "fact": {"type": "string", "description": "The fact to persist, in plain language"}
                    },
                    "required": ["fact"]
                }
            },
            {
                "name": "save_to_memory",
                "description": (
                    "Persist a personal fact about the user to long-term memory. "
                    "Use for people, family relationships, names, roles, and personal background. "
                    "Not for tasks or work items — use save_to_vault for those."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "description": "The fact in plain language, self-contained"},
                        "type": {"type": "string", "enum": ["user", "context"], "description": "'user' for permanent personal facts, 'context' for current focus/projects"}
                    },
                    "required": ["content", "type"]
                }
            }
        ]

        # Build messages — exclude relay responses that signal tool failures
        # (they poison the LLM context and cause repeated refusals)
        _failure_markers = ("not responding", "agent error", "not available", "cannot do that")
        _delegated_sources = ("cato", "zeno", "alan")
        messages = []
        for msg in context[-5:]:
            if msg.from_user:
                messages.append({"role": "user", "content": msg.payload.get("text", "")})
            elif msg.from_agent == "relay":
                content = msg.payload.get("text", "")
                source = msg.payload.get("source")
                if any(m in content.lower() for m in _failure_markers):
                    continue
                if source in _delegated_sources:
                    first_line = content.split("\n")[0][:80]
                    content = f"[{source} response: {first_line}…]"
                messages.append({"role": "assistant", "content": content})
        messages.append({"role": "user", "content": text})

        # First call - tool decision
        from outheis.core.llm import call_llm

        system = self.get_system_prompt()
        response = call_llm(
            model=self.model_alias,
            agent=self.name,
            system=system,
            messages=messages,
            tools=tools,
            max_tokens=4096,
        )

        # Agentic loop - LLM can use multiple tools across turns
        max_turns = 8  # Safety limit
        turn = 0

        while turn < max_turns:
            turn += 1

            # Budget warning when running low
            if turn == max_turns - 1:
                messages.append({
                    "role": "user",
                    "content": "[System: Last turn. Respond to the user now.]"
                })

            # Check if tool use is needed
            if response.stop_reason != "tool_use":
                # No more tools - extract final response
                for block in response.content:
                    if hasattr(block, "text"):
                        return block.text
                return "I was unable to formulate a response."

            # Process tool calls
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    if verbose:
                        print(f"[turn {turn}, tool: {block.name}({block.input})]", file=sys.stderr)

                    if block.name == "search_vault":
                        if self._dispatcher is None:
                            result = "Dispatcher not available."
                        else:
                            result = self._dispatcher.dispatch_sync("data", block.input.get("query", ""), conversation_id)
                    elif block.name == "check_agenda":
                        if self._dispatcher is None:
                            result = "Dispatcher not available."
                        else:
                            timer = self._schedule_interim(original_msg, "agenda") if original_msg is not None else None
                            result = self._dispatcher.dispatch_sync("agenda", block.input.get("query", "Show me the current agenda."), conversation_id)
                            if timer is not None:
                                timer.cancel()
                        # Return agenda content directly — no second LLM pass
                        _agent_failures = ("Dispatcher not available.", "No response.", "Max iterations reached.")
                        if result and result not in _agent_failures:
                            return result
                    elif block.name == "refresh_agenda":
                        if self._dispatcher is None:
                            result = "Dispatcher not available."
                        else:
                            import uuid
                            from outheis.core.config import get_messages_path
                            from outheis.core.message import create_agent_message
                            from outheis.core.queue import append
                            trigger_msg = create_agent_message(
                                from_agent="relay",
                                to="dispatcher",
                                type="internal",
                                intent="internal",
                                payload={"text": "run_task:agenda_review"},
                                conversation_id=conversation_id or str(uuid.uuid4()),
                            )
                            append(get_messages_path(), trigger_msg)
                            result = "Agenda update queued — runs via scheduler with lock protection."
                    elif block.name == "get_config":
                        result = self._get_config_info(block.input.get("aspect", "all"))
                    elif block.name == "memory_migrate":
                        pattern_agent = self._dispatcher.get_agent("pattern") if self._dispatcher else None
                        if pattern_agent and hasattr(pattern_agent, 'run_migration'):
                            result = pattern_agent.run_migration()
                        else:
                            result = "Pattern agent not available for migration."
                    elif block.name == "memory_traits":
                        result = self._get_memory_traits()
                    elif block.name == "memory_traits_write":
                        result = self._write_memory_trait(
                            block.input.get("agent", "common"),
                            block.input.get("trait", "")
                        )
                    elif block.name == "analyze_tags":
                        if self._dispatcher is None:
                            result = "Dispatcher not available."
                        else:
                            result = self._dispatcher.dispatch_sync("data", "Show all tags in the vault with counts", conversation_id)
                    elif block.name == "add_to_daily":
                        content = block.input.get("content", "")
                        if content:
                            if self._dispatcher is None:
                                result = "Dispatcher not available."
                            else:
                                result = self._dispatcher.dispatch_sync(
                                    "agenda",
                                    f"Add to Agenda.md: {content}",
                                    conversation_id
                                )
                        else:
                            result = "No content provided"
                    elif block.name == "explain_code":
                        question = block.input.get("question", "")
                        if question:
                            if self._dispatcher is None:
                                result = "Dispatcher not available."
                            else:
                                # Prefer code agent, fallback to action
                                code_agent = self._dispatcher.get_agent("code")
                                target = "code" if code_agent is not None else "action"
                                result = self._dispatcher.dispatch_sync(
                                    target,
                                    question if target == "code" else f"Look at the outheis source code and explain: {question}",
                                    conversation_id
                                )
                        else:
                            result = "No question provided"
                    elif block.name == "check_token_usage":
                        from outheis.core.tokens import get_usage_summary
                        date_param = block.input.get("date")
                        days_param = block.input.get("days", 7)
                        result = get_usage_summary(days=days_param, date=date_param)
                    elif block.name == "delegate_to_agent":
                        # Generic delegation - LLM decides which agent and what to ask
                        agent = block.input.get("agent", "")
                        task = block.input.get("task", "")
                        if agent and task:
                            if self._dispatcher is None:
                                result = "Dispatcher not available."
                            else:
                                result = self._dispatcher.dispatch_sync(agent, task, conversation_id)
                        else:
                            result = "Agent and task must be specified"
                    elif block.name == "save_to_vault":
                        fact = block.input.get("fact", "")
                        if fact and self._dispatcher is not None:
                            result = self._dispatcher.dispatch_sync(
                                "data",
                                (
                                    f"A fact was mentioned in conversation — persist it to the vault.\n\n"
                                    f"Fact: {fact}\n\n"
                                    "Instructions:\n"
                                    "1. Search the vault index for the most relevant existing file.\n"
                                    "2. Append the fact as a dated entry (today's date, plain language).\n"
                                    "3. Call update_shadow with that file's path so Shadow.md is updated immediately.\n"
                                    "If no relevant file exists, append to a general notes file."
                                ),
                                conversation_id,
                            )
                        else:
                            result = "No fact provided or dispatcher unavailable."
                    elif block.name == "save_to_memory":
                        content = block.input.get("content", "")
                        memory_type = block.input.get("type", "user")
                        if content and memory_type in ("user", "context"):
                            self._add_to_memory(content, memory_type)  # type: ignore[arg-type]
                            result = f"✓ Saved to {memory_type} memory"
                        else:
                            result = "No content provided or invalid type."
                    else:
                        result = "Tool not found"

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

            # Continue conversation with tool results
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

            response = call_llm(
                model=self.model_alias,
                agent=self.name,
                system=system,
                messages=messages,
                tools=tools,
                max_tokens=4096,
            )

        # Max turns reached
        return "Maximum number of steps reached. Please refine your request."

    def _get_config_info(self, aspect: str) -> str:
        """Get configuration information for the user."""
        from outheis.core.config import load_config

        config = load_config()

        if aspect == "vault":
            vaults = config.human.all_vaults()
            return f"Vault paths: {[str(v) for v in vaults]}"

        elif aspect == "signal":
            if config.signal.enabled:
                return (
                    f"Signal is enabled.\n"
                    f"Bot phone: {config.signal.bot_phone}\n"
                    f"Bot name: {config.signal.bot_name}\n"
                    f"Allowed contacts: {len(config.signal.allowed)}"
                )
            else:
                return "Signal is not enabled."

        elif aspect == "agents":
            lines = ["Agent configuration:"]
            for name, agent_cfg in config.agents.items():
                status = "enabled" if agent_cfg.enabled else "disabled"
                lines.append(f"  {name} ({agent_cfg.name}): {status}, model: {agent_cfg.model}")
            return "\n".join(lines)

        elif aspect == "models":
            lines = ["Model aliases:"]
            for alias, model_cfg in config.llm.models.items():
                lines.append(f"  {alias}: {model_cfg.provider}/{model_cfg.name}")
            return "\n".join(lines)

        else:  # "all" or unknown
            lines = [
                f"Human: {config.human.name}",
                f"Language: {config.human.language}",
                f"Timezone: {config.human.timezone}",
                f"Vaults: {[str(v) for v in config.human.all_vaults()]}",
                f"Signal: {'enabled' if config.signal.enabled else 'disabled'}",
                "",
                "Agents:",
            ]
            for name, agent_cfg in config.agents.items():
                status = "✓" if agent_cfg.enabled else "✗"
                lines.append(f"  {status} {name} ({agent_cfg.name}): {agent_cfg.model}")
            return "\n".join(lines)

    def _add_to_rules(self, target: str, content: str) -> None:
        """Add a rule to rules file."""
        from outheis.core.config import get_rules_dir
        from datetime import datetime

        rules_dir = get_rules_dir()
        rules_dir.mkdir(parents=True, exist_ok=True)
        rules_file = rules_dir / f"{target}.md"

        timestamp = datetime.now().strftime("%Y-%m-%d")
        rule_line = f"- {content}  <!-- {timestamp} -->\n"

        if rules_file.exists():
            existing = rules_file.read_text(encoding="utf-8")
            if content in existing:
                return
            rules_file.write_text(existing + rule_line, encoding="utf-8")
        else:
            header = f"# User Rules: {target.title()}\n\n"
            rules_file.write_text(header + rule_line, encoding="utf-8")

    def _get_memory_traits(self) -> str:
        """Get memory traits summary."""
        from outheis.core.memory import get_memory_store
        from outheis.core.config import get_rules_dir

        store = get_memory_store()
        lines = ["Known traits:", ""]

        # User traits
        user_entries = store.get("user")
        if user_entries:
            lines.append("## Identity")
            for e in user_entries[:10]:
                lines.append(f"  • {e.content}")
            lines.append("")

        # Feedback
        feedback_entries = store.get("feedback")
        if feedback_entries:
            lines.append("## Preferences")
            for e in feedback_entries[:10]:
                lines.append(f"  • {e.content}")
            lines.append("")

        # Context
        context_entries = store.get("context")
        if context_entries:
            lines.append("## Current Focus")
            for e in context_entries[:5]:
                lines.append(f"  • {e.content}")
            lines.append("")

        # Rules
        rules_dir = get_rules_dir()
        if rules_dir.exists():
            rule_files = list(rules_dir.glob("*.md"))
            if rule_files:
                lines.append("## Established Rules")
                for rf in rule_files:
                    content = rf.read_text(encoding="utf-8")
                    rule_count = len([l for l in content.split("\n") if l.strip().startswith("-")])
                    if rule_count:
                        lines.append(f"  • {rf.stem}: {rule_count} rules")

        return "\n".join(lines)

    def _write_memory_trait(self, agent: str, trait: str) -> str:
        """Write trait directly to rules."""
        valid_agents = ["relay", "data", "agenda", "pattern", "common"]
        if agent not in valid_agents:
            return f"Invalid agent: {agent}. Use: {', '.join(valid_agents)}"

        if not trait:
            return "No trait provided."

        self._add_to_rules(agent, trait)
        return f"✓ Rule added to {agent}: {trait}"


# =============================================================================
# FACTORY
# =============================================================================

def create_relay_agent(model_alias: str = "fast") -> RelayAgent:
    """Create a relay agent instance."""
    return RelayAgent(model_alias=model_alias)
