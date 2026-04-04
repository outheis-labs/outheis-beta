"""
Relay agent (ou).

The communication interface. Routes messages, composes responses,
formats output for each channel.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from outheis.agents.base import BaseAgent
from outheis.core.message import Message


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
        from outheis.agents.loader import load_skills, load_rules
        from outheis.core.config import load_config
        from outheis.core.memory import get_memory_context
        
        config = load_config()
        skills = load_skills("relay")
        rules = load_rules("relay")
        memory_context = get_memory_context()
        
        prompt_parts = []
        
        # Skills first - how to act
        if skills:
            prompt_parts.append(f"# Skills\n\n{skills}")
        
        # Rules - what to observe
        if rules:
            prompt_parts.append(f"# Rules\n\n{rules}")
        
        # User identity
        if config.human.name:
            prompt_parts.append(f"# User\n\nThe user's name is {config.human.name}.")
        
        # Memory context
        if memory_context:
            prompt_parts.append(memory_context)
        
        prompt_parts.append(f"\nDefault language: {config.human.language}")
        
        return "\n\n---\n\n".join(prompt_parts)






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

        # Check for explicit agent mentions (@zeno, @cato) and bare agenda read commands
        text_lower = text.lower().strip()
        _AGENDA_READ_COMMANDS = {"agenda", "daily", "tagesagenda", "was steht heute", "was ist heute"}
        if "@zeno" in text_lower:
            if verbose:
                print("[explicit @zeno → data]", file=sys.stderr)
            response_text = self._handle_with_data_agent(text, msg)
        elif "@cato" in text_lower or text_lower in _AGENDA_READ_COMMANDS:
            if verbose:
                print("[explicit @cato → agenda]", file=sys.stderr)
            response_text = self._handle_with_agenda_agent(text, msg)
        elif "@alan" in text_lower:
            if verbose:
                print("[explicit @alan → code]", file=sys.stderr)
            response_text = self._handle_with_code_agent(text, msg)
        else:
            # Let Relay handle with tools - it decides when to delegate
            # Use session context for continuity across restarts
            session_context = self.get_session_context(max_messages=30)
            # Also get conversation-specific context
            conv_context = self.get_conversation_context(msg.conversation_id)
            # Merge: session context first, then conversation (to prioritize recent)
            context = self._merge_contexts(session_context, conv_context)
            response_text = self._generate_response(text, context, msg)

        return self.respond(
            to="transport",
            payload={"text": response_text},
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
        """Write a 'please wait' notification to transport before a slow local-model call."""
        if not self._is_ollama_agent(agent_name):
            return
        try:
            from outheis.core.config import get_messages_path
            from outheis.core.message import create_agent_message
            from outheis.core.queue import append
            text = "One moment — local model, this may take a little longer..."
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

    def _handle_with_data_agent(self, text: str, msg: Message) -> str:
        """Delegate to Data agent (zeno) via dispatcher."""
        if self._dispatcher is None:
            return "Dispatcher not available."
        self._send_interim(msg, "data")
        return self._dispatcher.dispatch_sync("data", text, msg.conversation_id)

    def _handle_with_agenda_agent(self, text: str, msg: Message) -> str:
        """Delegate to Agenda agent via dispatcher."""
        if self._dispatcher is None:
            return "Dispatcher not available."
        self._send_interim(msg, "agenda")
        return self._dispatcher.dispatch_sync("agenda", text, msg.conversation_id)

    def _handle_with_code_agent(self, text: str, msg: Message) -> str:
        """Delegate to Code agent (alan) via dispatcher."""
        if self._dispatcher is None:
            return "Dispatcher not available."
        self._send_interim(msg, "code")
        result = self._dispatcher.dispatch_sync("code", text, msg.conversation_id)
        if result.startswith("Agent 'code' not available"):
            return "Code agent (alan) ist nicht aktiviert. Aktiviere ihn in config.json unter agents.code.enabled: true."
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
        try:
            return self._call_llm_with_tools(text, context, original_msg.conversation_id)
        except Exception as e:
            return f"Ein Fehler ist aufgetreten: {e}"

    def _call_llm_with_tools(self, text: str, context: list[Message], conversation_id: str = "relay") -> str:
        """Call LLM API with tool support for vault/agenda access."""
        import os
        import sys
        
        verbose = os.environ.get("OUTHEIS_VERBOSE")
        
        # Define tools
        tools = [
            {
                "name": "search_vault",
                "description": "Search the user's vault (notes, documents, files) for personal information. USE THIS when asked about personal facts you don't know from Memory: where they live, contacts, family details, projects, health info, or anything personal that might be in their notes. Also use for questions about specific files or directories.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "What to search for"
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "check_agenda",
                "description": "Read and return the current agenda/schedule. Use this when the user asks to see their agenda, schedule, or Daily.md — including bare commands like 'Agenda', 'agenda', 'was steht heute an', 'was ist heute'. Returns the exact file content. Do NOT use refresh_agenda unless the user explicitly asks to update, regenerate, or refresh.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The schedule question"
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "refresh_agenda",
                "description": "Regenerate/update Daily.md. ONLY use when the user explicitly says 'aktualisiere', 'aktualisiere daily', 'aktualisiere agenda', 'update daily', 'refresh agenda', 'regeneriere', or similar explicit update commands. Never use just because the user asks to see the agenda.",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "get_config",
                "description": "Get outheis system configuration. Use when the user asks about vault paths, which models are used, whether Signal is enabled, agent settings, or any other system configuration.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "aspect": {
                            "type": "string",
                            "description": "What config to retrieve: 'vault', 'signal', 'agents', 'models', or 'all'"
                        }
                    },
                    "required": ["aspect"]
                }
            },
            {
                "name": "memory_migrate",
                "description": "Process migration files from vault/Migration/ directory. Use when user says 'memory migrate', 'migriere memory', 'process migration', or asks to import/migrate data. Reads .json and .md files, creates Migration.md for approval.",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "memory_traits",
                "description": "Show recognized traits and memory summary. Use when user asks 'memory traits', 'zeige traits', 'was weißt du über mich', 'what do you know about me', or wants to see their profile/personality.",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "memory_traits_write",
                "description": "Write a trait directly to rules, bypassing Pattern agent. Use when user explicitly says 'schreibe regel', 'add rule', 'remember always', or wants to permanently add a behavioral rule.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "agent": {
                            "type": "string",
                            "description": "Target agent: relay, data, agenda, pattern, or common"
                        },
                        "trait": {
                            "type": "string",
                            "description": "The rule/trait to add"
                        }
                    },
                    "required": ["agent", "trait"]
                }
            },
            {
                "name": "analyze_tags",
                "description": "Analyze tag usage in the vault. Use when user asks about tags, tag statistics, tag cleanup, 'welche tags', 'zeige tags', 'tag-analyse', or wants to know which tags are used.",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "add_to_daily",
                "description": "Add content to Daily.md. Use when user wants to add a task, note, reminder, or any content to their daily file. Examples: 'füge X zu Daily hinzu', 'add task X', 'schreib in Daily', 'track X daily', 'add to my daily checklist'.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "The content to add (task, note, reminder, checklist item)"
                        },
                        "section": {
                            "type": "string",
                            "description": "Target section: 'Tasks', 'Schedule', 'Notes', 'Morning', 'Evening', or null for auto"
                        }
                    },
                    "required": ["content"]
                }
            },
            {
                "name": "write_to_inbox",
                "description": "Write content to Inbox.md for later processing. Use when user wants to quickly note something, dump a thought, or add unstructured content that will be processed later.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "The content to add to inbox"
                        }
                    },
                    "required": ["content"]
                }
            },
            {
                "name": "explain_code",
                "description": "Use for ANY question about the outheis source code or implementation: how many lines, what does agent X do, where is Y implemented, how does Z work, show me the code for. Examples: 'wie viele zeilen', 'was macht der data agent', 'zeig mir den code', 'wie ist X implementiert'. Do NOT use for general problems unrelated to code internals.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": "The question about outheis code"
                        }
                    },
                    "required": ["question"]
                }
            },
            {
                "name": "check_token_usage",
                "description": "Show token usage and estimated API costs for a time period. Use when user asks about token consumption, costs, 'wie viele tokens', 'was kostet das', 'token-verbrauch', 'kosten diese woche', 'wie viel habe ich verbraucht', etc. For single-day queries set date: 'heute'/'today' for today, 'gestern'/'yesterday' for yesterday, or 'YYYY-MM-DD' for a specific date. For multi-day windows (last 7 days etc.) use the days parameter instead. IMPORTANT: Always forward the complete tool output verbatim, including the per-agent breakdown — never summarize or omit the agent list.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "days": {
                            "type": "integer",
                            "description": "Rolling look-back window in days (e.g. 7 = last 7 days). Ignored when date is set."
                        },
                        "date": {
                            "type": "string",
                            "description": "Specific calendar day: 'today', 'yesterday', or 'YYYY-MM-DD'. Use this for single-day queries."
                        }
                    },
                    "required": []
                }
            },
            {
                "name": "delegate_to_agent",
                "description": "PRIMARY TOOL for getting things done. Delegate a task to a specialist agent. Use this for ANY user request that requires action: regenerate files, search vault, update daily, write content, etc. You can call this multiple times to orchestrate complex tasks. Agents: 'data' (vault read/write/search), 'agenda' (daily/inbox/exchange, schedule, regenerate daily), 'action' (task execution), 'pattern' (memory, learning).",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "agent": {
                            "type": "string",
                            "enum": ["data", "agenda", "action", "pattern"],
                            "description": "Which agent to delegate to"
                        },
                        "task": {
                            "type": "string",
                            "description": "What the agent should do - be specific and complete"
                        }
                    },
                    "required": ["agent", "task"]
                }
            }
        ]
        
        # Build messages — exclude relay responses that signal tool failures
        # (they poison the LLM context and cause repeated refusals)
        _failure_markers = ("antwortet nicht", "agent error", "not available", "kann das nicht")
        messages = []
        for msg in context[-5:]:
            if msg.from_user:
                messages.append({"role": "user", "content": msg.payload.get("text", "")})
            elif msg.from_agent == "relay":
                content = msg.payload.get("text", "")
                if not any(m in content.lower() for m in _failure_markers):
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
                    "content": "[System: Letzter Turn. Antworte jetzt dem User.]"
                })
            
            # Check if tool use is needed
            if response.stop_reason != "tool_use":
                # No more tools - extract final response
                for block in response.content:
                    if hasattr(block, "text"):
                        return block.text
                return "Ich konnte keine Antwort formulieren."
            
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
                            result = self._dispatcher.dispatch_sync("data", block.input["query"], conversation_id)
                    elif block.name == "check_agenda":
                        if self._dispatcher is None:
                            result = "Dispatcher not available."
                        else:
                            result = self._dispatcher.dispatch_sync("agenda", block.input["query"], conversation_id)
                        # Return agenda content directly — no second LLM pass
                        if result and result != "Dispatcher not available.":
                            return result
                    elif block.name == "refresh_agenda":
                        if self._dispatcher is None:
                            result = "Dispatcher not available."
                        else:
                            result = self._dispatcher.dispatch_sync("agenda", "Aktualisiere Daily.md für heute.", conversation_id)
                    elif block.name == "get_config":
                        result = self._get_config_info(block.input.get("aspect", "all"))
                    elif block.name == "memory_migrate":
                        result = self._run_memory_migrate()
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
                            result = self._dispatcher.dispatch_sync("data", "Zeige alle Tags im Vault mit Anzahl", conversation_id)
                    elif block.name == "add_to_daily":
                        content = block.input.get("content", "")
                        section = block.input.get("section", "")
                        if content:
                            section_hint = f" in Sektion {section}" if section else ""
                            if self._dispatcher is None:
                                result = "Dispatcher not available."
                            else:
                                result = self._dispatcher.dispatch_sync(
                                    "agenda",
                                    f"Füge zu Daily.md hinzu{section_hint}: {content}",
                                    conversation_id
                                )
                        else:
                            result = "Kein Inhalt angegeben"
                    elif block.name == "write_to_inbox":
                        content = block.input.get("content", "")
                        if content:
                            if self._dispatcher is None:
                                result = "Dispatcher not available."
                            else:
                                result = self._dispatcher.dispatch_sync(
                                    "agenda",
                                    f"Notiere in Inbox.md: {content}",
                                    conversation_id
                                )
                        else:
                            result = "Kein Inhalt angegeben"
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
                                    question if target == "code" else f"Schau im outheis-Code nach und erkläre: {question}",
                                    conversation_id
                                )
                        else:
                            result = "Keine Frage angegeben"
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
                            result = "Agent und Task müssen angegeben werden"
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
        return "Maximale Anzahl an Schritten erreicht. Bitte präzisiere deine Anfrage."

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

    def _run_memory_migrate(self) -> str:
        """Run memory migration from vault/Migration/.

        Two-phase flow:
        Phase A — if Exchange.md has a migration section: process [x]/[-] items, remove section.
        Phase B — parse new Migration/ files via LLM, deduplicate against existing memory,
                   write consolidated pending to Exchange.md for user confirmation.
        """
        from outheis.core.config import load_config
        from outheis.agents.agenda import get_agenda_dir
        from outheis.core.memory import get_memory_store
        import re

        config = load_config()
        vault = config.human.primary_vault()
        migration_dir = vault / "Migration"

        if not migration_dir.exists():
            return "Kein Migration/ Verzeichnis im Vault gefunden. Nichts zu tun."

        agenda_dir = get_agenda_dir()
        exchange_path = agenda_dir / "Exchange.md" if agenda_dir else None
        store = get_memory_store()

        adopted_items: list[str] = []
        rejected_count = 0
        still_pending: list[tuple[str, str]] = []

        # ── Phase A: process confirmed items from Exchange.md migration section ──
        if exchange_path and exchange_path.exists():
            exchange_text = exchange_path.read_text(encoding="utf-8")
            pattern = r'<!-- outheis:migration:start -->(.*?)<!-- outheis:migration:end -->'
            m = re.search(pattern, exchange_text, re.DOTALL)
            if m:
                for line in m.group(1).splitlines():
                    item_m = re.match(
                        r'^-\s*\[([ xX\-])\]\s*(.+?)\s*\[(\w+(?::\w+)?)\]\s*$',
                        line.strip(),
                    )
                    if not item_m:
                        continue
                    status = item_m.group(1).lower()
                    content_text = item_m.group(2).strip()
                    entry_type = item_m.group(3).strip()
                    if status == 'x':
                        if entry_type.startswith("rule:"):
                            self._add_to_rules(entry_type.split(":")[1], content_text)
                        else:
                            store.add(content_text, entry_type)
                        adopted_items.append(content_text)
                    elif status == '-':
                        rejected_count += 1
                    else:
                        still_pending.append((content_text, entry_type))

                # Remove migration section from Exchange.md
                cleaned = re.sub(pattern, '', exchange_text, flags=re.DOTALL).strip()
                exchange_path.write_text(cleaned + "\n", encoding="utf-8")

        # ── Phase B: parse new source files ─────────────────────────────────────
        new_entries: list[tuple[str, str]] = []
        files_processed = []
        parse_errors = []

        for f in sorted(migration_dir.iterdir()):
            if f.name.startswith("x-") or f.suffix.lower() not in [".json", ".md"]:
                continue
            try:
                entries = (
                    self._parse_json_migration(f)
                    if f.suffix.lower() == ".json"
                    else self._parse_md_migration(f)
                )
                if entries:
                    new_entries.extend(entries)
                    files_processed.append(f)
                else:
                    parse_errors.append(f"{f.name}: keine Einträge gefunden")
            except Exception as e:
                parse_errors.append(f"{f.name}: {e}")

        # ── Phase C: deduplicate candidates via LLM ──────────────────────────────
        all_candidates = still_pending + new_entries
        if all_candidates:
            all_candidates = self._deduplicate_migration_entries(all_candidates, store)

        # ── Phase D: write pending section to Exchange.md ────────────────────────
        if all_candidates and exchange_path:
            self._write_migration_section(exchange_path, all_candidates)

        # ── Phase E: rename processed source files ───────────────────────────────
        for f in files_processed:
            f.rename(f.parent / f"x-{f.name}")

        # ── Build response ────────────────────────────────────────────────────────
        parts = []
        if adopted_items:
            parts.append(f"{len(adopted_items)} Einträge übernommen.")
        if rejected_count:
            parts.append(f"{rejected_count} abgelehnt.")
        if files_processed:
            names = ", ".join(f.name for f in files_processed)
            parts.append(f"{len(files_processed)} Datei(en) geparst: {names}")
        if all_candidates:
            parts.append(
                f"{len(all_candidates)} Einträge zur Bestätigung in Exchange.md — "
                "bitte prüfen und mit [x] / [-] markieren, dann erneut `memory migrate` ausführen."
            )
        if parse_errors:
            parts.append("Fehler: " + "; ".join(parse_errors))
        if not parts:
            parts.append("Keine neuen Einträge zu verarbeiten.")
        return "\n".join(parts)

    def _deduplicate_migration_entries(
        self, entries: list[tuple[str, str]], store
    ) -> list[tuple[str, str]]:
        """Deduplicate migration candidates against existing memory via LLM."""
        from outheis.core.llm import call_llm
        import json

        existing_lines = [
            f"[{e.get('type', 'user')}] {e.get('content', '')}"
            for e in store.all()
        ]
        if not existing_lines:
            return entries

        entries_json = json.dumps(
            [{"content": c, "type": t} for c, t in entries],
            ensure_ascii=False,
            indent=2,
        )
        existing_text = "\n".join(existing_lines[:200])

        prompt = (
            "Below are candidate migration entries and the existing memory.\n\n"
            "Rules:\n"
            "- Remove entries already covered by existing memory (exact or clearly redundant).\n"
            "- Merge closely related entries into one.\n"
            "- Keep entries that add genuinely new information.\n\n"
            f"EXISTING MEMORY:\n{existing_text}\n\n"
            f"CANDIDATE ENTRIES:\n{entries_json}\n\n"
            "Respond ONLY with a JSON array of surviving entries in the same format. "
            "If nothing survives, respond with []."
        )

        try:
            response = call_llm(
                model=self.model_alias,
                agent=self.name,
                system=self.get_system_prompt(),
                messages=[{"role": "user", "content": prompt}],
                max_tokens=4096,
            )
            text = response.content[0].text.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()
            result = []
            for item in json.loads(text):
                if isinstance(item, dict):
                    c = item.get("content", "").strip()
                    t = item.get("type", "user").strip()
                    if c:
                        result.append((c, t))
            return result
        except Exception as e:
            print(f"[relay] deduplication failed: {e}", file=sys.stderr)
            return entries

    def _write_migration_section(
        self, exchange_path, entries: list[tuple[str, str]]
    ) -> None:
        """Append migration confirmation block to Exchange.md."""
        from datetime import datetime
        from pathlib import Path

        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        lines = [
            "",
            "<!-- outheis:migration:start -->",
            "## Migration-Vorschläge",
            "",
            f"*{ts} — Bitte prüfen und markieren:*",
            "*`[x]` übernehmen · `[-]` ablehnen · `[ ]` offen lassen*",
            "*Anschließend: `memory migrate` erneut ausführen.*",
            "",
        ]
        for content_text, entry_type in entries:
            lines.append(f"- [ ] {content_text} [{entry_type}]")
        lines += ["", "<!-- outheis:migration:end -->", ""]

        section = "\n".join(lines)
        exchange_path = Path(exchange_path)
        if exchange_path.exists():
            existing = exchange_path.read_text(encoding="utf-8").rstrip()
            exchange_path.write_text(existing + "\n" + section, encoding="utf-8")
        else:
            exchange_path.parent.mkdir(parents=True, exist_ok=True)
            exchange_path.write_text(section.lstrip(), encoding="utf-8")

    def _parse_json_migration(self, path) -> list[tuple[str, str]]:
        """Parse JSON migration file.
        
        Supports formats:
        - {"entries": [{"content": "...", "type": "user"}, ...]}
        - [{"content": "...", "type": "user"}, ...]
        - ["string1", "string2", ...]
        - {"key": "value", ...} — treats each value as entry
        """
        import json
        content = path.read_text(encoding="utf-8")
        data = json.loads(content)
        entries = []
        
        # Format 1: {"entries": [...]}
        if isinstance(data, dict) and "entries" in data:
            items = data["entries"]
        # Format 2: [...] array at top level
        elif isinstance(data, list):
            items = data
        # Format 3: {"key": "value", ...} — each key-value pair
        elif isinstance(data, dict):
            # Treat each key-value as potential entry
            items = []
            for key, value in data.items():
                if isinstance(value, str):
                    items.append({"content": f"{key}: {value}", "type": "user"})
                elif isinstance(value, dict):
                    # Nested dict with content/type
                    items.append(value)
                elif isinstance(value, list):
                    # List of strings
                    for v in value:
                        if isinstance(v, str):
                            items.append({"content": v, "type": "user"})
        else:
            items = []
        
        for item in items:
            if isinstance(item, dict):
                entry_content = item.get("content", "")
                entry_type = item.get("type", "user")
            elif isinstance(item, str):
                entry_content = item
                entry_type = "user"
            else:
                continue
            
            if entry_content and entry_content.strip():
                entries.append((entry_content.strip(), entry_type))
        
        return entries

    def _parse_md_migration(self, path) -> list[tuple[str, str]]:
        """
        Parse Markdown migration file via LLM.

        Uses LLM instead of heuristic parsing so it handles any markdown
        structure — plain lists, tables, free text, mixed formatting — without
        extracting formatting artifacts as entries.
        """
        from outheis.core.llm import call_llm

        content = path.read_text(encoding="utf-8")

        prompt = (
            f"File: {path.name}\n\n"
            f"{content}\n\n"
            "---\n"
            "Extract all meaningful personal facts, preferences, rules, or behavioral guidelines "
            "from this file. Ignore markdown formatting artifacts, table separators, section headers, "
            "and structural elements. Each extracted entry must be a complete, self-contained statement.\n\n"
            "Respond ONLY with a JSON array. Each element is an object with:\n"
            '- "content": the entry as a clear statement\n'
            '- "type": one of "user" (facts about the person), "feedback" (behavioral preferences), '
            '"context" (current focus/projects), "rule:agenda", "rule:data", "rule:relay"\n\n'
            "Example:\n"
            '[{"content": "Works at senswork as Director Innovation Lab", "type": "user"},\n'
            ' {"content": "Prefers short, direct answers", "type": "feedback"}]\n\n'
            "If no meaningful entries found, respond with: []"
        )

        try:
            system = self.get_system_prompt()
            response = call_llm(
                model=self.model_alias,
                agent=self.name,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=4096,
            )
            import json as _json
            text = response.content[0].text.strip()
            # Strip markdown code fences if present
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()
            data = _json.loads(text)
            entries = []
            for item in data:
                if isinstance(item, dict):
                    c = item.get("content", "").strip()
                    t = item.get("type", "user").strip()
                    if c:
                        entries.append((c, t))
            return entries
        except Exception as e:
            print(f"[relay] MD migration parse failed for {path.name}: {e}")
            return []

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
        lines = ["Erkannte Eigenschaften:", ""]
        
        # User traits
        user_entries = store.get("user")
        if user_entries:
            lines.append("## Identität")
            for e in user_entries[:10]:
                lines.append(f"  • {e.content}")
            lines.append("")
        
        # Feedback
        feedback_entries = store.get("feedback")
        if feedback_entries:
            lines.append("## Präferenzen")
            for e in feedback_entries[:10]:
                lines.append(f"  • {e.content}")
            lines.append("")
        
        # Context
        context_entries = store.get("context")
        if context_entries:
            lines.append("## Aktueller Fokus")
            for e in context_entries[:5]:
                lines.append(f"  • {e.content}")
            lines.append("")
        
        # Rules
        rules_dir = get_rules_dir()
        if rules_dir.exists():
            rule_files = list(rules_dir.glob("*.md"))
            if rule_files:
                lines.append("## Etablierte Regeln")
                for rf in rule_files:
                    content = rf.read_text(encoding="utf-8")
                    rule_count = len([l for l in content.split("\n") if l.strip().startswith("-")])
                    if rule_count:
                        lines.append(f"  • {rf.stem}: {rule_count} Regeln")
        
        return "\n".join(lines)

    def _write_memory_trait(self, agent: str, trait: str) -> str:
        """Write trait directly to rules."""
        valid_agents = ["relay", "data", "agenda", "pattern", "common"]
        if agent not in valid_agents:
            return f"Ungültiger Agent: {agent}. Verwende: {', '.join(valid_agents)}"
        
        if not trait:
            return "Kein Trait angegeben."
        
        self._add_to_rules(agent, trait)
        return f"✓ Regel hinzugefügt zu {agent}: {trait}"


# =============================================================================
# FACTORY
# =============================================================================

def create_relay_agent(model_alias: str = "fast") -> RelayAgent:
    """Create a relay agent instance."""
    return RelayAgent(model_alias=model_alias)
