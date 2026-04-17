# outheis Color System

Machine-readable format: each color entry is a YAML-style block between `---` markers.

---
name: Charcoal
hex: "#1A1A1A"
role: text-primary, border-primary
usage: Primary text, structural borders (sidebar, topbar, statusbar)
---

---
name: Slate
hex: "#4A4646"
role: text-secondary
usage: Secondary text, labels, form hints
---

---
name: Stone
hex: "#7A7676"
role: text-tertiary
usage: Muted text, timestamps, placeholders
---

---
name: Silver
hex: "#B8B4B4"
role: border-secondary
usage: Inner row separators, card borders, input borders
---

---
name: Mist
hex: "#E8E6E6"
role: bg-tertiary
usage: Hover backgrounds, tertiary surfaces
---

---
name: White
hex: "#FFFFFF"
role: bg-primary
usage: Primary background (cards, sidebar, topbar)
---

---
name: Fog
hex: "#F4F3F3"
role: bg-secondary
usage: Main content area background, scrollable panels
---

## Accent Colors

---
name: Teal
hex: "#218380"
role: accent-success, agent-relay (ou)
usage: Success states, running indicator, ou agent
---

---
name: Amber Flame
hex: "#FFB400"
role: accent-warning, agent-action (hiro)
usage: Warning states, fallback status, hiro agent
---

---
name: Scarlet Fire
hex: "#FF2E00"
role: accent-danger, agent-agenda (cato)
usage: Error states, destructive actions, cato agent
---

---
name: Wisteria
hex: "#C490D1"
role: accent-info, agent-code (alan)
usage: Info states, alan agent
---

---
name: Pearl Aqua
hex: "#97EAD2"
role: agent-data (zeno)
usage: zeno agent
---

---
name: Dark Amethyst
hex: "#460A46"
role: agent-pattern (rumi)
usage: rumi agent
---

---
name: Wisteria
hex: "#C490D1"
role: accent-info, accent-primary, agent-code (alan)
usage: Info states, token usage chart, alan agent
---

## Agent Color Map

| Agent | Name | Key    | Color         | Hex      |
|-------|------|--------|---------------|----------|
| ou    | ou   | relay  | Teal          | #218380  |
| zeno  | zeno | data   | Pearl Aqua    | #97EAD2  |
| cato  | cato | agenda | Scarlet Fire  | #FF2E00  |
| hiro  | hiro | action | Amber Flame   | #FFB400  |
| rumi  | rumi | pattern| Dark Amethyst | #460A46  |
| alan  | alan | code   | Wisteria      | #C490D1  |

## CSS Variables (style.css)

```css
--bg-primary:     #FFFFFF;
--bg-secondary:   #F4F3F3;
--bg-tertiary:    #E8E6E6;

--text-primary:   #1A1A1A;  /* Charcoal */
--text-secondary: #4A4646;  /* Slate */
--text-tertiary:  #7A7676;  /* Stone */

--border-primary:   #1A1A1A;  /* Charcoal */
--border-secondary: #B8B4B4;  /* Silver */

--accent-primary: #C490D1;  /* Wisteria */
--accent-info:    #C490D1;  /* Wisteria */
--accent-success: #218380;  /* Teal */
--accent-warning: #FFB400;  /* Amber Flame */
--accent-danger:  #FF2E00;  /* Scarlet Fire */
```
