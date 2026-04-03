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
            "## Verfügbare Tools (nur Output)",
            "- write_file(file, content) — Datei schreiben (daily/inbox/exchange)",
            "- append_file(file, content) — An Datei anhängen",
            "- load_skill(topic) — Detail-Skills nachladen wenn nötig",
            "",
            "## Prinzipien",
            "- Struktur des Users übernehmen, nicht aufzwingen",
            "- Du HAST bereits alle Dateien oben — nicht nochmal lesen",
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
        """
        Define available tools — OUTPUT ONLY.
        
        Context is provided in system prompt.
        Tools are only for writing, not reading.
        """
        return [
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
        """
        Execute a tool — OUTPUT ONLY.
        
        No read tools needed since context is in system prompt.
        """
        agenda_dir = get_agenda_dir()
        if not agenda_dir:
            return "Kein Agenda-Verzeichnis gefunden."
        
        file_map = {
            "daily": "Daily.md",
            "inbox": "Inbox.md",
            "exchange": "Exchange.md",
        }
        
        if name == "write_file":
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
    
    _READ_KEYWORDS = {
        "agenda", "daily", "daily.md", "today", "heute", "tag",
        "was steht", "was liegt", "was gibt", "zeig", "zeige",
        "wie schaut", "was habe ich", "was hab ich", "überblick",
        "tagesplan", "tagesagenda", "was ist heute",
    }
    _WRITE_KEYWORDS = {
        "update", "aktualisier", "add", "füge", "hinzufüg", "eintrag",
        "remove", "entfern", "lösch", "mark", "markier", "erledigt",
        "change", "änder", "schreib", "write", "verschieb", "postpone",
        "erstell", "create", "regenerier", "refresh",
    }

    def _is_read_query(self, query: str) -> bool:
        """True if query is a read-only request for the current agenda."""
        q = query.lower()
        has_read = any(kw in q for kw in self._READ_KEYWORDS)
        has_write = any(kw in q for kw in self._WRITE_KEYWORDS)
        return has_read and not has_write

    def _get_daily_content(self) -> str | None:
        """Return raw Daily.md content, or None if not found."""
        agenda_dir = get_agenda_dir()
        if not agenda_dir:
            return None
        path = agenda_dir / "Daily.md"
        return path.read_text(encoding="utf-8") if path.exists() else None

    def handle(self, msg: Message) -> Message | None:
        """Handle incoming message with tools."""
        import sys

        verbose = os.environ.get("OUTHEIS_VERBOSE")
        query = msg.payload.get("text", "")
        response_to = "transport" if msg.from_user else (msg.from_agent or "relay")

        if not query:
            return self.respond(
                to=response_to,
                payload={"error": "Empty query"},
                conversation_id=msg.conversation_id,
                reply_to=msg.id,
            )

        # Read-only agenda query: return Daily.md verbatim, skip LLM
        if self._is_read_query(query):
            content = self._get_daily_content()
            if content:
                return self.respond(
                    to=response_to,
                    payload={"text": content},
                    conversation_id=msg.conversation_id,
                    reply_to=msg.id,
                )

        try:
            answer = self._process_with_tools(query, verbose)
            
            return self.respond(
                to=response_to,
                payload={"text": answer},
                conversation_id=msg.conversation_id,
                reply_to=msg.id,
            )
        except Exception as e:
            return self.respond(
                to=response_to,
                payload={"error": str(e)},
                conversation_id=msg.conversation_id,
                reply_to=msg.id,
            )
    
    def handle_direct(self, query: str) -> str:
        """Direct query interface for Relay delegation."""
        if self._is_read_query(query):
            content = self._get_daily_content()
            if content:
                return content
        return self._process_with_tools(query)
    
    def _process_with_tools(self, query: str, verbose: bool = False) -> str:
        """Process query using tools autonomously."""
        import sys
        from outheis.core.llm import call_llm
        
        messages = [{"role": "user", "content": query}]
        tools = self._get_tools()
        system = self.get_system_prompt()

        max_iterations = 7
        for iteration in range(max_iterations):
            response = call_llm(
                model=self.model_alias,
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
