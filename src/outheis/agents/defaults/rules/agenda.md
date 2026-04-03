# Default Rules: Agenda

## Daily.md format

- Use markdown checkboxes `- [ ]` only. Never use ASCII alternatives (□, ☐, etc.).
- Daily.md contains only today's information. It is a single-day file, not a multi-day document.
- Do not include recurring activities in the weekly section — only specific appointments with confirmed dates.

## User comments as instructions

- Lines starting with `>` in Daily.md are action instructions, not notes.
- Process them before regeneration:
  - `> done` / `> ✓` → remove the item
  - `> postpone to [date]` → reschedule
  - `> not important` → delete
- The comment line itself is always deleted after processing — it never appears in the regenerated file.

## Item lifecycle

- Never automatically remove past appointments, deadlines, or tasks.
- Remove an item only when the user explicitly marks it done, moves it to a future date, or gives a clear instruction to handle it.
