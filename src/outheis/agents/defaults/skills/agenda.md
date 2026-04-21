# Default Skills: Agenda

## Agenda.md — first-time creation

If Agenda.md does not exist, create it using the default template. Populate from Shadow.md where available. From the second day onwards, follow the user's own structure.

Default template:

```
# ☀️ [Weekday], [Date] (Week [N])
*Updated: [HH:MM]*

---
## 📌 Recurring

- [ ]

---
## 📅 Today

**Overdue:**

**Communication:**

---
## 🗓️ This Week

---
## 💶 Finances
```

## Content synthesis

Extract information from vault files, understand context, then generate coherent Agenda.md sections. Do not copy/paste content blocks — synthesize appointments, events, and patterns into properly formatted items.

## Weekly section

The weekly section contains only the current week. Only specific dated appointments — no recurring activities.

## Comment-driven workflow

Lines starting with `>` are instructions. Read and execute before regeneration. The comment line is deleted afterwards — it never appears in the new version.

## Item persistence

Never remove past items automatically. Only on explicit user direction.

## Manual edit preservation

If the user changed the text or tags of an item directly in Agenda.md, that version is authoritative. Do not revert to Shadow.md or vault wording on the next run.

## Shadow.md surfacing

Mandatory items always surface to Today (no cap): `#date` today/past, `#action-required` with no date or overdue date. Optional fill: up to 5 items total in Today, chronological, from items up to 30 days out. Items tagged `#done-*` or `#cato-consolidated` are never shown.

## Checkboxes

Markdown checkboxes `- [ ]` only. Never ASCII alternatives.
