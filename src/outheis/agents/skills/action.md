# Action Agent Skills

## Prinzipien

- Code ist die Wahrheit — im Zweifel nachschauen
- Konkrete Zeilennummern und Funktionsnamen nennen
- Nicht nur erklären, sondern auch Lösungen vorschlagen

## Code-Fragen beantworten

Wenn gefragt "warum kann X nicht Y?":
1. `search_source` nach relevanten Keywords
2. `read_source` der verdächtigen Dateien
3. Erkläre was im Code passiert
4. Zeige wo die Limitierung ist
5. Schlage vor was geändert werden müsste

## Wichtige Dateien

- `agents/relay.py` — Hauptkoordinator, Tools, Routing
- `agents/data.py` — Vault-Operationen
- `agents/agenda.py` — Terminverwaltung
- `agents/pattern.py` — Lernen, Memory-Extraktion
- `core/config.py` — Konfiguration
- `core/memory.py` — Memory-System
- `agents/skills/*.md` — Agent-Skills
- `agents/rules/*.md` — Agent-Regeln

## Erklärungsstil

Kurz und technisch:
- "In `relay.py:245` fehlt ein Tool für X"
- "Die Funktion `_handle_foo()` prüft nicht auf Y"
- "Um das zu ändern: füge in Zeile Z hinzu..."
