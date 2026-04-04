"""
Agenda agent (cato).

Personal secretary: schedule, time management, daily rhythm.
Feingranulare Regeln, nah am User.

Works on vault/Agenda/:
- Daily.md — Today's structure
- Inbox.md — Quick inputs
- Exchange.md — Async communication / decision basis for open issues
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, date, timedelta
from pathlib import Path

from outheis.agents.base import BaseAgent
from outheis.core.config import load_config, get_human_dir
from outheis.core.message import Message


# =============================================================================
# HELPERS
# =============================================================================

def get_agenda_dir() -> Path | None:
    """Get Agenda directory from primary vault."""
    config = load_config()
    vault = config.human.primary_vault()
    if vault.exists():
        agenda_path = vault / "Agenda"
        agenda_path.mkdir(exist_ok=True)  # Create if not exists
        return agenda_path
    return None


def get_today_str() -> str:
    """Today formatted for display."""
    return date.today().strftime("%A, %d. %B %Y")


def get_today_iso() -> str:
    """Today in ISO format."""
    return date.today().isoformat()


# =============================================================================
# AGENDA AGENT
# =============================================================================

@dataclass
class AgendaAgent(BaseAgent):
    """
    Agenda agent — personal secretary.
    
    Autonomous: decides structure, formatting, timing.
    Learns user's rhythm and preferences.
    """
    
    name: str = "agenda"
    
    def get_system_prompt(self) -> str:
        """
        Build system prompt with FULL CONTEXT.
        
        Unlike Data agent (large vault), Agenda has only 3 files.
        All context is loaded upfront — no read tools needed.
        """
        from outheis.core.memory import get_memory_context
        from outheis.agents.loader import load_skills, load_rules
        
        config = load_config()
        memory = get_memory_context()
        skills = load_skills("agenda")
        rules = load_rules("agenda")
        
        today = get_today_str()
        today_iso = get_today_iso()
        now = datetime.now().strftime("%H:%M")
        weekday = date.today().strftime("%A")
        
        # Load all agenda files upfront
        agenda_context = self._load_agenda_context()
        
        parts = [
            "# Agenda Agent (cato)",
            "",
            "Du bist der persönliche Sekretär. Termine, Tagesstruktur, Rhythmus.",
            "",
            f"**Heute:** {today} ({today_iso})",
            f"**Jetzt:** {now}",
            f"**Wochentag:** {weekday}",
            f"**Sprache:** {config.human.language}",
            "",
            "---",
            "",
            "## Aktueller Stand (alle 3 Dateien)",
            "",
            agenda_context,
            "",
            "---",
            "",
            "## Verfügbare Tools",
            "- get_daily() — Tagesagenda lesen (gibt Daily.md exakt zurück)",
            "- write_file(file, content) — Datei schreiben (daily/inbox/exchange)",
            "- append_file(file, content) — An Datei anhängen",
            "- load_skill(topic) — Detail-Skills nachladen wenn nötig",
            "",
            "## Prinzipien",
            "- Wenn der User die Agenda lesen will: get_daily() aufrufen und das Ergebnis",
            "  **zeichengenau und unverändert** zurückgeben — kein Umformulieren, kein Kürzen,",
            "  keine Ergänzungen.",
            "- Struktur des Users übernehmen, nicht aufzwingen",
            "- Bei Unsicherheit via Exchange.md fragen",
            "- Kurz und direkt",
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
    
    def _load_agenda_context(self) -> str:
        """
        Load all agenda files as context.

        Context is provided upfront, not fetched via tools.
        If Shadow.md is missing or sparse, triggers a background shadow_scan
        via the dispatcher message queue (fire-and-forget).
        """
        agenda_dir = get_agenda_dir()
        if not agenda_dir:
            return "(Kein Agenda-Verzeichnis)"

        parts = []

        for filename in ["Daily.md", "Inbox.md", "Exchange.md", "Shadow.md"]:
            filepath = agenda_dir / filename
            if filepath.exists():
                content = filepath.read_text(encoding="utf-8")
                if filename == "Exchange.md":
                    import re
                    content = re.sub(
                        r'\n*<!-- outheis:migration:start -->.*?<!-- outheis:migration:end -->\n*',
                        '\n',
                        content,
                        flags=re.DOTALL,
                    ).strip()
                parts.append(f"### {filename}\n\n```markdown\n{content}\n```")
            else:
                parts.append(f"### {filename}\n\n(existiert nicht)")

        # If Shadow.md is absent or sparse, trigger a background scan via zeno
        shadow_path = agenda_dir / "Shadow.md"
        shadow_sparse = (
            not shadow_path.exists()
            or len(shadow_path.read_text(encoding="utf-8").strip()) < 200
        )
        if shadow_sparse:
            self._trigger_shadow_scan()

        return "\n\n".join(parts)

    def _trigger_shadow_scan(self) -> None:
        """
        Request a shadow_scan from the dispatcher (fire-and-forget).

        The scan runs in a background thread via the existing task-locking
        mechanism — no double-run risk even if called repeatedly.
        """
        import uuid
        from outheis.core.config import get_messages_path
        from outheis.core.message import create_agent_message
        from outheis.core.queue import append

        msg = create_agent_message(
            from_agent="agenda",
            to="dispatcher",
            type="internal",
            intent="internal",
            payload={"text": "run_task:shadow_scan"},
            conversation_id=str(uuid.uuid4()),
        )
        append(get_messages_path(), msg)
        print("[agenda] Shadow.md sparse — shadow_scan requested", file=sys.stderr)
    
    
    def _get_tools(self) -> list[dict]:
        return [
            {
                "name": "get_daily",
                "description": (
                    "Return the verbatim content of Daily.md. "
                    "Call this whenever the user wants to see today's agenda. "
                    "Always return the result exactly as received — no modifications."
                ),
                "input_schema": {"type": "object", "properties": {}, "required": []},
            },
            {
                "name": "write_file",
                "description": "Write/replace a file (Daily.md, Inbox.md, or Exchange.md)",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "file": {"type": "string", "enum": ["daily", "inbox", "exchange"]},
                        "content": {"type": "string", "description": "Full content for the file"}
                    },
                    "required": ["file", "content"]
                }
            },
            {
                "name": "append_file",
                "description": "Append content to a file",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "file": {"type": "string", "enum": ["daily", "inbox", "exchange"]},
                        "content": {"type": "string", "description": "Content to append"}
                    },
                    "required": ["file", "content"]
                }
            },
            {
                "name": "load_skill",
                "description": "Load detailed skill instructions (if needed)",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string", "description": "Topic: structure, dates, inbox, exchange, reminders"}
                    },
                    "required": ["topic"]
                }
            },
        ]
    
    def _execute_tool(self, name: str, inputs: dict) -> str:
        agenda_dir = get_agenda_dir()
        if not agenda_dir:
            return "Kein Agenda-Verzeichnis gefunden."

        file_map = {"daily": "Daily.md", "inbox": "Inbox.md", "exchange": "Exchange.md"}

        if name == "get_daily":
            return self._tool_get_daily()

        elif name == "write_file":
            filename = file_map.get(inputs.get("file", "").lower())
            if not filename:
                return "Ungültige Datei. Wähle: daily, inbox, exchange"
            return self._write_file(agenda_dir / filename, inputs.get("content", ""))
        
        elif name == "append_file":
            filename = file_map.get(inputs.get("file", "").lower())
            if not filename:
                return "Ungültige Datei. Wähle: daily, inbox, exchange"
            return self._append_file(agenda_dir / filename, inputs.get("content", ""))
        
        elif name == "load_skill":
            return self._load_skill(inputs.get("topic", ""))
        
        else:
            return f"Unknown tool: {name}"
    
    # =========================================================================
    # FILE OPERATIONS
    # =========================================================================
    
    def _read_file(self, path: Path) -> str:
        """Read file, return content or message if not exists."""
        if not path.exists():
            return f"{path.name} existiert noch nicht."
        return path.read_text(encoding="utf-8")
    
    def _write_file(self, path: Path, content: str) -> str:
        """Write file."""
        try:
            path.write_text(content, encoding="utf-8")
            return f"✓ {path.name} geschrieben"
        except Exception as e:
            return f"Fehler: {e}"
    
    def _append_file(self, path: Path, content: str) -> str:
        """Append to file."""
        try:
            existing = path.read_text(encoding="utf-8") if path.exists() else ""
            path.write_text(existing + content, encoding="utf-8")
            return f"✓ An {path.name} angehängt"
        except Exception as e:
            return f"Fehler: {e}"
    
    def _load_skill(self, topic: str) -> str:
        """Load detailed skill."""
        skills_path = get_human_dir() / "skills" / "agenda.md"
        system_skills_path = Path(__file__).parent / "skills" / "agenda.md"
        
        content = ""
        if skills_path.exists():
            content += skills_path.read_text(encoding="utf-8")
        if system_skills_path.exists():
            content += "\n\n" + system_skills_path.read_text(encoding="utf-8")
        
        if not content:
            return "Keine Skills gefunden."
        
        # Find relevant section
        topic_lower = topic.lower()
        lines = content.split("\n")
        relevant = []
        in_section = False
        
        for line in lines:
            if line.startswith("## "):
                if topic_lower in line.lower():
                    in_section = True
                    relevant.append(line)
                elif in_section:
                    break
            elif in_section:
                relevant.append(line)
        
        if relevant:
            return "\n".join(relevant)
        return f"Kein Abschnitt '{topic}' gefunden."
    

    # =========================================================================
    # HASH-BASED CHANGE DETECTION
    # =========================================================================
    
    def _compute_hash(self, path: Path) -> str:
        """Compute MD5 hash of a file."""
        if not path.exists():
            return ""
        return hashlib.md5(path.read_bytes()).hexdigest()
    
    def _get_hash_cache_path(self) -> Path:
        """Get path to agenda hash cache."""
        return get_human_dir() / "cache" / "agenda" / "hashes.json"
    
    def _load_hashes(self) -> dict:
        """Load stored hashes from cache."""
        path = self._get_hash_cache_path()
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    
    def _save_hashes(self, hashes: dict) -> None:
        """Save current hashes to cache."""
        path = self._get_hash_cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(hashes, indent=2), encoding="utf-8")
    
        # =========================================================================
    # MESSAGE HANDLING
    # =========================================================================
    
    def _tool_get_daily(self) -> str:
        """Return Daily.md verbatim. Sets _passthrough_content for state saving."""
        agenda_dir = get_agenda_dir()
        if not agenda_dir:
            return "(Kein Agenda-Verzeichnis)"
        path = agenda_dir / "Daily.md"
        if not path.exists():
            return "(Daily.md existiert noch nicht)"
        content = path.read_text(encoding="utf-8")
        self._passthrough_content = content
        return content

    # =========================================================================
    # PASS-THROUGH STATE  (per user identity, Snowflake-based freshness)
    # =========================================================================
    #
    # Signal assigns a new conversation_id per message, so we key by the
    # sender's phone identity instead.
    #
    # Freshness is derived entirely from the message queue: on load, we
    # scan the last 50 messages for any to="transport" response with a
    # higher Snowflake ID than the stored pass-through that also replies
    # to a message from this identity.  If one exists, cato has since
    # spoken — context is stale.  No explicit clear step needed.

    def _passthrough_path(self) -> Path:
        return get_human_dir() / "cache" / "agenda" / "passthrough.json"

    def _save_passthrough(self, identity: str, response_id: str, content: str) -> None:
        """Persist pass-through response ID and content for this identity."""
        path = self._passthrough_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except Exception:
            data = {}
        data[identity] = {"id": response_id, "content": content}
        path.write_text(json.dumps(data), encoding="utf-8")

    def _load_passthrough(self, identity: str) -> str | None:
        """Return pass-through content if still the last message sent to this identity.

        Uses the message queue as the source of truth: if a newer to="transport"
        response exists that replies to a message from this identity, the
        pass-through is considered superseded and None is returned.
        """
        path = self._passthrough_path()
        if not path.exists():
            return None
        try:
            entry = json.loads(path.read_text(encoding="utf-8")).get(identity)
        except Exception:
            return None
        if not entry:
            return None

        passthrough_id: str = entry["id"]
        content: str = entry["content"]

        from outheis.core.config import get_messages_path
        from outheis.core.queue import read_last_n
        recent = read_last_n(get_messages_path(), 50)

        # IDs of messages that came FROM this identity (potential reply_to targets)
        user_ids = {m.id for m in recent if m.from_user and m.from_user.identity == identity}

        # Any newer outgoing response to this identity → context superseded
        superseded = any(
            m.to == "transport" and m.id > passthrough_id and m.reply_to in user_ids
            for m in recent
        )
        return None if superseded else content

    def handle(self, msg: Message) -> Message | None:
        """Handle incoming message with tools."""
        verbose = os.environ.get("OUTHEIS_VERBOSE")
        query = msg.payload.get("text", "")
        response_to = "transport" if msg.from_user else (msg.from_agent or "relay")
        identity = msg.from_user.identity if msg.from_user else None

        if not query:
            return self.respond(
                to=response_to,
                payload={"error": "Empty query"},
                conversation_id=msg.conversation_id,
                reply_to=msg.id,
            )

        prior = self._load_passthrough(identity) if identity else None
        self._passthrough_content = None  # reset; _tool_get_daily sets if called
        try:
            answer = self._process_with_tools(query, verbose, prior_content=prior)
            response = self.respond(
                to=response_to,
                payload={"text": answer},
                conversation_id=msg.conversation_id,
                reply_to=msg.id,
            )
            if identity and self._passthrough_content:
                self._save_passthrough(identity, response.id, self._passthrough_content)
            return response
        except Exception as e:
            return self.respond(
                to=response_to,
                payload={"error": str(e)},
                conversation_id=msg.conversation_id,
                reply_to=msg.id,
            )

    def handle_direct(self, query: str) -> str:
        """Direct query interface for Relay delegation."""
        self._passthrough_content = None
        return self._process_with_tools(query)

    def _process_with_tools(self, query: str, verbose: bool = False,
                             prior_content: str | None = None) -> str:
        """Process query using tools autonomously."""
        import sys
        from outheis.core.llm import call_llm

        if prior_content:
            # Inject the prior pass-through as a synthetic exchange so the LLM
            # knows what it last sent verbatim.
            messages = [
                {"role": "user", "content": "Zeig mir die aktuelle Agenda."},
                {"role": "assistant", "content": prior_content},
                {"role": "user", "content": query},
            ]
        else:
            messages = [{"role": "user", "content": query}]
        tools = self._get_tools()
        system = self.get_system_prompt()

        max_iterations = 7
        for iteration in range(max_iterations):
            response = call_llm(
                model=self.model_alias,
                agent=self.name,
                system=system,
                messages=messages,
                tools=tools,
                max_tokens=2048,
            )
            
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            
            if not tool_uses:
                text_parts = [b.text for b in response.content if hasattr(b, "text")]
                return "\n".join(text_parts) if text_parts else "Keine Antwort."
            
            tool_results = []
            for tool in tool_uses:
                if verbose:
                    print(f"[agenda tool: {tool.name}({tool.input})]", file=sys.stderr)

                result = self._execute_tool(tool.name, tool.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool.id,
                    "content": result,
                })

            # get_daily sets _passthrough_content — return verbatim, skip second LLM call
            if self._passthrough_content is not None:
                return self._passthrough_content

            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})
        
        return "Maximale Iterationen erreicht."
    
    # =========================================================================
    # SCHEDULED TASKS
    # =========================================================================
    
    def run_hourly_review(self, force: bool = False) -> None:
        """
        Hourly review — called by scheduler at xx:55.
        
        - force=True: unconditional run (04:55 = morning, 23:55 = evening)
        - force=False: skip if no agenda files changed (hash-based)
        """
        import sys
        
        now = datetime.now()
        timestamp = now.isoformat()
        
        agenda_dir = get_agenda_dir()
        if not agenda_dir:
            return
        
        filenames = ["Daily.md", "Inbox.md", "Exchange.md"]
        current_hashes = {f: self._compute_hash(agenda_dir / f) for f in filenames}
        
        comment_trigger = False
        if not force:
            stored_hashes = self._load_hashes()
            if current_hashes == stored_hashes:
                # Still run if Daily.md has unprocessed user comments
                daily_path = agenda_dir / "Daily.md"
                has_comments = daily_path.exists() and any(
                    line.startswith(">") for line in daily_path.read_text(encoding="utf-8").splitlines()
                )
                if not has_comments:
                    print(f"[{timestamp}] Agenda: no changes, skipping", file=sys.stderr)
                    return
                comment_trigger = True

        # Build context-aware prompt
        hour = now.hour
        if force and hour <= 6:
            context = "Morgenreview: Erstelle oder aktualisiere Daily.md für heute."
        elif force and hour >= 22:
            context = "Abendreview: Schließe den Tag ab, archiviere was erledigt ist."
        elif force:
            context = "Pflichtreview."
        elif comment_trigger:
            context = "User-Kommentare in Daily.md erkannt — bitte verarbeiten."
        else:
            context = "Änderungen in Agenda-Dateien erkannt."
        
        query = (
            f"Es ist {now.strftime('%H:%M')} Uhr. {context}\n\n"
            "Du hast bereits alle aktuellen Dateien im Kontext oben.\n\n"
            "Führe folgende Schritte aus:\n"
            "1. Inbox verarbeiten: Jeden Eintrag nach Daily.md übertragen oder via Exchange.md klären. "
            "Dann Inbox.md LEER schreiben — nur Header `# Inbox\\n\\n---`. Kein Eintrag darf stehen bleiben.\n"
            "2. Daily.md prüfen: Neuer Tag? User-Kommentare (Zeilen mit '>') lesen, als Anweisungen ausführen, dann LÖSCHEN — keine '>'-Zeile darf in der regenerierten Daily.md erscheinen.\n"
            "3. Exchange.md prüfen: User-Antworten verarbeiten?\n\n"
            "Antworte kurz was du getan hast."
        )
        
        try:
            result = self._process_with_tools(query)
            # Save hashes after successful run (so failed runs get retried)
            self._save_hashes(current_hashes)
            print(f"[{timestamp}] Agenda: {result[:120]}", file=sys.stderr)
        except Exception as e:
            print(f"[{timestamp}] Agenda error: {e}", file=sys.stderr)
    
    def refresh_daily(self) -> str:
        """Manual refresh — called by user command."""
        return self._process_with_tools(
            "Aktualisiere Daily.md für heute. Prüfe ob das Datum stimmt, "
            "ob die Struktur passt. Verarbeite Inbox-Items wenn vorhanden. "
            "Berichte was du getan hast."
        )
    
    def insert_to_daily(self, content: str, section: str | None = None) -> bool:
        """Insert content to Daily.md — called by Relay."""
        section_hint = f" in Sektion '{section}'" if section else ""
        result = self._process_with_tools(
            f"Füge folgendes zu Daily.md hinzu{section_hint}: {content}"
        )
        return "✓" in result or "hinzugefügt" in result.lower()
    
    # =========================================================================
    # LEARNING
    # =========================================================================
    
    def learn_preference(self, category: str, preference: str) -> None:
        """Store learned preference in skills."""
        from outheis.agents.loader import append_user_skill
        append_user_skill("agenda", preference, section=category)
    
    def remember(self, content: str, memory_type: str = "feedback") -> None:
        """Store in memory."""
        from outheis.core.memory import get_memory_store
        store = get_memory_store()
        store.add(content, memory_type)


# =============================================================================
# FACTORY
# =============================================================================

def create_agenda_agent(model_alias: str | None = None) -> AgendaAgent:
    """Create Agenda agent with config."""
    if model_alias:
        return AgendaAgent(model_alias=model_alias)
    
    config = load_config()
    agent_cfg = config.agents.get("agenda")
    if agent_cfg:
        return AgendaAgent(model_alias=agent_cfg.model)
    return AgendaAgent()
