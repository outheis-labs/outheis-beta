# Action Agent Skills

## Principles

- Code is truth — look it up when in doubt
- Name concrete line numbers and function names
- Don't just explain — also suggest solutions

## Answering Code Questions

When asked "why can X not Y?":
1. `search_source` for relevant keywords
2. `read_source` of suspect files
3. Explain what happens in the code
4. Show where the limitation is
5. Suggest what would need to change

## Important Files

- `agents/relay.py` — main coordinator, tools, routing
- `agents/data.py` — vault operations
- `agents/agenda.py` — scheduling
- `agents/pattern.py` — learning, memory extraction
- `core/config.py` — configuration
- `core/memory.py` — memory system
- `agents/skills/*.md` — agent skills
- `agents/rules/*.md` — agent rules

## Explanation Style

Short and technical:
- "In `relay.py:245` a tool for X is missing"
- "The function `_handle_foo()` doesn't check for Y"
- "To change this: add in line Z..."
