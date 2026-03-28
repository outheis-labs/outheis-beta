"""
Pattern agent (rumi).

Reflection, insight extraction, learning, and knowledge generalization.

Unlike other agents, Pattern works in the background:
- Analyzes conversations for memorable information
- Maintains Memory (user/feedback/context)
- Distills User Rules from stable patterns
- Learns how to learn (meta-memory for own strategies)

All processing happens locally. Nothing leaves the user's control.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from outheis.agents.base import BaseAgent
from outheis.core.message import Message
from outheis.core.memory import get_memory_store, MemoryType
from outheis.core.queue import read_last_n
from outheis.core.config import get_messages_path, get_human_dir, get_rules_dir, get_skills_dir, load_config


def get_seed_dir() -> Path:
    """Get path to seed directory."""
    path = get_human_dir() / "memory" / "seed"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_seed_staging_path() -> Path:
    """Get path to seed.json staging file."""
    return get_human_dir() / "memory" / "seed.json"


# =============================================================================
# PATTERN AGENT
# =============================================================================

@dataclass
class PatternAgent(BaseAgent):
    """
    Pattern agent handles reflection and learning.
    
    Works silently in the background to maintain memory and
    distill user rules from observed patterns.
    """

    name: str = "pattern"
    
    @property
    def meta_memory_path(self) -> Path:
        """Path to Pattern agent's own memory (strategies, learnings)."""
        path = get_human_dir() / "memory" / "pattern"
        path.mkdir(parents=True, exist_ok=True)
        return path
    
    def get_system_prompt(self) -> str:
        from outheis.core.memory import get_memory_context
        from outheis.agents.loader import load_skills, load_rules
        
        memory = get_memory_context()
        skills = load_skills("pattern")
        rules = load_rules("pattern")
        meta_memory = self._load_meta_memory()
        
        parts = []
        
        if skills:
            parts.append(f"# Skills\n\n{skills}")
        if rules:
            parts.append(f"# Rules\n\n{rules}")
        if memory:
            parts.append(f"# Memory\n\n{memory}")
        if meta_memory:
            parts.append(f"# Your Learning History\n\n{meta_memory}")
        
        return "\n\n---\n\n".join(parts)
    
    def _load_meta_memory(self) -> str:
        """Load Pattern agent's own memory about extraction strategies."""
        strategies_file = self.meta_memory_path / "strategies.md"
        if strategies_file.exists():
            return strategies_file.read_text(encoding="utf-8")
        return ""
    
    def _save_meta_memory(self, content: str) -> None:
        """Save to Pattern agent's own memory."""
        strategies_file = self.meta_memory_path / "strategies.md"
        strategies_file.write_text(content, encoding="utf-8")
    
    def _append_meta_insight(self, insight: str) -> None:
        """Append an insight to Pattern agent's memory."""
        current = self._load_meta_memory()
        timestamp = datetime.now().strftime("%Y-%m-%d")
        new_entry = f"\n## {timestamp}\n{insight}\n"
        self._save_meta_memory(current + new_entry)

    def handle(self, msg: Message) -> Message | None:
        """Handle an incoming message (direct query to pattern agent)."""
        query = msg.payload.get("text", "")
        
        if "analyze" in query.lower() or "memory" in query.lower():
            count = self.analyze_recent_conversations()
            return self.respond(
                to=msg.from_agent or "relay",
                payload={
                    "text": f"Analyzed recent conversations. Extracted {count} new memory entries.",
                },
                conversation_id=msg.conversation_id,
                reply_to=msg.id,
            )
        
        return self.respond(
            to=msg.from_agent or "relay",
            payload={
                "text": "Pattern agent is ready. Use 'analyze memory' to trigger analysis.",
            },
            conversation_id=msg.conversation_id,
            reply_to=msg.id,
        )

    def analyze_recent_conversations(self, hours: int = 24) -> int:
        """
        Analyze recent conversations and extract memory.
        
        Returns number of new memory entries created.
        """
        messages_path = get_messages_path()
        recent_messages = read_last_n(messages_path, 100)
        
        cutoff = datetime.now() - timedelta(hours=hours)
        user_messages = [
            m for m in recent_messages
            if m.from_user and datetime.fromtimestamp(m.timestamp) > cutoff
        ]
        
        if not user_messages:
            return 0
        
        conversation_text = self._build_conversation_context(user_messages)
        
        store = get_memory_store()
        current_memory = store.to_prompt_context()
        
        extractions = self._extract_with_llm(conversation_text, current_memory)
        
        count = 0
        for extraction in extractions:
            memory_type = extraction.get("type")
            content = extraction.get("content")
            confidence = extraction.get("confidence", 0.8)
            decay_days = extraction.get("decay_days")
            
            if memory_type in ["user", "feedback", "context"] and content:
                store.add(
                    content,
                    memory_type,
                    confidence=confidence,
                    decay_days=decay_days,
                )
                count += 1
        
        expired = store.cleanup_expired()
        if expired > 0:
            print(f"[Pattern] Cleaned up {expired} expired memory entries")
        
        return count
    
    def _build_conversation_context(self, messages: list[Message]) -> str:
        """Build a text context from messages for analysis."""
        lines = []
        for msg in messages[-10:]:
            text = msg.payload.get("text", "")
            if text:
                lines.append(f"User: {text}")
        
        return "\n".join(lines)
    
    def _extract_with_llm(self, conversation_text: str, current_memory: str) -> list[dict]:
        """Use LLM to extract memorable information."""
        config = load_config()
        
        user_prompt = f"""Current memory (don't repeat this):
{current_memory if current_memory else "(empty)"}

---

Recent conversation:
{conversation_text}

---

Extract any NEW information worth remembering. Use your judgment — don't be mechanical.

Respond in JSON:
{{
  "extractions": [
    {{"type": "user|feedback|context", "content": "...", "confidence": 0.0-1.0, "decay_days": null|number}}
  ],
  "reasoning": "Brief explanation"
}}"""
        
        try:
            from outheis.core.llm import call_llm
            
            response = call_llm(
                model=self.model_alias,
                agent=self.name,
                system=self.get_system_prompt(),
                messages=[{"role": "user", "content": user_prompt}],
                max_tokens=1000,
            )
            
            response_text = response.content[0].text.strip()
            
            if response_text.startswith("```"):
                lines = response_text.split("\n")
                response_text = "\n".join(lines[1:-1])
            
            data = json.loads(response_text)
            return data.get("extractions", [])
            
        except Exception as e:
            print(f"Pattern agent extraction error: {e}")
            return []

    def consider_user_rules(self) -> int:
        """
        Review Memory and consider promoting stable patterns to User Rules.
        
        Returns number of new rules created.
        """
        store = get_memory_store()
        all_memory = store.get_all()
        
        if not any(all_memory.values()):
            return 0
        
        memory_summary = store.to_prompt_context()
        current_rules = self._load_current_user_rules()
        
        prompt = f"""Review this Memory and consider if any patterns are stable enough to become User Rules.

CURRENT MEMORY:
{memory_summary}

CURRENT USER RULES:
{current_rules if current_rules else "(none)"}

User Rules are persistent behavioral guidelines for agents. They should be:
- Clearly established and stable
- Genuinely helpful for future interactions
- Not contradicted by the user

If you see patterns worth promoting, respond with:
{{
  "new_rules": [
    {{"agent": "relay|data|agenda|common", "rule": "Clear, actionable statement"}}
  ],
  "reasoning": "Why these are worth promoting"
}}

If nothing is ready for promotion:
{{
  "new_rules": [],
  "reasoning": "Why not"
}}"""

        try:
            from outheis.core.llm import call_llm
            
            response = call_llm(
                model=self.model_alias,
                agent=self.name,
                system=self.get_system_prompt(),
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1000,
            )
            
            response_text = response.content[0].text.strip()
            if response_text.startswith("```"):
                lines = response_text.split("\n")
                response_text = "\n".join(lines[1:-1])
            
            data = json.loads(response_text)
            new_rules = data.get("new_rules", [])
            
            count = 0
            for rule_data in new_rules:
                agent = rule_data.get("agent", "common")
                rule = rule_data.get("rule", "")
                if rule:
                    self._append_user_rule(agent, rule)
                    count += 1
            
            return count
            
        except Exception as e:
            print(f"Pattern agent rule consideration error: {e}")
            return 0
    
    def _load_current_user_rules(self) -> str:
        """Load all current user rules as text."""
        rules_dir = get_rules_dir()
        if not rules_dir.exists():
            return ""
        
        parts = []
        for rule_file in rules_dir.glob("*.md"):
            content = rule_file.read_text(encoding="utf-8").strip()
            if content:
                parts.append(f"## {rule_file.stem}\n{content}")
        
        return "\n\n".join(parts)
    
    def _append_user_rule(self, agent: str, rule: str) -> None:
        """Append a rule to the appropriate user rules file."""
        rules_dir = get_rules_dir()
        rules_dir.mkdir(parents=True, exist_ok=True)
        
        rule_file = rules_dir / f"{agent}.md"
        
        timestamp = datetime.now().strftime("%Y-%m-%d")
        entry = f"- {rule}  <!-- {timestamp} -->\n"
        
        if rule_file.exists():
            current = rule_file.read_text(encoding="utf-8")
            # Don't add duplicates
            if rule in current:
                return
            rule_file.write_text(current + entry, encoding="utf-8")
        else:
            header = f"# User Rules for {agent.title()} Agent\n\n"
            rule_file.write_text(header + entry, encoding="utf-8")

    # =========================================================================
    # SKILL DISTILLATION — THE CENTRAL LEARNING MECHANISM
    # =========================================================================

    def distill_skills(self) -> int:
        """
        Distill skills from accumulated memory and observations.
        
        This is the CENTRAL MECHANISM of the learning system:
        - Observe patterns across memory entries
        - Extract general principles from specific instances
        - Write/update skills that make many memory entries obsolete
        - A good skill replaces 10 memory entries
        
        Skills are the "trained weights" of the attention system.
        They direct focus before processing begins.
        
        Returns number of skill updates made.
        """
        store = get_memory_store()
        current_memory = store.to_prompt_context()
        current_skills = self._load_current_user_skills()
        current_rules = self._load_current_user_rules()
        meta_memory = self._load_meta_memory()
        
        if not current_memory:
            return 0
        
        prompt = f"""You are the Pattern Agent — the learning engine of outheis.

Your task: DISTILL SKILLS from observations.

## The Attention Hierarchy

Skills > Memory > Rules

- **Skills** (highest density): Condensed principles that direct attention.
  A good skill makes 10 memory entries obsolete.
  Skills are HOW to think about something.
  
- **Memory** (medium density): Facts and observations.
  Raw material for skill distillation.
  
- **Rules** (lowest density): Hard constraints and boundaries.
  Rules are what NOT to do.

## Current State

### Memory (raw observations):
{current_memory}

### Current Skills:
{current_skills if current_skills else "(none yet)"}

### Current Rules:
{current_rules if current_rules else "(none)"}

### Your Learning History:
{meta_memory if meta_memory else "(none yet)"}

## Your Task

Look for patterns that can be DISTILLED into skills:

1. **Repeated corrections** → Extract the principle behind them
2. **Consistent preferences** → Make them attention-directing
3. **Domain knowledge** → Condense into actionable guidance
4. **What works** → Capture the pattern, not the instance

Example distillation:
- Memory: "User corrected date format 3x"
- Memory: "User prefers ISO dates"  
- Memory: "User said dates should be YYYY-MM-DD"
→ Skill: "Dates: Always ISO format (YYYY-MM-DD)"
→ Delete 3 memory entries, add 1 skill line

## Response Format

Respond with JSON:
{{
  "skill_updates": [
    {{
      "agent": "common|relay|data|agenda|action",
      "action": "add|update|merge",
      "content": "The skill principle (one clear line)",
      "reasoning": "Why this distillation",
      "obsoletes_memory": ["list of memory entries this replaces"]
    }}
  ],
  "no_distillation_reason": "If nothing to distill, explain why"
}}

Be SELECTIVE. Only distill when:
- Pattern is clear (3+ instances)
- Principle is generalizable
- Skill would direct future attention

If nothing is ready to distill: {{"skill_updates": [], "no_distillation_reason": "..."}}"""

        try:
            from outheis.core.llm import call_llm
            
            response = call_llm(
                model=self.model_alias,
                agent=self.name,
                system=self.get_system_prompt(),
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1500,
            )
            
            response_text = response.content[0].text.strip()
            
            if not response_text:
                return 0
            
            # Handle markdown code blocks
            if response_text.startswith("```"):
                lines = response_text.split("\n")
                response_text = "\n".join(lines[1:-1]).strip()
            if response_text.startswith("json"):
                response_text = response_text[4:].strip()
            
            data = json.loads(response_text)
            skill_updates = data.get("skill_updates", [])
            
            if not skill_updates:
                return 0
            
            count = 0
            for update in skill_updates:
                agent = update.get("agent", "common")
                action = update.get("action", "add")
                content = update.get("content", "")
                
                if not content:
                    continue
                
                if action in ["add", "update", "merge"]:
                    self._update_user_skill(agent, content)
                    count += 1
                    
                    # Mark this distillation in meta-memory
                    reasoning = update.get("reasoning", "")
                    if reasoning:
                        self._append_meta_insight(
                            f"Distilled skill for {agent}: {content[:50]}... | {reasoning}"
                        )
            
            return count
            
        except json.JSONDecodeError:
            pass
        except Exception as e:
            print(f"Pattern agent skill distillation error: {e}")
        
        return 0

    def _load_current_user_skills(self) -> str:
        """Load all current user skills as text."""
        skills_dir = get_skills_dir()
        if not skills_dir.exists():
            return ""
        
        parts = []
        for skill_file in skills_dir.glob("*.md"):
            content = skill_file.read_text(encoding="utf-8").strip()
            if content:
                parts.append(f"## {skill_file.stem}\n{content}")
        
        return "\n\n".join(parts)

    def _update_user_skill(self, agent: str, skill_content: str) -> None:
        """
        Add or update a skill in the user skills directory.
        
        Skills are stored as markdown files, one per agent.
        Each skill is a single principle/guideline.
        """
        skills_dir = get_skills_dir()
        skills_dir.mkdir(parents=True, exist_ok=True)
        
        skill_file = skills_dir / f"{agent}.md"
        timestamp = datetime.now().strftime("%Y-%m-%d")
        
        # Format as a skill entry
        entry = f"- {skill_content}  <!-- distilled {timestamp} -->\n"
        
        if skill_file.exists():
            current = skill_file.read_text(encoding="utf-8")
            
            # Don't add duplicates (check for similar content)
            if skill_content.lower() in current.lower():
                return
            
            # Check if this updates an existing skill
            # (simplified: just append, user can consolidate)
            skill_file.write_text(current + entry, encoding="utf-8")
        else:
            header = f"# User Skills for {agent.title()} Agent\n\n"
            header += "<!-- Distilled by Pattern Agent. These direct attention. -->\n\n"
            skill_file.write_text(header + entry, encoding="utf-8")

    def validate_strategies(self) -> None:
        """
        Review own extraction strategies and update if needed.
        
        This is how Pattern agent learns how to learn.
        """
        meta_memory = self._load_meta_memory()
        store = get_memory_store()
        current_memory = store.to_prompt_context()
        
        prompt = f"""Reflect on your extraction strategies.

YOUR CURRENT STRATEGIES/LEARNINGS:
{meta_memory if meta_memory else "(none yet)"}

CURRENT USER MEMORY STATE:
{current_memory if current_memory else "(empty)"}

Consider:
- What extraction approaches have worked well?
- What have you learned about this user's communication style?
- What should you pay more attention to?
- What should you ignore?

If you have insights worth recording, respond with:
{{
  "insight": "Your learning or strategy refinement",
  "should_record": true
}}

If nothing new:
{{
  "insight": "",
  "should_record": false
}}"""

        try:
            from outheis.core.llm import call_llm
            
            response = call_llm(
                model=self.model_alias,
                agent=self.name,
                system=self.get_system_prompt(),
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500,
            )
            
            response_text = response.content[0].text.strip()
            
            if not response_text:
                # Empty response, nothing to do
                return
            
            # Handle markdown code blocks
            if response_text.startswith("```"):
                lines = response_text.split("\n")
                # Remove first and last line (``` markers)
                response_text = "\n".join(lines[1:-1]).strip()
            
            # Handle ```json specifically
            if response_text.startswith("json"):
                response_text = response_text[4:].strip()
            
            if not response_text or response_text == "{}":
                return
            
            data = json.loads(response_text)
            
            if data.get("should_record") and data.get("insight"):
                self._append_meta_insight(data["insight"])
                print(f"[Pattern] Recorded strategy insight")
            
        except json.JSONDecodeError as e:
            # LLM didn't return valid JSON - not critical, skip silently
            pass
        except Exception as e:
            print(f"Pattern agent strategy validation error: {e}")

    def run_scheduled(self) -> None:
        """
        Run scheduled reflection.

        Called at configured time (default 04:00).
        
        The scheduled run follows the Attention Hierarchy:
        1. Extract → Memory (raw observations)
        2. Consolidate → Memory (clean up)
        3. Distill → Skills (condense patterns into principles)
        4. Promote → Rules (stable constraints)
        5. Validate → Meta-learning (learn how to learn)
        """
        timestamp = datetime.now().isoformat()
        print(f"[{timestamp}] Pattern agent: starting scheduled run")
        
        # 0. Process seed files (migration)
        seed_staged = self.process_seed_files()
        if seed_staged > 0:
            print(f"[{timestamp}] Pattern agent: staged {seed_staged} seed entries for approval")
        
        # 0b. Apply approved seed entries
        seed_applied = self.apply_approved_seeds()
        if seed_applied > 0:
            print(f"[{timestamp}] Pattern agent: applied {seed_applied} approved seed entries")
        
        # 1. Extract from recent conversations
        memory_count = self.analyze_recent_conversations(hours=24)
        print(f"[{timestamp}] Pattern agent: extracted {memory_count} new memories")
        
        # 2. Consolidate memory (merge duplicates, resolve contradictions)
        consolidated = self.consolidate_memory()
        if consolidated > 0:
            print(f"[{timestamp}] Pattern agent: consolidated {consolidated} memory entries")
        
        # 3. Distill skills (THE CENTRAL MECHANISM)
        # This is where many small observations become few powerful principles
        skills_count = self.distill_skills()
        if skills_count > 0:
            print(f"[{timestamp}] Pattern agent: distilled {skills_count} skill updates")
        
        # 4. Consider promoting to User Rules (stable constraints only)
        rules_count = self.consider_user_rules()
        if rules_count > 0:
            print(f"[{timestamp}] Pattern agent: created {rules_count} new user rules")
        
        # 5. Validate own strategies (learn how to learn)
        self.validate_strategies()
        
        # 6. Notify about pending seeds (if Agenda enabled)
        self.notify_pending_seeds()
        
        print(f"[{timestamp}] Pattern agent: scheduled run complete")

    def consolidate_memory(self) -> int:
        """
        Review memory for duplicates, contradictions, and outdated entries.
        
        Uses LLM judgment to decide what to merge, update, or remove.
        Returns number of entries changed.
        """
        store = get_memory_store()
        all_memory = store.get_all(include_expired=True)
        
        # Build a summary of all entries with indices for reference
        entries_by_type: dict[str, list[tuple[int, dict]]] = {}
        for memory_type in ["user", "feedback", "context"]:
            entries = all_memory.get(memory_type, [])
            entries_by_type[memory_type] = [
                (i, {"content": e.content, "created_at": e.created_at.isoformat(), "confidence": e.confidence})
                for i, e in enumerate(entries)
            ]
        
        if not any(entries_by_type.values()):
            return 0
        
        prompt = f"""Review this memory for consolidation. Look for:
- Duplicates (same information stated differently)
- Contradictions (conflicting facts)
- Superseded entries (newer info makes older obsolete)
- Expired or no longer relevant context

CURRENT MEMORY:
{json.dumps(entries_by_type, indent=2, default=str)}

For each action needed, respond with:
{{
  "actions": [
    {{"type": "remove", "memory_type": "context", "index": 0, "reason": "Duplicate of index 1"}},
    {{"type": "remove", "memory_type": "user", "index": 2, "reason": "Contradicted by newer entry"}}
  ],
  "reasoning": "Brief explanation of what you consolidated"
}}

If nothing needs consolidation:
{{
  "actions": [],
  "reasoning": "Memory is clean"
}}

Be conservative - only remove entries when clearly redundant or wrong."""

        try:
            from outheis.core.llm import call_llm
            
            response = call_llm(
                model=self.model_alias,
                agent=self.name,
                system=self.get_system_prompt(),
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1000,
            )
            
            response_text = response.content[0].text.strip()
            
            if not response_text:
                return 0
            
            if response_text.startswith("```"):
                lines = response_text.split("\n")
                response_text = "\n".join(lines[1:-1]).strip()
            if response_text.startswith("json"):
                response_text = response_text[4:].strip()
            
            data = json.loads(response_text)
            actions = data.get("actions", [])
            
            if not actions:
                return 0
            
            # Process removals in reverse order to maintain indices
            # Group by type and sort by index descending
            removals: dict[str, list[int]] = {}
            for action in actions:
                if action.get("type") == "remove":
                    mt = action.get("memory_type")
                    idx = action.get("index")
                    if mt and idx is not None:
                        if mt not in removals:
                            removals[mt] = []
                        removals[mt].append(idx)
            
            count = 0
            for memory_type, indices in removals.items():
                # Sort descending so we remove from end first
                for idx in sorted(indices, reverse=True):
                    if store.remove(memory_type, idx):
                        count += 1
            
            return count
            
        except json.JSONDecodeError:
            pass
        except Exception as e:
            print(f"Pattern agent consolidation error: {e}")
        
        return 0

    # =========================================================================
    # SEED PROCESSING
    # =========================================================================

    def process_seed_files(self) -> int:
        """
        Process seed files for migration.
        
        Reads all .json files in seed/ (ignoring x-* prefixed ones),
        compares with existing memory, and stages new/conflicting
        entries in seed.json for approval.
        
        Returns number of entries staged.
        """
        seed_dir = get_seed_dir()
        staging_path = get_seed_staging_path()
        
        # Find unprocessed seed files
        seed_files = [
            f for f in seed_dir.glob("*.json")
            if not f.name.startswith("x-")
        ]
        
        if not seed_files:
            return 0
        
        # Load existing memory for comparison
        store = get_memory_store()
        existing_memory = store.get_all()
        existing_contents = set()
        for entries in existing_memory.values():
            for entry in entries:
                existing_contents.add(entry.content.lower().strip())
        
        # Load current staging
        staging = {"pending": []}
        if staging_path.exists():
            try:
                staging = json.loads(staging_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                staging = {"pending": []}
        
        # Track already staged content
        staged_contents = {
            e.get("content", "").lower().strip()
            for e in staging.get("pending", [])
        }
        
        count = 0
        
        for seed_file in seed_files:
            try:
                data = json.loads(seed_file.read_text(encoding="utf-8"))
                entries = data.get("entries", [])
                
                for entry in entries:
                    content = entry.get("content", "")
                    content_lower = content.lower().strip()
                    
                    # Skip if already in memory or already staged
                    if content_lower in existing_contents:
                        continue
                    if content_lower in staged_contents:
                        continue
                    
                    # Determine target type
                    target = entry.get("type") or self._infer_memory_type(content)
                    
                    # Check for conflicts
                    conflict = self._find_conflict(content, existing_memory)
                    
                    staging["pending"].append({
                        "content": content,
                        "source": f"seed/{seed_file.name}",
                        "status": None,
                        "conflicts_with": conflict,
                        "target": target,
                    })
                    staged_contents.add(content_lower)
                    count += 1
                
                # Rename to mark as processed
                processed_name = f"x-{seed_file.name}"
                seed_file.rename(seed_dir / processed_name)
                
            except json.JSONDecodeError as e:
                print(f"[Pattern] Invalid JSON in seed file {seed_file.name}: {e}")
            except Exception as e:
                print(f"[Pattern] Error processing seed file {seed_file.name}: {e}")
        
        # Save staging
        if count > 0:
            staging_path.write_text(
                json.dumps(staging, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        
        return count

    def _infer_memory_type(self, content: str) -> str:
        """Infer memory type from content."""
        content_lower = content.lower()
        
        # Feedback indicators
        feedback_words = [
            "prefers", "preference", "prefer", "always", "never", "better", "rather"
        ]
        if any(w in content_lower for w in feedback_words):
            return "feedback"
        
        # Context indicators (temporary)
        context_words = [
            "current", "currently", "working on", "this week", "today"
        ]
        if any(w in content_lower for w in context_words):
            return "context"
        
        # Default to user facts
        return "user"

    def _find_conflict(self, content: str, existing_memory: dict) -> str | None:
        """
        Check if content conflicts with existing memory.
        
        Returns the conflicting content if found, None otherwise.
        """
        # Simple heuristic: check for overlapping subjects
        # Could be enhanced with LLM for better semantic matching
        content_words = set(content.lower().split())
        
        for entries in existing_memory.values():
            for entry in entries:
                existing_words = set(entry.content.lower().split())
                overlap = content_words & existing_words
                
                # If significant overlap but different content, might conflict
                if len(overlap) >= 3:
                    # Check if it's not just similar but contradictory
                    # Simple heuristic: if both mention same subject
                    # but aren't identical, flag as potential conflict
                    if entry.content.lower().strip() != content.lower().strip():
                        return entry.content
        
        return None

    def apply_approved_seeds(self) -> int:
        """
        Apply approved seed entries to memory.
        
        Reads seed.json, applies entries with status="approved",
        removes entries with status="approved" or "rejected",
        keeps entries with status=null.
        
        Returns number of entries applied.
        """
        staging_path = get_seed_staging_path()
        
        if not staging_path.exists():
            return 0
        
        try:
            staging = json.loads(staging_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return 0
        
        pending = staging.get("pending", [])
        if not pending:
            return 0
        
        store = get_memory_store()
        applied = 0
        remaining = []
        
        for entry in pending:
            status = entry.get("status")
            
            if status == "approved":
                # Apply to memory
                content = entry.get("content", "")
                target = entry.get("target", "user")
                
                if content and target in ["user", "feedback", "context"]:
                    store.add(
                        content,
                        target,
                        confidence=0.9,
                        source=entry.get("source", "seed"),
                    )
                    applied += 1
                # Don't add to remaining (remove from staging)
                
            elif status == "rejected":
                # Just remove from staging, don't apply
                pass
                
            else:
                # status is None (undecided) - keep in staging
                remaining.append(entry)
        
        # Update staging file
        if remaining:
            staging["pending"] = remaining
            staging_path.write_text(
                json.dumps(staging, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        else:
            # All processed, remove staging file
            staging_path.unlink(missing_ok=True)
        
        return applied

    def notify_pending_seeds(self) -> None:
        """
        Notify user about pending seed entries via Exchange.md.
        
        Only called if Agenda agent is enabled.
        """
        staging_path = get_seed_staging_path()
        
        if not staging_path.exists():
            return
        
        try:
            staging = json.loads(staging_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return
        
        pending = [
            e for e in staging.get("pending", [])
            if e.get("status") is None
        ]
        
        if not pending:
            return
        
        # Check if Agenda agent is enabled
        config = load_config()
        agenda_config = config.agents.get("agenda")
        if not agenda_config or not agenda_config.enabled:
            return
        
        # Add notification to Exchange.md
        primary_vault = config.human.primary_vault()
        exchange_path = primary_vault / "Agenda" / "Exchange.md"
        
        if not exchange_path.exists():
            return
        
        timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:00")

        # Build notification
        lines = [
            "\n---\n",
            f"## {timestamp} – Pending Seed Entries\n",
            f"There are {len(pending)} seed entries awaiting approval.",
            "Edit `~/.outheis/human/memory/seed.json` to approve/reject:",
            "- Set `\"status\": \"approved\"` to add to memory",
            "- Set `\"status\": \"rejected\"` to discard",
            "",
        ]

        # Show first few entries
        for entry in pending[:3]:
            content = entry.get("content", "")[:80]
            if len(entry.get("content", "")) > 80:
                content += "..."
            lines.append(f"- {content}")

        if len(pending) > 3:
            lines.append(f"- ... and {len(pending) - 3} more")

        lines.append("")

        notification = "\n".join(lines)

        # Append to Exchange.md
        current = exchange_path.read_text(encoding="utf-8")
        if "Pending Seed Entries" not in current:  # Don't duplicate
            exchange_path.write_text(current + notification, encoding="utf-8")

    # =========================================================================
    # MEMORY MIGRATION
    # =========================================================================

    def run_migration(self) -> str:
        """Run memory migration from vault/Migration/.

        Phase A — process accept/reject decisions in Exchange.md, then clear it.
        Phase B — single LLM call: all source files + all existing knowledge → proposals.
        Phase C — write proposals to Exchange.md; x-prefix all source files.
        """
        import re
        from outheis.core.config import load_config
        from outheis.core.memory import get_memory_store

        config = load_config()
        vault = config.human.primary_vault()
        migration_dir = vault / "Migration"

        if not migration_dir.exists():
            return "No migration/ directory found in vault. Nothing to do."

        exchange_path = migration_dir / "Exchange.md"
        store = get_memory_store()

        adopted_items: list[str] = []
        rejected_count = 0
        still_pending: list[tuple[str, str]] = []
        new_proposals: list[tuple[str, str]] = []
        llm_error: str | None = None

        # ── Phase A: process confirmed items from Exchange.md ────────────────
        # Write to memory first, then clear Exchange.md (crash-safe order).
        if exchange_path.exists():
            exchange_text = exchange_path.read_text(encoding="utf-8")
            cb_re = re.compile(r'^-\s*\[([ xX])\]', re.IGNORECASE)
            type_re = re.compile(r'^(.+?)\s*\[(\w+(?::\w+)?)\]\s*$')
            pending_items: list[tuple[str, str, bool, bool]] = []

            if '---' in exchange_text:
                in_item = False
                item_text = item_type = ''
                accept = reject = False
                cb_count = 0
                for line in exchange_text.splitlines():
                    t = line.strip()
                    if t == '---':
                        if in_item and item_text:
                            pending_items.append((item_text, item_type, accept, reject))
                        in_item = True
                        item_text = item_type = ''
                        accept = reject = False
                        cb_count = 0
                        continue
                    cb_m = cb_re.match(t)
                    if cb_m:
                        if cb_count == 0:
                            accept = cb_m.group(1).lower() == 'x'
                        else:
                            reject = cb_m.group(1).lower() == 'x'
                        cb_count += 1
                    elif t and not item_text:
                        type_m = type_re.match(t)
                        if type_m:
                            item_text, item_type = type_m.group(1).strip(), type_m.group(2).strip()
                if in_item and item_text:
                    pending_items.append((item_text, item_type, accept, reject))
            else:
                # Old format fallback: - [x/ ] content [type]
                for line in exchange_text.splitlines():
                    t = line.strip()
                    cb_m = cb_re.match(t)
                    if not cb_m:
                        continue
                    checked = cb_m.group(1).lower() == 'x'
                    rest = t[cb_m.end():].strip()
                    type_m = type_re.match(rest)
                    if type_m:
                        txt, typ = type_m.group(1).strip(), type_m.group(2).strip()
                    else:
                        txt, typ = rest, 'user'
                    pending_items.append((txt, typ, checked, not checked))

            for item_text, item_type, accept, reject in pending_items:
                adopted = accept and not reject
                rejected_item = reject and not accept
                if adopted:
                    if item_type.startswith("rule:"):
                        self._append_user_rule(item_type.split(":")[1], item_text)
                    else:
                        store.add(item_text, item_type)
                    adopted_items.append(item_text)
                elif rejected_item:
                    rejected_count += 1
                else:
                    still_pending.append((item_text, item_type))

            exchange_path.write_text("", encoding="utf-8")
            print(
                f"[memory_migrate] Phase A: {len(adopted_items)} adopted, "
                f"{rejected_count} rejected, {len(still_pending)} still pending."
            )

        # ── Phase B: single LLM call across all source files ─────────────────
        source_files = [
            f for f in sorted(migration_dir.iterdir())
            if not f.name.startswith("x-")
            and f.suffix.lower() in [".json", ".md"]
            and f.name not in ("Migration.md", "Exchange.md")
        ]
        print(f"[memory_migrate] Phase B: {len(source_files)} source file(s) found.")

        if source_files:
            sources: dict[str, str] = {}
            for f in source_files:
                try:
                    sources[f.name] = f.read_text(encoding="utf-8")
                except Exception as e:
                    print(f"[memory_migrate] Could not read {f.name}: {e}")

            if sources:
                print(f"[memory_migrate] Calling LLM to extract proposals from {len(sources)} file(s)...")
                try:
                    new_proposals = self._propose_from_sources(sources, store)
                    print(f"[memory_migrate] LLM returned {len(new_proposals)} proposal(s).")
                except Exception as e:
                    llm_error = str(e)
                    print(f"[memory_migrate] LLM call failed: {e}")
                    # Do NOT return early — Phase C must still x-prefix source files
                    # and preserve still_pending items so they are not lost.

        # ── Phase C: write proposals to Exchange.md; x-prefix source files ───
        all_proposals = still_pending + new_proposals
        try:
            if all_proposals:
                self._write_proposals(exchange_path, all_proposals)
                print(f"[memory_migrate] {len(all_proposals)} proposals written to Exchange.md.")
            else:
                print("[memory_migrate] No proposals to write.")
        except Exception as e:
            print(f"[memory_migrate] Could not write Exchange.md: {e}")

        for f in source_files:
            try:
                f.rename(f.parent / f"x-{f.name}")
                print(f"[memory_migrate] x-prefixed: {f.name}")
            except Exception as e:
                print(f"[memory_migrate] Could not rename {f.name}: {e}")

        # ── Summary ───────────────────────────────────────────────────────────
        parts = []
        if llm_error:
            parts.append(f"Warning: LLM call failed ({llm_error}). Source files x-prefixed; still-pending items preserved.")
        if adopted_items:
            parts.append(f"{len(adopted_items)} item(s) adopted into memory.")
        if rejected_count:
            parts.append(f"{rejected_count} rejected.")
        if source_files:
            parts.append(f"{len(source_files)} source file(s) processed and x-prefixed.")
        if all_proposals:
            parts.append(
                f"{len(all_proposals)} proposal(s) in Exchange.md — "
                "review, mark Accept/Reject, then Run now."
            )
        elif not adopted_items and not source_files:
            parts.append("Nothing to process.")
        return "\n".join(parts) if parts else "Done."

    def _propose_from_sources(
        self,
        sources: dict,  # filename → raw text
        store,
    ) -> list[tuple[str, str]]:
        """Single LLM call: read all source files + existing knowledge, return proposals.

        READ-ONLY with respect to existing memory/skills/rules. This method MUST NOT
        call store.add(), _append_user_rule(), or write to any skills/rules file.
        Existing entries are used only as deduplication context for the LLM prompt.
        Modifications to existing entries happen exclusively in Phase A (adoption),
        after the user has explicitly accepted a proposal in Exchange.md.
        """
        import json
        from outheis.core.llm import call_llm

        # Collect existing entries as exact-match reference only.
        # Used exclusively to skip word-for-word duplicates — NOT to filter
        # "similar" or "already covered" items (that decision belongs to the user).
        existing_lines: list[str] = []
        all_entries = store.get_all()
        for mt, entries in all_entries.items():
            mt_str = mt.value if hasattr(mt, 'value') else str(mt)
            for e in entries:
                existing_lines.append(e.content)

        rules_text = self._load_current_user_rules()
        skills_dir = get_skills_dir()
        skills_parts: list[str] = []
        if skills_dir.exists():
            for sf in skills_dir.glob("*.md"):
                c = sf.read_text(encoding="utf-8").strip()
                if c:
                    skills_parts.append(c)

        existing_text = "\n".join(existing_lines[:800])
        existing_rules = "\n".join(skills_parts)[:4000]
        if rules_text:
            existing_rules = rules_text[:2000] + "\n" + existing_rules

        # Build migration file sections
        source_sections = [f"### {name}\n{content}" for name, content in sources.items()]
        sources_text = "\n\n".join(source_sections)

        prompt = (
            "You are a precision fact-extraction engine for a personal memory system. "
            "Your output will be reviewed by the user before anything is stored.\n\n"

            "TASK: Extract every discrete fact from the migration files below as a "
            "self-contained item.\n\n"

            "EXTRACTION RULES:\n"
            "1. Copy facts verbatim or near-verbatim. Preserve every name, number, date, "
            "time, threshold, file path, URL, and rule exactly as written. "
            "Do not paraphrase, compress, or restate in your own words.\n"
            "2. GROUP facts that form a single coherent unit (e.g. a full weekly schedule, "
            "a file-structure rule set, a person's complete role description). "
            "SPLIT facts that are genuinely independent of each other.\n"
            "3. Each item must be fully self-contained — readable without the source file. "
            "Add the subject name if the source uses a pronoun or implicit reference.\n"
            "4. Do not add interpretation, context, or editorial framing beyond the source.\n\n"

            "DEDUPLICATION — this is the hardest part, read carefully:\n"
            "A source fact is redundant ONLY IF an existing entry already contains "
            "THE SAME SPECIFIC INFORMATION — same numbers, names, rules, paths, and details.\n\n"
            "A GENERAL existing entry does NOT cover its specific instances. Examples:\n"
            "  - Existing: 'Alice works at Acme Corp' — does NOT cover: employee count, "
            "revenue, management names, Alice's exact role and hours, equity structure.\n"
            "  - Existing: 'Bob runs Smith Plumbing' — does NOT cover: 3rd generation, "
            "20 years experience, fixed costs, current profitability, why it cannot be given up.\n"
            "  - Existing: 'Shadow.md holds background items' — does NOT cover: the CRITICAL "
            "rule that Shadow items must NEVER appear in Agenda.md, not even in hints.\n"
            "  - Existing: 'Vault uses Archive directory' — does NOT cover: exact path, cleanup "
            "obligation, which files may remain, storage limit.\n\n"
            "Ask yourself for each fact: 'Does an existing entry already state THESE SPECIFIC "
            "details — not just this general topic?' If the answer is no or uncertain: include it.\n"
            "When in doubt: include. The user decides what to keep.\n\n"

            "TYPES:\n"
            "  user — personal facts, schedule, preferences, life context, family\n"
            "  skill — procedural knowledge, how-to, workflow\n"
            "  rule:relay / rule:data / rule:agenda / rule:pattern — agent-specific rules\n"
            "  project — ongoing project info\n"
            "  reference — pointer to a file, resource, or external system\n\n"
        )
        if existing_text or existing_rules:
            prompt += (
                "EXISTING ENTRIES (use only for deduplication as described above):\n"
                f"{existing_text}\n"
                f"{existing_rules}\n\n"
            )
        prompt += (
            f"MIGRATION FILES:\n{sources_text}\n\n"
            "Respond ONLY with a JSON array:\n"
            '[{"content": "...", "type": "user"}, ...]\n'
            "If the files contain nothing extractable, respond with []."
        )

        response = call_llm(
            model=self.model_alias,
            timeout=300.0,
            agent=self.name,
            system=self.get_system_prompt(),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=8192,
        )

        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()

        result: list[tuple[str, str]] = []
        for item in json.loads(text):
            if isinstance(item, dict):
                c = item.get("content", "").strip()
                t = item.get("type", "user").strip()
                if c:
                    result.append((c, t))
        return result

    def _write_proposals(
        self,
        exchange_path,
        proposals: list[tuple[str, str]],
    ) -> None:
        """Write migration proposals to Exchange.md in --- separated format."""
        from pathlib import Path as _Path

        exchange_path = _Path(exchange_path)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")

        header = (
            f"## Migration Proposals — {ts}\n\n"
            "*Accept ✓ / Reject ✗ — then Run now*\n\n"
        )
        items = [
            f"*extracted: {ts}*\n{content} [{entry_type}]\n- [ ] Accept\n- [ ] Reject"
            for content, entry_type in proposals
        ]
        body = "---\n" + "\n---\n".join(items) + "\n---\n"
        section = header + body

        existing = exchange_path.read_text(encoding="utf-8").strip() if exchange_path.exists() else ""
        if existing:
            exchange_path.write_text(existing + "\n\n" + section, encoding="utf-8")
        else:
            exchange_path.parent.mkdir(parents=True, exist_ok=True)
            file_header = (
                "# Migration Exchange\n\n"
                "*Proposals from Migration/ files for adoption into the memory system.*\n\n"
            )
            exchange_path.write_text(file_header + section, encoding="utf-8")

    def _scan_file_tags(self, path) -> list[str]:
        """Extract all #tag-name tokens from a file (live scan, not cached)."""
        import re
        try:
            text = path.read_text(encoding="utf-8")
            return sorted(set(re.findall(r'#([a-z][a-z0-9-]+)', text)))
        except Exception:
            return []

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

        if isinstance(data, dict) and "entries" in data:
            items = data["entries"]
        elif isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = []
            for key, value in data.items():
                if isinstance(value, str):
                    items.append({"content": f"{key}: {value}", "type": "user"})
                elif isinstance(value, dict):
                    items.append(value)
                elif isinstance(value, list):
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



# =============================================================================
# FACTORY
# =============================================================================

def create_pattern_agent(model_alias: str = "capable") -> PatternAgent:
    """Create a pattern agent instance."""
    return PatternAgent(model_alias=model_alias)
