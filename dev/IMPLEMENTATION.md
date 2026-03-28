# Implementation Status

Work-in-progress tracking. Completed items are removed.

---

## Open Tasks

### Phase 1: Data Agent — ✓ COMPLETE

- [x] Implement vault search in Data agent
- [x] Build search index (`index.jsonl`)
- [x] Relay delegates vault queries to Data

### Phase 1.5: Memory System — ✓ COMPLETE

- [x] Memory store (`core/memory.py`)
- [x] Pattern agent memory extraction
- [x] Explicit `!` marker for immediate storage
- [x] Temporal decay for context entries
- [x] Memory in agent system prompts

### Phase 1.6: Rules System — ✓ COMPLETE

- [x] System Rules in `agents/rules/*.md`
- [x] Rules loader (`agents/loader.py`)
- [x] All agents use rules loader
- [x] CLI `outheis rules` command
- [x] User Rules infrastructure (Pattern agent can write to `human/rules/`)

### Phase 2: Agenda Agent — ✓ COMPLETE

- [x] Agenda agent implementation (read Agenda files, LLM processing)
- [x] Delegation from Relay to Agenda (@cato, schedule keywords)
- [x] Date awareness in system prompt

### Phase 3: Polish & Integrations

- [ ] **Action agent (hiro)**: External integrations (email, calendar APIs)
- [ ] Agenda agent: Schedule conflict detection, write operations
- [ ] Pattern agent: Bot-chat analysis for behavioral patterns
- [ ] Pattern agent: Promote feedback to User Rules after threshold
- [ ] **Dynamic tag extraction with voting**
  - Extract candidate tags from vault content (YAKE/spaCy, local, fast)
  - Voting mechanism: tags gain weight through co-occurrence across documents
  - Prune single-instance/low-relevance tags automatically
  - Periodically re-evaluate as vault content changes
  - Result: bounded set of high-semantic-overlap tags
  - Store in `tag-weights.jsonl`, expose via Data agent
- [ ] Tag harmonization
- [ ] Signal transport
- [ ] Web UI (localhost)
  - [ ] Memory view and edit interface
  - [ ] Rules view and edit interface

---

## Architecture Decisions

### Rules System

Two-layer rule system separating architecture from preferences.

**System Rules vs. User Rules:**

| | System Rules | User Rules |
|---|--------------|------------|
| **Source** | Developers | Emergent from interaction |
| **Location** | `src/outheis/agents/rules/` | `~/.outheis/human/rules/` |
| **Purpose** | Boundaries, capabilities | Style, preferences |
| **Example** | "MAY NOT access external APIs" | "User prefers concise responses" |

**File Structure:**
```
src/outheis/agents/rules/
├── common.md         # All agents
├── relay.md          # Relay-specific
├── data.md           # Data-specific
├── agenda.md         # Agenda-specific
├── action.md         # Action-specific
└── pattern.md        # Pattern-specific

~/.outheis/human/rules/
├── common.md         # All agents (emergent)
├── relay.md          # Relay-specific (emergent)
└── ...
```

**Rule Loading:**
```python
def get_system_prompt(agent_name: str) -> str:
    rules = load_rules(agent_name)  # System + User
    memory = get_memory_context()
    return f"{rules}\n\n{memory}"
```

**User Rule Emergence:**
- Pattern agent detects repeated patterns (≥5 occurrences)
- Promotes consistent preferences to `human/rules/*.md`
- User can view/edit via `outheis rules`

### Memory System

Persistent memory about the user, separate from vault content.

**Memory vs. Vault:**
- **Memory** = Meta-level (about the user, working preferences, current context)
- **Vault** = Work content (documents, notes, projects)

**Memory Types:**

| Type | Purpose | Decay | Examples |
|------|---------|-------|----------|
| `user` | Personal facts | Permanent | "User is 35 years old", "Children: Leo, Emma" |
| `feedback` | Working preferences | Permanent | "Prefers short answers", "Respond in German" |
| `context` | Current focus | 14 days default | "Working on Project Alpha", "Preparing for trip" |

**Storage:**
```
~/.outheis/human/memory/
├── user.json
├── feedback.json
└── context.json
```

**Explicit Marker `!`:**
User can prefix messages with `!` to immediately store in memory:
- `! I am 35 years old` → user memory
- `! please give short answers` → feedback memory
- `! working on project X` → context memory (with decay)

Classification is automatic based on keywords.

**Temporal Awareness:**
- `context` entries expire after `decay_days` (default: 14)
- Temporary moods/stress are NOT stored as character traits
- Pattern agent cleans up expired entries during scheduled runs

### Coherent Identity

Although outheis consists of multiple agents, users experience a single coherent assistant.

**Maintained by:**
- Common rules shared across all agents
- Shared memory context in all prompts
- Pattern agent ensuring consistent personality evolution

**Personality emergence:**
1. User interacts naturally over time
2. Pattern agent extracts preferences to Memory
3. Repeated patterns become User Rules
4. Rules shape all agent behavior
5. Result: Stable, personalized assistant

### Dispatcher Scheduler

The dispatcher includes a built-in scheduler for periodic tasks. This is more portable than relying on external schedulers (cron, launchd, systemd timers).

**Implementation:**
- Uses `select()` with timeout — no polling loop, no external dependencies
- Wakeup pipe for signal handling
- Timeout calculated from next scheduled task

**Scheduled tasks:**
- `pattern` (04:00): Run Pattern agent reflection, extract memories
- `index_rebuild` (04:30): Rebuild vault search indices  
- `archive_rotation` (05:00): Rotate old messages to archive

**Why not external scheduler?**
- Different on every platform (cron, launchd, Task Scheduler)
- Dispatcher already runs as daemon
- `select()` timeout adds zero overhead when idle

---

## Open Questions

1. **Local LLM support?**
   - Current: Anthropic API only
   - Future: Ollama via litellm?

2. **Signal transport implementation?**
   - signal-cli or signal-cli-rest-api?
   - Polling interval?

3. **Web UI Memory/Rules Editor?**
   - Direct JSON/MD edit vs. structured form?
   - Conflict resolution if Pattern agent updates during edit?

---

## Completed

- ✓ Core modules (schema, message, queue, config)
- ✓ Dispatcher daemon with routing
- ✓ Dispatcher scheduler (select-based, no polling)
- ✓ Lock manager (socket + priority)
- ✓ Write-ahead logging
- ✓ CLI transport (init, start, stop, send, chat, status, pattern, migrate, memory, rules)
- ✓ Relay agent with LLM + memory + rules + delegation
- ✓ Data agent with vault search + rules
- ✓ Agenda agent with schedule queries + rules
- ✓ Pattern agent with memory extraction + rules
- ✓ Memory system (core/memory.py)
- ✓ Rules system (agents/loader.py, agents/rules/)
- ✓ Explicit `!` marker for memory
- ✓ Agent stubs (action)
- ✓ GitHub Actions CI
- ✓ Test fixtures (vault with Agenda/)
