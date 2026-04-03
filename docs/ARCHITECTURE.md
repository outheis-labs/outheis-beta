# outheis Architecture

## Core Principle: Microkernel Design

outheis follows microkernel principles from operating system design:
- **Minimal kernel**: Only coordination and message passing
- **Autonomous components**: Agents are independent processes
- **Clean interfaces**: Communication via messages, not shared state
- **Privilege separation**: Each agent has its domain, respects boundaries

## The Agents

```
┌─────────────────────────────────────────────────────────────┐
│                         Relay (ou)                          │
│              Coordination, delegation, routing              │
└─────────────────────┬───────────────────────────────────────┘
                      │ messages
        ┌─────────────┼─────────────┬─────────────┐
        ▼             ▼             ▼             ▼
   ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐
   │  Data   │   │ Agenda  │   │ Action  │   │ Pattern │
   │ (zeno)  │   │ (cato)  │   │ (hiro)  │   │ (rumi)  │
   │         │   │         │   │         │   │         │
   │ Vault   │   │Schedule │   │  Tasks  │   │Learning │
   │ access  │   │ time    │   │  exec   │   │ memory  │
   └─────────┘   └─────────┘   └─────────┘   └─────────┘
```

### Relay (ou)
The coordinator. Routes messages, delegates to specialists, synthesizes responses.
Never does domain work directly.

### Data (zeno)
Vault operations. Reads, writes, indexes, searches.
Gets relevant context at startup, works autonomously within it.

### Agenda (cato)
Schedule and time management. Daily.md, Inbox.md, Exchange.md.
Gets agenda files at startup, decides structure and formatting.

### Action (hiro)
Task execution. Schedules background jobs, runs commands.
Can read outheis source code to explain behavior.

### Pattern (rumi)
**The learning engine.** Extracts memory, distills skills, promotes rules.
This is the central mechanism that makes the system learn.

---

## The Attention Hierarchy

This is the core learning architecture:

```
        ┌─────────────────────────┐
        │        SKILLS           │ ← highest density
        │  condensed principles   │   direct attention
        │  "how to think"         │   before processing
        └───────────┬─────────────┘
                    │ distillation (↑)
        ┌───────────┴─────────────┐
        │        MEMORY           │ ← medium density
        │  facts, observations    │   raw material
        │  "what was observed"    │   for distillation
        └───────────┬─────────────┘
                    │ hardening (rare)
        ┌───────────┴─────────────┐
        │        RULES            │ ← lowest density
        │  constraints, limits    │   hard boundaries
        │  "what never to do"     │   rarely change
        └─────────────────────────┘
```

### Skills (highest priority)
- **Function**: Direct attention before processing begins
- **Content**: Condensed principles, not procedures
- **Example**: "Dates: Always ISO format (YYYY-MM-DD)"
- **Location**: `~/.outheis/human/skills/*.md`
- **Effect**: One good skill makes 10 memory entries obsolete

### Memory (processing material)
- **Function**: Store observations for later distillation
- **Content**: Facts (user), behaviors (feedback), temporary (context)
- **Example**: "User corrected date format on 2026-03-15"
- **Location**: `~/.outheis/human/memory/*.json`
- **Effect**: Raw material, consumed by distillation

### Rules (hard constraints)
- **Function**: Define boundaries that must not be crossed
- **Content**: Prohibitions, invariants, non-negotiables
- **Example**: "Never delete files without confirmation"
- **Location**: `~/.outheis/human/rules/*.md`
- **Effect**: Override everything else, rarely added

---

## The Distillation Process

Pattern Agent runs the distillation cycle:

```
Observe → Extract → Consolidate → Distill → Prune
   │         │           │           │         │
   │         │           │           │         └─ Remove obsolete memory
   │         │           │           └─ Create/update skills
   │         │           └─ Merge duplicates, resolve conflicts
   │         └─ Write to memory (user/feedback/context)
   └─ Watch conversations, corrections, feedback
```

### Distillation Triggers
- **3+ similar observations** → Pattern detected
- **Repeated corrections** → Principle extractable
- **Stable preference** → Ready for skill

### Quality Criteria
A good distilled skill:
- Directs attention (tells what to notice)
- Generalizes (applies beyond specific instance)
- Replaces (makes memory entries unnecessary)

---

## Agent Design Principles

### Context at Startup, Not Via Tools
Agents receive relevant context when invoked, not through many read-tools.
Like a process getting its memory space.

```python
# Bad: Agent makes many tool calls to gather context
read_daily()
read_inbox() 
read_exchange()
# then decide

# Good: Agent gets context, makes decisions
context = {daily, inbox, exchange}  # provided at invocation
# decide and act
```

### Minimal Tools for Output
Tools are for **actions**, not data gathering:
- `write_file(path, content)` — write output
- `append_file(path, content)` — append to file
- `search(query)` — when context is too large (scale strategy)

### Current Tool Counts

| Agent | Tools | Strategy |
|-------|-------|----------|
| Agenda (cato) | 3 | Full context at startup (3 small files) |
| Data (zeno) | 5 | Index in context, read_file for detail |
| Action (hiro) | 4 | Task registry + source index |
| Pattern (rumi) | - | Background, no tool-use loop |
| Relay (ou) | - | Coordinates, delegates to specialists |

### load_skill for Scale
When context would be too large, use demand-paging:
- Agent has index/overview in context
- Calls `load_skill(topic)` when detail needed
- Like a controlled page-fault

---

## The Scaling Problem

As data grows, agents can't have everything in context.

### Solution: Abstraction, Not More Tools

**Bad scaling**: Add more read-tools
```
read_file_1(), read_file_2(), ... read_file_n()
```

**Good scaling**: Better abstractions
```
Index + Heuristics + On-demand detail
```

### Scaling Strategies

1. **Index with Heuristics**
   - Agent sees smart index, not all files
   - Index includes: recency, access frequency, tag matches

2. **Relevance Scoring**
   - Pattern Agent learns what's typically relevant
   - Pre-filter before agent gets context

3. **Progressive Loading**
   - Overview first, detail on demand
   - `load_skill(topic)` for more depth

4. **Skill-Based Compression**
   - Skills replace detailed instructions
   - "Use ISO dates" vs 10 examples

---

## File Locations

```
~/.outheis/
├── human/                    # User-specific data
│   ├── config.json          # Configuration
│   ├── messages.jsonl       # Message queue
│   ├── memory/              # Memory store
│   │   ├── user.json       # User facts
│   │   ├── feedback.json   # Behavioral preferences
│   │   ├── context.json    # Temporary context
│   │   └── pattern/        # Pattern agent meta-memory
│   ├── skills/              # DISTILLED by Pattern Agent
│   │   ├── common.md       # All agents
│   │   ├── relay.md        # Relay-specific
│   │   └── ...
│   ├── rules/               # PROMOTED from stable patterns
│   │   ├── common.md
│   │   └── ...
│   └── cache/               # Ephemeral data
│
src/outheis/
├── agents/
│   ├── skills/              # SYSTEM skills (not user)
│   │   ├── common.md
│   │   ├── pattern.md
│   │   └── ...
│   ├── relay.py
│   ├── data.py
│   ├── agenda.py
│   ├── action.py
│   └── pattern.py
└── core/
    ├── config.py
    ├── memory.py
    ├── llm.py
    └── ...
```

---

## Key Insight: "Attention Is All You Need"

The transformer architecture's core insight — that attention mechanisms can replace complex sequential processing — applies directly to outheis. This isn't metaphor; it's the same principle at a different level.

### The Mapping

| LLM Concept | outheis Equivalent |
|-------------|-------------------|
| Trained weights | Skills (distilled principles) |
| Context window | Memory (current observations) |
| Query | User message |
| Attention scores | Relevance heuristics |
| Training loop | Pattern Agent (nightly) |

### How It Works

In a transformer:
- **Weights** are learned patterns that direct attention to relevant parts of input
- **Context** is the current input being processed
- **Query** determines what to focus on
- Training refines weights so less context is needed for good outputs

In outheis:
- **Skills** are learned principles that direct agent attention to what matters
- **Memory** is accumulated observations awaiting distillation
- **User request** determines current focus
- Pattern Agent refines skills so agents need less in their context

### The Training Loop

```
User interacts with agents
        ↓
Corrections, preferences observed
        ↓
Stored in Memory (feedback type)
        ↓
Pattern Agent runs (nightly)
        ↓
Recognizes patterns (3+ similar observations)
        ↓
Distills into Skill (condensed principle)
        ↓
Deletes redundant Memory entries
        ↓
Next agent invocation: Skill directs attention
        ↓
Agent behaves differently (learned)
```

This is gradient descent at the system level. Each correction adjusts the "weights" (skills). Over time, the system needs less explicit context because the skills direct attention efficiently.

### Why Not More Code?

The anti-pattern is solving learning with code:

**Wrong approach:**
```python
def format_date(date):
    if user_prefers_iso:      # hardcoded check
        return date.isoformat()
    elif user_prefers_german:  # another branch
        return date.strftime("%d.%m.%Y")
    # ... more branches for each preference
```

**Right approach:**
```
Skill: "Dates: Always ISO format (YYYY-MM-DD)"
```

The LLM reads the skill and applies it. No code changes needed when preferences change. The system learns by refining skills, not by adding branches.

### Scaling Through Compression

As context grows, naive approaches fail:

**Wrong:** Add more tools to fetch more data
```
read_file_1(), read_file_2(), ... read_file_n()
```

**Right:** Better compression through skills
```
One skill replaces 10 memory entries
One principle replaces 10 examples
```

This mirrors how trained weights compress training data. A model doesn't store all training examples; it learns patterns. Similarly, outheis doesn't keep all observations; it distills principles.

### The Hierarchy as Attention Layers

```
Skills (highest density)
   │  "Use ISO dates" — applies everywhere
   │  Compressed knowledge, maximum leverage
   │
Memory (medium density)
   │  "User corrected date format 3x"
   │  Raw observations, awaiting compression
   │
Rules (lowest density)
      "Never delete without confirmation"
      Hard constraints, override everything
```

Each layer has different characteristics:

| Layer | Density | Volatility | Function |
|-------|---------|------------|----------|
| Skills | High | Changes via distillation | Direct attention |
| Memory | Medium | Changes constantly | Store observations |
| Rules | Low | Rarely changes | Set boundaries |

### Pattern Agent as Optimizer

The Pattern Agent is the optimizer of this system:

1. **Observes gradients** — user corrections indicate error
2. **Accumulates updates** — memory stores observations
3. **Applies batch update** — nightly distillation
4. **Prunes redundancy** — deletes obsolete memory

Like a training loop, it runs continuously in the background, gradually improving the system's "weights" (skills) based on observed "loss" (user corrections).

### Practical Implications

1. **Don't hardcode preferences** — let skills emerge from observation
2. **Don't add tools for data** — compress data into context via skills
3. **Trust the distillation** — corrections today become skills tomorrow
4. **Measure by context size** — better skills = smaller context needed

The goal: a system that gets better not by adding code, but by refining attention. The longer it runs, the less it needs in context, because skills direct focus efficiently.

---

## OS Analogies Throughout

The microkernel principles apply at every level:

| OS Concept | outheis Equivalent | Effect |
|------------|-------------------|--------|
| Process gets memory at start | Agent gets context at invocation | No repeated fetching |
| Few syscalls (read, write) | Few tools (write_file, append) | Clean interfaces |
| Page fault on demand | load_skill(topic) | Progressive loading |
| Kernel only coordinates | Relay only delegates | Separation of concerns |
| Shared libraries | Common skills/rules | Reusable knowledge |
| Process isolation | Agent domains | Clear responsibilities |

### Why This Matters

Traditional chatbot approach:
```
User → Monolithic handler → Response
         (all logic in one place)
```

outheis approach:
```
User → Relay → Specialist Agent → Response
         │          │
         │          └── Has own context, skills, rules
         └── Only routes, never does domain work
```

This isn't just organization — it enables learning. Each agent can have specialized skills that the Pattern Agent refines independently.

---

## Design Philosophy

1. **Distillation over Accumulation**
   - Don't just collect, refine
   - Skills > Memory
   - One principle beats ten examples

2. **Principles over Procedures**
   - Skills say "what to notice"
   - Not "step 1, step 2, step 3"
   - LLM decides how to apply

3. **Autonomy within Boundaries**
   - Agents decide how to work
   - Rules set what not to do
   - No hardcoded templates

4. **Scale through Abstraction**
   - Not more tools, better index
   - Not more memory, better skills
   - Not more code, better attention

5. **Organic Learning**
   - Corrections today → skills tomorrow
   - System improves by running, not by coding
   - The goal: less context needed over time
