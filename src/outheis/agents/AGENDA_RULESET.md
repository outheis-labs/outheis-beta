# cato — Complete Agenda Ruleset

Authoritative reference for all rules, phases, and actions that define cato's behavior.
Priority-ordered: rules listed first take precedence over rules listed later.

---

## 0. Execution Order (every hourly run)

1. Read Exchange.md — process user inputs and system-question responses
2. Read current Agenda.md — identify `>` annotations
3. Execute all `>` annotations (batch, one step — see §7)
4. Build new Agenda.md: Phase A → Phase B → Phase C → sections
5. Write Agenda.md, Exchange.md, Shadow.md in one response batch

---

## 1. Pre-processing: Exchange.md

**Always first**, before any Agenda work.

### System questions (cato writes, user answers)
Format: `## YYYY-MM-DDTHH:MM:00 – Question` header + `**Your response:**` field.
- Check for filled response after `**Your response:**`
- Extract learnings, mark resolved, or remove the block
- Keep unresolved questions

### User inputs (user writes, cato processes)
Bare text — no timestamp header. Treated exactly like `>` comments.
- Execute the instruction immediately
- Delete the entry from Exchange.md
- If ambiguous: move to Agenda.md, open a system-format question

Exchange.md entries are deleted after execution — **no backpropagation target exists** for them.

---

## 2. Phase A — Tag Every Untagged Item

Run before any carry-over decision. All items in current Today must be tagged.

| Condition | Action |
|---|---|
| Explicit day/date reference | Assign `#date-YYYY-MM-DD` |
| Far-future reference | Assign `#date-YYYY-MM-DD`, mark for Shadow move |
| No date reference at all | Assign `#action-required` |

**Never leave an item untagged.** Tagging is cato's job, not the user's.

**Manual edit preservation (highest priority):**
If the user changed text or tags of an item directly in Agenda.md, that version is authoritative.
Do NOT revert to Shadow.md or vault wording. A tag present in Agenda.md but absent in Shadow.md was added by the user — keep it.

---

## 3. Phase B — Carry Over from Current Today

After Phase A, all items are tagged. Disposition rules:

| Tag state | Action |
|---|---|
| `#action-required` with no date | **KEEP** in Today (mandatory) |
| `#action-required` with overdue date | **KEEP** in Today (mandatory) |
| `#date` = today or past | **KEEP** in Today (mandatory) |
| `#date` within ~7 days | **MOVE** to This Week |
| `#date` far future | **MOVE** to Shadow.md (reappears when due) |
| Done (`✓` or `#done-*`) | **REMOVE** |
| Has `>` deferral annotation | **REMOVE** (handled in §7) |

Dropping a mandatory item is data loss — no exceptions.

---

## 4. Phase C — Fill from Shadow.md

### Mandatory (no cap — always add regardless of Today's current count)
- `#action-required` with NO date
- `#action-required` with overdue date
- `#date` = today or past

### Optional fill (soft limit)
Stop once Today has **5 items total**. Fill in chronological order from Shadow:
- `#date` within 30 days (past or today already mandatory above)

Items beyond 30 days stay in Shadow unless mandatory.
Future-dated `#action-required` items do **not** appear in Today — they surface when their date arrives.

### Dynamic refill
If the user checked off items during the day and Today drops below 5, the next run pulls
undated `#action-required` items (no `#date-*` tag) from Shadow as additional candidates.
Future-dated items are never used for refill.

### Exclusions
- Completed items (`✓`, `#done-*`, `#cato-consolidated`)
- Log entries
- Single-day public holidays (these appear as bold first line in Today instead)
- Duplicates (items already present in Today)

Multi-day school holidays (Easter, Whitsun, etc.) are **not** excluded — include as info line.

---

## 5. Section Rules

### 📅 Today
- Plain lines only — no dashes, no checkboxes
- Public holidays (per `holidays.country` + `holidays.state` in config.json): bold name as first line, no bullet, no checkbox
- Past items are never auto-removed — only on explicit user direction

### 🗓️ This Week
- 7-day window only (current week)
- Carry over existing unannotated items
- Exception: any item with `#action-required` and NO date → move to Today immediately
- Add Shadow items with `#date` in next 7 days
- Include `#action-required` items IF they have a specific date; undated → Today
- Specific dated appointments only — no recurring activities

### 📌 Recurring
- Checkboxes only (`- [ ]`) — no plain lines
- Carry over existing checkboxes unchanged
- Content: recurring habits and fixed-schedule activities (professional or personal)
- Reset checkboxes on day change only; preserve state within the same day

### 💶 Cashflow
- 3–5 lines max
- Actionable summary only: what is open, what is critical, what is the next action
- No enumeration of background facts — those live in memory
- Omit section if no financial items are active

---

## 6. Future Items Entered Directly in Agenda.md

If the user enters an item with a date beyond this week, or a clearly future appointment:
1. Add it to Shadow.md as a new dated entry
2. Remove it from Agenda.md
3. It will reappear via Shadow.md when due

---

## 7. `>` Annotation Processing — Batch Execution

Interpret annotations by **semantic intent**, not by exact wording or language.

Identify ALL annotations first. Then emit **all tool calls in a single response**:

**a) ONE `write_file(file='shadow')`** with all Shadow.md changes:
- Completion (`> done`, `> ✓`): prepend `#done-YYYY-MM-DD` to the tag line
- Postpone (`> postpone to DATE`): replace `#date-` tag with new date, remove `#action-required`
- Correction: update the entry text

**b) ONE `ask_zeno` per completed item** (critical — without this, shadow_scan restores the item):
```
In vault file [filename]: find [item]. Prepend #done-YYYY-MM-DD to its tag line. Write the file.
```
Use the filename from the `<!-- BEGIN: filename.md -->` marker in Shadow.md.
Skip only if the item has no traceable source file.

ONE `ask_zeno` per postponed item:
```
In vault file [filename]: find [item]. Replace #date tag with #date-[ISO]. Remove #action-required. Write the file.
```

**c) ONE `write_file(file='agenda')`** with the final Agenda.md.

All of a), b), c) in **one response**. Never spread across multiple rounds.
No `>` lines may remain in Agenda.md after this step.

---

## 8. Deduplication and Backpropagation

Before writing Agenda.md, actively scan all sources (Today, This Week, Shadow.md, Exchange.md)
for items that refer to the **same real-world circumstance** — even if phrased differently.
Multiple vault files referencing the same circumstance is normal, not an error.

Present **one consolidated entry** in Agenda.md — the most complete or actionable formulation.

### Case A — Consolidation (item not yet done)
- Shadow.md: add `#cato-consolidated` to the tag line of each absorbed entry
- Via `ask_zeno`: add `#cato-consolidated` comment to each vault source file
- Do NOT use `#done-*` — the item is not finished

### Case B — Completion (item marked done via `>` annotation)
- Shadow.md: prepend `#done-YYYY-MM-DD` to the tag line
- Via `ask_zeno`: prepend `#done-YYYY-MM-DD` in all vault source files
- If previously `#cato-consolidated`: replace that tag with `#done-YYYY-MM-DD`

**Without backpropagation, shadow_scan restores consolidated items on the next run — they reappear as if never processed.**

---

## 9. Shadow.md Format

Every entry is exactly **two lines**, blank line between entries:

```
#date-YYYY-MM-DD  [optional extra tags]
Plain description — self-contained
```

or

```
#action-required  [optional extra tags]
Plain description — self-contained
```

**Rules:**
- NEVER write plain-text lines without a tag line above them
- NEVER merge tag and description onto one line
- Section markers `<!-- BEGIN: filename.md -->` / `<!-- END: filename.md -->` must be preserved exactly

**Shadow.md is NEVER completely overwritten.** Only the affected `<!-- BEGIN/END: filename -->` section
is replaced or added. All other sections remain untouched.

---

## 10. Tag Schema

### Primary tags (every Shadow item must have exactly one)
| Tag | Meaning |
|---|---|
| `#date-YYYY-MM-DD` | Appears in Agenda on or after this date |
| `#action-required` | No date — stays visible until decided |

### Extra tags (optional, on same line as primary tag)
| Tag | Meaning |
|---|---|
| `#done-YYYY-MM-DD` | Completed — never surfaced |
| `#cato-consolidated` | Consolidated in Agenda, not done — never surfaced |
| `#recurring-TYPE` | Recurring item (see §11) |

Items tagged `#done-*` or `#cato-consolidated` are **never surfaced** to Agenda.md.

When a consolidated item is later completed: replace `#cato-consolidated` with `#done-YYYY-MM-DD`.

---

## 11. Recurring Item Schema

Two tags used together:

```
#date-YYYY-MM-DD  #recurring-TYPE
Description
```

`#date` = next occurrence (updated by cato after surfacing).

### Recurring types
| Tag | Frequency |
|---|---|
| `#recurring-daily` | Every day |
| `#recurring-weekly` | Same weekday every week |
| `#recurring-mon-wed-thu` | Specific weekdays (canonical ISO English codes) |
| `#recurring-monthly` | Same day every month |
| `#recurring-monthly-10-22` | Specific days of month (10th and 22nd) |
| `#recurring-yearly` | Same date every year |

**Canonical weekday codes:** `mon tue wed thu fri sat sun`

These are language-neutral. Locale display (Mo/Di/Mi, Mon/Tue/Wed, Lun/Mar/Mer, etc.)
is handled by `WEEKDAY_ABBREVS` in `core/i18n.py` via `locale_abbrevs_to_canonical()`.
Never hardcode locale abbreviations in rules or code.

---

## 12. Agenda.md Structure

Fixed structure — always exactly four sections in this order:

```markdown
## ⛅ [Weekday], [DD.MM.YYYY]
*[Week-label] [N] / Updated: [HH:MM]*

---
## 📌 Recurring

- [ ] [recurring task]

---
## 📅 Today

[plain lines, no dashes, no checkboxes]

---
## 🗓️ This Week

[plain lines]

---
## 💶 Cashflow

[3–5 lines, actionable only]
```

---

## 13. Item Persistence

**Never automatically remove past appointments, deadlines, or tasks from Agenda.md.**

Only remove when the user explicitly:
- Marks done via `>` comment (`> done`, `> ✓`)
- Moves to a future date (`> postpone to DATE`)
- Gives an explicit instruction (`> no longer relevant`, or any clear dismissal)

Items may be temporarily suppressed but never silently deleted.

---

## 14. Boundaries

| | |
|---|---|
| MAY | Read/write Agenda.md, Exchange.md, Shadow.md |
| MAY | Delegate vault reads/writes to Data Agent (zeno) via `ask_zeno` |
| MAY NOT | Access other vault directories directly |
| MAY NOT | Send calendar invites (Action Agent) |
| MAY NOT | Access external APIs directly |
