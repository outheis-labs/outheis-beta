"""
Data agent (zeno).

Autonomous knowledge management across all vaults.
Can read AND write. Decides formatting itself.
Uses tools for file operations, LLM for decisions.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from outheis.agents.base import BaseAgent
from outheis.core.config import load_config, get_human_dir
from outheis.core.index import SearchIndex, create_index
from outheis.core.message import Message
from outheis.core.vault import read_file, VaultFile


# =============================================================================
# DATA AGENT
# =============================================================================

@dataclass
class DataAgent(BaseAgent):
    """
    Data agent handles vault operations — read AND write.
    
    Autonomous: decides what to do based on request.
    Uses tools for file operations.
    Learns formatting preferences from corrections.
    """
    
    name: str = "data"
    _indices: dict[str, SearchIndex] = field(default_factory=dict, repr=False)
    
    def get_system_prompt(self) -> str:
        """
        Build system prompt with INDEX as context.
        
        Unlike Agenda (3 small files → full context),
        Data manages a potentially large Vault.
        
        Strategy: Index + Heuristics in context, detail via tools.
        """
        from outheis.core.memory import get_memory_context
        from outheis.agents.loader import load_skills, load_rules
        
        config = load_config()
        memory = get_memory_context()
        skills = load_skills("data")
        rules = load_rules("data")
        
        # Load vault index as context (not all files)
        vault_overview = self._get_vault_overview()
        
        parts = [
            "# Data Agent (zeno)",
            "",
            "Du verwaltest den Vault. Lesen UND Schreiben.",
            "",
            "## Vault-Übersicht (Index)",
            "",
            vault_overview,
            "",
            "---",
            "",
            "## Verfügbare Tools",
            "- search(query) — Suche im Vault (wenn Index nicht reicht)",
            "- read_file(path) — Datei-Detail laden",
            "- write_file(path, content) — Datei schreiben",
            "- append_file(path, content) — An Datei anhängen",
            "- load_skill(topic) — Detail-Skills nachladen",
            "",
            "## Prinzipien",
            "- Du HAST den Index oben — nicht nochmal suchen wenn Info da",
            "- read_file nur wenn Detail nötig",
            "- Formatierung: wie der User es macht",
            "- Bei Unsicherheit fragen",
            "",
            f"Sprache: {config.human.language}",
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
    
    def _get_vault_overview(self) -> str:
        """
        Get vault overview from index.
        
        This is the key scaling mechanism:
        - Show file names, tags, recent changes
        - NOT full content
        - Agent uses read_file for detail
        """
        config = load_config()
        vault = config.human.primary_vault()
        
        if not vault.exists():
            return "(Kein Vault konfiguriert)"
        
        # Try to load cached index
        cache_dir = get_human_dir() / "cache" / "index"
        index_file = cache_dir / f"{vault.name}.jsonl"
        
        if index_file.exists():
            return self._format_index(index_file)
        
        # Fallback: quick file listing
        return self._quick_listing(vault)
    
    def _format_index(self, index_file: Path) -> str:
        """Format index as overview for context."""
        import json
        
        lines = []
        try:
            with open(index_file, "r", encoding="utf-8") as f:
                entries = [json.loads(line) for line in f if line.strip()]
            
            # Sort by recency (most recent first)
            entries.sort(key=lambda e: e.get("mtime", ""), reverse=True)
            
            # Show recent files with tags
            lines.append(f"**{len(entries)} Dateien im Vault**")
            lines.append("")
            lines.append("Kürzlich geändert:")
            
            for entry in entries[:15]:  # Top 15 recent
                name = entry.get("name", "?")
                tags = entry.get("tags", [])
                tag_str = " ".join(f"#{t}" for t in tags[:3]) if tags else ""
                lines.append(f"- {name} {tag_str}")
            
            if len(entries) > 15:
                lines.append(f"- ... und {len(entries) - 15} weitere")
            
        except Exception as e:
            lines.append(f"(Index-Fehler: {e})")
        
        return "\n".join(lines)
    
    def _quick_listing(self, vault: Path) -> str:
        """Quick file listing when no index available."""
        files = list(vault.glob("*.md"))[:20]
        
        if not files:
            return "(Vault ist leer)"
        
        lines = [f"**{len(list(vault.glob('*.md')))} .md Dateien**", ""]
        for f in files:
            lines.append(f"- {f.name}")
        
        if len(list(vault.glob("*.md"))) > 20:
            lines.append("- ... (mehr Dateien vorhanden)")
        
        return "\n".join(lines)
    
    def _get_tools(self) -> list[dict]:
        """
        Define available tools — INDEX-FIRST APPROACH.
        
        Agent has vault overview in context.
        Tools for: search (scale), read (detail), write (output).
        
        Removed: list_dir, file_exists, get_tags (redundant with index).
        """
        return [
            {
                "name": "search",
                "description": "Search vault when index overview isn't enough",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"}
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "read_file",
                "description": "Read file detail (you have names from index)",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Filename from index"}
                    },
                    "required": ["path"]
                }
            },
            {
                "name": "write_file",
                "description": "Write or create file in vault",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Filename"},
                        "content": {"type": "string", "description": "File content"}
                    },
                    "required": ["path", "content"]
                }
            },
            {
                "name": "append_file",
                "description": "Append content to existing file",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Filename"},
                        "content": {"type": "string", "description": "Content to append"}
                    },
                    "required": ["path", "content"]
                }
            },
            {
                "name": "load_skill",
                "description": "Load detailed skill instructions",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string", "description": "Topic: formatting, tags, dates, structure"}
                    },
                    "required": ["topic"]
                }
            },
        ]
    
    def _execute_tool(self, name: str, inputs: dict) -> str:
        """Execute a tool and return result."""
        config = load_config()
        vault = config.human.primary_vault()
        
        if name == "search":
            return self._tool_search(inputs.get("query", ""))
        
        elif name == "read_file":
            return self._tool_read_file(vault, inputs.get("path", ""))
        
        elif name == "write_file":
            return self._tool_write_file(vault, inputs.get("path", ""), inputs.get("content", ""))
        
        elif name == "append_file":
            return self._tool_append_to_file(vault, inputs.get("path", ""), inputs.get("content", ""))
        
        elif name == "load_skill":
            return self._tool_load_skill(inputs.get("topic", ""))
        
        else:
            return f"Unknown tool: {name}"
    
    # =========================================================================
    # TOOL IMPLEMENTATIONS
    # =========================================================================
    
    def _tool_search(self, query: str) -> str:
        """Search vault."""
        if not query:
            return "No query provided"
        
        self._ensure_index_fresh()
        results = []
        for index in self._get_indices():
            for entry in index.search(query, limit=5, track_access=True):
                results.append({
                    "path": entry.path,
                    "title": entry.title,
                    "tags": entry.tags,
                })
        
        if not results:
            return "Keine Ergebnisse gefunden."
        
        return json.dumps(results, ensure_ascii=False, indent=2)
    
    def _tool_read_file(self, vault: Path, path: str) -> str:
        """Read file from vault."""
        full_path = vault / path
        if not full_path.exists():
            return f"Datei nicht gefunden: {path}"
        if not full_path.is_file():
            return f"Ist ein Verzeichnis, keine Datei: {path}"
        
        try:
            content = full_path.read_text(encoding="utf-8")
            return content
        except Exception as e:
            return f"Fehler beim Lesen: {e}"
    
    def _tool_write_file(self, vault: Path, path: str, content: str) -> str:
        """Write file to vault."""
        if not path:
            return "Kein Pfad angegeben"
        
        full_path = vault / path
        
        # Create parent directories if needed
        full_path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            full_path.write_text(content, encoding="utf-8")
            # Update index
            self._ensure_index_fresh()
            return f"✓ Geschrieben: {path}"
        except Exception as e:
            return f"Fehler beim Schreiben: {e}"
    
    def _tool_append_to_file(self, vault: Path, path: str, content: str) -> str:
        """Append to file in vault."""
        full_path = vault / path
        
        if not full_path.exists():
            return f"Datei nicht gefunden: {path}"
        
        try:
            existing = full_path.read_text(encoding="utf-8")
            full_path.write_text(existing + content, encoding="utf-8")
            return f"✓ Angehängt an: {path}"
        except Exception as e:
            return f"Fehler: {e}"
    
    def _tool_list_dir(self, vault: Path, path: str) -> str:
        """List directory contents."""
        target = vault / path if path else vault
        
        if not target.exists():
            return f"Verzeichnis nicht gefunden: {path or '/'}"
        if not target.is_dir():
            return f"Ist eine Datei, kein Verzeichnis: {path}"
        
        try:
            items = []
            for item in sorted(target.iterdir()):
                if item.name.startswith("."):
                    continue
                item_type = "dir" if item.is_dir() else "file"
                items.append({"name": item.name, "type": item_type})
            
            return json.dumps(items, ensure_ascii=False, indent=2)
        except Exception as e:
            return f"Fehler: {e}"
    
    def _tool_file_exists(self, vault: Path, path: str) -> str:
        """Check if path exists."""
        full_path = vault / path
        
        if full_path.exists():
            if full_path.is_dir():
                return f"Ja, Verzeichnis existiert: {path}"
            else:
                return f"Ja, Datei existiert: {path}"
        else:
            # Try fuzzy search
            results = self.find_by_path(path)
            if results:
                matches = [r[1].path for r in results[:3]]
                return f"Nicht gefunden: {path}\nÄhnliche: {', '.join(matches)}"
            return f"Nicht gefunden: {path}"
    
    def _tool_get_tags(self) -> str:
        """Get all tags with counts."""
        self._ensure_index_fresh()
        all_tags = {}
        for index in self._get_indices():
            for tag, count in index.get_all_tags().items():
                all_tags[tag] = all_tags.get(tag, 0) + count
        
        sorted_tags = sorted(all_tags.items(), key=lambda x: -x[1])
        lines = [f"#{tag}: {count}" for tag, count in sorted_tags[:20]]
        return "\n".join(lines) if lines else "Keine Tags gefunden."
    
    def _tool_load_skill(self, topic: str) -> str:
        """Load detailed skill from file."""
        skills_path = get_human_dir() / "skills" / "data.md"
        
        # Also check system skills
        system_skills_path = Path(__file__).parent / "skills" / "data.md"
        
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
                    break  # End of relevant section
            elif in_section:
                relevant.append(line)
        
        if relevant:
            return "\n".join(relevant)
        else:
            # Return summary if no specific section found
            return f"Kein Abschnitt '{topic}' gefunden. Verfügbar:\n{content[:500]}..."
    
    # =========================================================================
    # INDEX MANAGEMENT
    # =========================================================================
    
    def _get_indices(self) -> list[SearchIndex]:
        """Get or create search indices for all vaults."""
        config = load_config()
        vaults = config.human.all_vaults()
        
        indices = []
        for vault_path in vaults:
            if not vault_path.exists():
                continue
            
            key = str(vault_path)
            if key not in self._indices:
                self._indices[key] = create_index(vault_path)
                self._indices[key].update()
            
            indices.append(self._indices[key])
        
        return indices
    
    def _ensure_index_fresh(self) -> None:
        """Ensure indices are up-to-date."""
        for index in self._get_indices():
            added, updated, removed = index.update()
            if added or updated or removed:
                import sys
                print(f"[index] {index.vault_root.name}: +{added} ~{updated} -{removed}", file=sys.stderr)
    
    def find_by_path(self, pattern: str) -> list[tuple[SearchIndex, any]]:
        """Find files by path pattern across all vaults."""
        results = []
        for index in self._get_indices():
            for entry in index.find_by_path(pattern):
                results.append((index, entry))
        return results
    
    # =========================================================================
    # MESSAGE HANDLING
    # =========================================================================
    
    def handle(self, msg: Message) -> Message | None:
        """Handle incoming message with tool-based approach."""
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
        return self._process_with_tools(query)
    
    def _process_with_tools(self, query: str, verbose: bool = False) -> str:
        """Process query using tools autonomously."""
        import sys
        from outheis.core.llm import call_llm
        
        messages = [{"role": "user", "content": query}]
        tools = self._get_tools()
        
        # Tool use loop
        max_iterations = 10  # Komplexe Vault-Operationen brauchen mehr Tools
        system = self.get_system_prompt()
        for iteration in range(max_iterations):
            # Budget warning when running low
            if iteration == max_iterations - 2:
                messages.append({
                    "role": "user",
                    "content": "[System: Nur noch 2 Tool-Aufrufe möglich. Fasse jetzt zusammen mit dem was du hast.]"
                })

            response = call_llm(
                model=self.model_alias,
                system=system,
                messages=messages,
                tools=tools,
                max_tokens=2048,
            )
            
            # Check for tool use
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            
            if not tool_uses:
                # No tools, extract text response
                text_parts = [b.text for b in response.content if hasattr(b, "text")]
                return "\n".join(text_parts) if text_parts else "Keine Antwort."
            
            # Execute tools
            tool_results = []
            for tool in tool_uses:
                if verbose:
                    print(f"[data tool: {tool.name}({tool.input})]", file=sys.stderr)
                
                result = self._execute_tool(tool.name, tool.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool.id,
                    "content": result,
                })
            
            # Add assistant response and tool results to messages
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})
        
        return "Maximale Iterationen erreicht."
    
    # =========================================================================
    # LEARNING
    # =========================================================================
    
    def learn_preference(self, category: str, preference: str) -> None:
        """
        Store a learned preference in skills.
        
        Called when user corrects the agent.
        """
        from outheis.agents.loader import append_user_skill
        append_user_skill("data", preference, section=category)
    
    def remember(self, content: str, memory_type: str = "feedback") -> None:
        """Store something in memory."""
        from outheis.core.memory import get_memory_store
        store = get_memory_store()
        store.add(content, memory_type)

    # =========================================================================
    # SHADOW SCAN
    # =========================================================================
    
    def scan_chronological_entries(self) -> int:
        """
        Scan vault for chronological entries, write to Shadow.md.

        Uses a file-state cache (name → size + mtime) to process only new or
        changed files.  Shadow.md is organised by source file with
        <!-- BEGIN/END --> section markers so individual sections can be
        replaced or removed without touching the rest.

        Returns the number of files actually processed this run.
        """
        config = load_config()
        primary_vault = config.human.primary_vault()
        shadow_path = primary_vault / "Agenda" / "Shadow.md"
        cache_path = get_human_dir() / "cache" / "shadow" / "file_state.json"

        old_hashes = self._load_shadow_cache(cache_path)
        current_files = self._get_vault_files(primary_vault)

        current_hashes = {
            name: self._hash_file(path)
            for name, path in current_files.items()
        }

        new_files     = {n: p for n, p in current_files.items() if n not in old_hashes}
        changed_files = {
            n: p for n, p in current_files.items()
            if n in old_hashes and current_hashes[n] != old_hashes[n]
        }
        deleted_names = set(old_hashes) - set(current_files)

        files_to_process = {**new_files, **changed_files}

        if not files_to_process and not deleted_names:
            return 0

        sections = self._parse_shadow_sections(shadow_path)

        for name in deleted_names:
            sections.pop(name, None)

        processed = 0
        for name, path in files_to_process.items():
            try:
                content = path.read_text(encoding="utf-8")
                entries = self._extract_chronological_entries(name, content)
                if entries:
                    sections[name] = entries
                else:
                    sections.pop(name, None)
                processed += 1
            except Exception as e:
                print(f"Shadow scan: error processing {name}: {e}")

        self._write_shadow(shadow_path, sections)
        self._save_shadow_cache(cache_path, current_hashes)

        return processed

    def _get_vault_files(self, vault: Path) -> dict[str, Path]:
        """All .md files in vault, excluding the Agenda/ directory itself."""
        agenda_dir = vault / "Agenda"
        files: dict[str, Path] = {}
        for path in vault.rglob("*.md"):
            try:
                path.relative_to(agenda_dir)
                continue  # skip anything inside Agenda/
            except ValueError:
                pass
            if any(part.startswith(".") for part in path.parts):
                continue
            files[str(path.relative_to(vault))] = path
        return files

    def _hash_file(self, path: Path) -> str:
        """MD5 hash of file content."""
        import hashlib
        return hashlib.md5(path.read_bytes()).hexdigest()

    def _load_shadow_cache(self, cache_path: Path) -> dict:
        """Load {filename: md5} cache."""
        if not cache_path.exists():
            return {}
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_shadow_cache(self, cache_path: Path, hashes: dict) -> None:
        """Save {filename: md5} cache."""
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(hashes, indent=2), encoding="utf-8")

    def _parse_shadow_sections(self, shadow_path: Path) -> dict[str, str]:
        """Parse Shadow.md into {filename: body} using BEGIN/END markers."""
        import re
        sections: dict[str, str] = {}
        if not shadow_path.exists():
            return sections
        content = shadow_path.read_text(encoding="utf-8")
        pattern = re.compile(
            r"<!-- BEGIN: (.+?) -->\n(.*?)<!-- END: .+? -->",
            re.DOTALL,
        )
        for match in pattern.finditer(content):
            sections[match.group(1)] = match.group(2).rstrip()
        return sections

    def _write_shadow(self, shadow_path: Path, sections: dict[str, str]) -> None:
        """Write Shadow.md from {filename: body} dict, sorted by filename."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        lines = [
            "# Shadow — Vault Chronological Index",
            f"*Zuletzt aktualisiert: {timestamp}*",
            "",
        ]
        for name in sorted(sections):
            lines.append(f"<!-- BEGIN: {name} -->")
            lines.append(f"## {name}")
            lines.append(sections[name])
            lines.append(f"<!-- END: {name} -->")
            lines.append("")
        shadow_path.parent.mkdir(parents=True, exist_ok=True)
        shadow_path.write_text("\n".join(lines), encoding="utf-8")

    def _extract_chronological_entries(self, filename: str, content: str) -> str:
        """
        Extract chronological entries from one file's full content via LLM.

        Uses the full agent system prompt (skills, memories, rules) so pattern
        recognition is not limited to static heuristics.

        Returns a formatted markdown bullet list, or empty string if none found.
        """
        from outheis.core.llm import call_llm

        prompt = (
            f"Datei: {filename}\n\n"
            f"{content}\n\n"
            "---\n"
            "Erkenne alle zeitlich relevanten Einträge in dieser Datei — nicht nur explizite "
            "Termine und Deadlines, sondern auch implizite: ausstehende Projekte, Abhängigkeiten "
            "(\"nach Abschluss von X\"), Wiedervorlagen, offene Aufgaben mit zeitlichem Bezug, "
            "überfällige Punkte, Projektphasen die noch nicht begonnen haben.\n\n"
            "Format — antworte NUR mit einer Markdown-Bullet-Liste, kein anderer Text:\n"
            "- ⏰ **2026-05-15** Mokatassen bei Suzanne Bühler abholen `#action-required`\n"
            "- 📅 **—** Willi Stemmer: Workshop-Finanzierung besprechen nach Rückkehr\n"
            "- 📋 **nach Tisch Strauss** Galina Schwarz: Projektstart Kommode + Truhe\n\n"
            "Icons: ⏰ deadline · 📅 appointment · 🎂 birthday · 🔄 recurring · 📋 task/pending\n"
            "Wenn keine zeitlich relevanten Einträge vorhanden: antworte mit NONE"
        )

        try:
            response = call_llm(
                model=self.model_alias,
                system=self.get_system_prompt(),
                messages=[{"role": "user", "content": prompt}],
                max_tokens=4096,
            )
            text = response.content[0].text.strip()
            return "" if text == "NONE" else text
        except Exception as e:
            print(f"Shadow scan: LLM error for {filename}: {e}")
            return ""


# =============================================================================
# FACTORY
# =============================================================================

def create_data_agent(model_alias: str | None = None) -> DataAgent:
    """Create Data agent with config."""
    from outheis.core.config import load_config
    config = load_config()
    
    if model_alias:
        return DataAgent(model_alias=model_alias)
    
    agent_cfg = config.agents.get("data")
    if agent_cfg:
        return DataAgent(model_alias=agent_cfg.model)
    
    return DataAgent()
