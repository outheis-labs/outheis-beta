"""Centralized internationalization strings for outheis.

All user-facing translated content lives here. Agents and transports import
from this module rather than defining inline language dicts.

Usage:
    from outheis.core.i18n import t, WEEKDAYS, AGENDA_LABELS
    label = t(INTERIM_LOCAL_MODEL, lang)
    wdays = WEEKDAYS.get(lang, WEEKDAYS["en"])
"""

from __future__ import annotations


def t(mapping: dict[str, str], lang: str, fallback: str = "en") -> str:
    """Look up a localized string. Falls back to base language code, then fallback."""
    result = mapping.get(lang)
    if result is None and "-" in lang:
        result = mapping.get(lang.split("-")[0])
    if result is None:
        result = mapping.get(fallback, "")
    return result


# ---------------------------------------------------------------------------
# Interim / status messages
# ---------------------------------------------------------------------------

INTERIM_LOCAL_MODEL: dict[str, str] = {
    "de": "Einen Moment — lokales Modell, das kann etwas dauern...",
    "en": "One moment — local model, this may take a little longer...",
    "fr": "Un instant — modèle local, cela peut prendre un peu plus de temps...",
    "es": "Un momento — modelo local, esto puede tardar un poco más...",
    "it": "Un momento — modello locale, potrebbe richiedere un po' più di tempo...",
    "pt": "Um momento — modelo local, isso pode demorar um pouco mais...",
    "nl": "Eén moment — lokaal model, dit kan iets langer duren...",
    "pl": "Chwileczkę — model lokalny, to może chwilę potrwać...",
    "ru": "Одну минуту — локальная модель, это может занять чуть больше времени...",
    "tr": "Bir saniye — yerel model, bu biraz daha uzun sürebilir...",
    "el": "Ένα λεπτό — τοπικό μοντέλο, αυτό μπορεί να πάρει λίγο περισσότερο χρόνο...",
    "ja": "少々お待ちください — ローカルモデルのため、少し時間がかかる場合があります...",
    "zh": "请稍候 — 本地模型，可能需要更多时间...",
    "ko": "잠시만요 — 로컬 모델, 조금 더 걸릴 수 있습니다...",
    "ar": "لحظة من فضلك — نموذج محلي، قد يستغرق وقتاً أطول قليلاً...",
}

PROPOSAL_PENDING: dict[str, str] = {
    "de": "(Zusammenfassung ausstehend — kurze Beschreibung des Vorschlags ergänzen.)",
    "en": "(Summary pending — add a brief description of this proposal.)",
    "fr": "(Résumé en attente — ajouter une brève description de cette proposition.)",
    "es": "(Resumen pendiente — añadir una breve descripción de esta propuesta.)",
    "it": "(Riepilogo in attesa — aggiungere una breve descrizione di questa proposta.)",
}


# ---------------------------------------------------------------------------
# Agenda scaffold strings
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Annotation keywords (used in cato system prompt)
# ---------------------------------------------------------------------------

ANNOTATION_COMPLETION_KEYWORDS: dict[str, list[str]] = {
    "de": ["erledigt", "abgehakt", "done", "nachgefasst", "bestätigt", "fertig", "geklärt"],
    "en": ["done", "completed", "finished", "confirmed", "resolved", "checked off"],
    "fr": ["fait", "terminé", "complété", "confirmé", "résolu"],
    "es": ["hecho", "completado", "terminado", "confirmado", "resuelto"],
    "it": ["fatto", "completato", "terminato", "confermato", "risolto"],
}

ANNOTATION_POSTPONE_KEYWORDS: dict[str, list[str]] = {
    "de": ["vertagen", "zurückstellen", "später", "frühestens", "nächste Woche", "nächsten Monat"],
    "en": ["postpone", "defer", "later", "not yet", "next week", "next month"],
    "fr": ["reporter", "différer", "plus tard", "semaine prochaine", "mois prochain"],
    "es": ["posponer", "aplazar", "más tarde", "la próxima semana", "el próximo mes"],
    "it": ["posticipare", "rinviare", "più tardi", "la settimana prossima", "il mese prossimo"],
}

ANNOTATION_BEHAVIORAL_KEYWORDS: dict[str, list[str]] = {
    "de": ["immer", "grundsätzlich", "nie", "niemals", "ab jetzt", "von nun an"],
    "en": ["always", "never", "from now on", "going forward", "in general", "as a rule"],
    "fr": ["toujours", "jamais", "désormais", "en général", "en règle générale"],
    "es": ["siempre", "nunca", "de ahora en adelante", "en general", "por regla general"],
    "it": ["sempre", "mai", "d'ora in poi", "in generale", "di norma"],
}

# Verb stems indicating a read/display intent (relay fast-route detection)
AGENDA_READ_INTENT_STEMS: dict[str, list[str]] = {
    "de": ["zeig", "anzeig", "was steht"],
    "en": ["show", "get", "fetch", "display", "read", "what"],
    "fr": ["montr", "affich", "qu'est"],
    "es": ["muest", "mostr"],
    "it": ["mostr", "visualizz"],
}

# Verb stems indicating a modification/action request (agenda handle_direct guard)
AGENDA_MODIFY_STEMS: dict[str, list[str]] = {
    "de": ["abhak", "hak ab", "abschlie", "entfern", "verschieb", "vertag"],
    "en": ["mark", "tick", "check off", "close", "remove", "delete",
           "move", "postpone", "finish", "complete", "resolve", "abort"],
    "fr": ["marqu", "supprimer", "finir", "termin"],
    "es": ["marcar", "eliminar", "terminar"],
    "it": ["segna", "elimina", "finire"],
}

# Routing verb stems for relay agenda-write path detection
AGENDA_WRITE_STEMS: dict[str, list[str]] = {
    "de": ["aktualisier", "erstell", "änder", "hinzufüg", "ergänz", "neu generier", "schreib", "trag ein", "notier"],
    "en": ["update", "creat", "chang", "add", "append", "regenerat"],
    "fr": ["mettr", "créer", "modifier", "ajouter", "compléter", "régénérer"],
    "es": ["actualiz", "crear", "cambiar", "añadir", "completar", "regenerar"],
    "it": ["aggiorna", "crea", "cambia", "aggiungi", "completa", "rigenera"],
}


# ---------------------------------------------------------------------------
# Weekdays
# ---------------------------------------------------------------------------

WEEKDAYS: dict[str, list[str]] = {
    "de": ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"],
    "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
    "fr": ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"],
    "es": ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"],
    "it": ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"],
    "pt": ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"],
    "nl": ["Maandag", "Dinsdag", "Woensdag", "Donderdag", "Vrijdag", "Zaterdag", "Zondag"],
}

# Short weekday abbreviations per locale (index matches WEEKDAYS — 0=Monday)
WEEKDAY_ABBREVS: dict[str, list[str]] = {
    "de": ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"],
    "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    "fr": ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"],
    "es": ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"],
    "it": ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"],
    "pt": ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"],
    "nl": ["Ma", "Di", "Wo", "Do", "Vr", "Za", "Zo"],
}

# Canonical weekday codes for Shadow.md recurring tags — always ISO English, language-neutral.
# Index 0 = Monday (matches Python's date.weekday()).
RECURRING_WEEKDAY_CODES: list[str] = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

def locale_abbrevs_to_canonical(abbrevs: list[str], lang: str) -> list[str]:
    """Convert locale weekday abbreviations to canonical ISO codes.

    Example: ["Mo", "Mi", "Do"] with lang="de" -> ["mon", "wed", "thu"]
    Unknown abbreviations are returned unchanged (lowercased).
    """
    locale_list = WEEKDAY_ABBREVS.get(lang, WEEKDAY_ABBREVS.get(lang.split("-")[0], []))
    lookup = {a.lower(): RECURRING_WEEKDAY_CODES[i] for i, a in enumerate(locale_list)}
    result = []
    for a in abbrevs:
        result.append(lookup.get(a.lower(), a.lower()))
    return result


AGENDA_LABELS: dict[str, dict[str, str]] = {
    "de": {
        "week": "KW",
        "personal": "Fixpunkte",
        "today_hdr": "Heute",
        "week_hdr": "Diese Woche",
        "overdue": "Überfällig",
        "today_lbl": "Heute",
        "empty_today": "*(keine überfälligen oder heutigen Items)*",
        "empty_week": "*(keine Items diese Woche)*",
        "generated": "Aktualisiert",
        "comment_hint": "Mit \">\" nach einem Item kommentieren oder anweisen.",
    },
    "en": {
        "week": "Week",
        "personal": "Recurring",
        "today_hdr": "Today",
        "week_hdr": "This Week",
        "overdue": "Overdue",
        "today_lbl": "Today",
        "empty_today": "*(no overdue or due-today items)*",
        "empty_week": "*(no items this week)*",
        "generated": "Generated",
        "comment_hint": "Use \">\" after an item to comment or give instructions.",
    },
    "fr": {
        "week": "Semaine",
        "personal": "Récurrent",
        "today_hdr": "Aujourd'hui",
        "week_hdr": "Cette semaine",
        "overdue": "En retard",
        "today_lbl": "Aujourd'hui",
        "empty_today": "*(aucun élément en retard ou dû aujourd'hui)*",
        "empty_week": "*(aucun élément cette semaine)*",
        "generated": "Généré",
        "comment_hint": "Utilisez \">\" après un élément pour commenter ou donner des instructions.",
    },
    "es": {
        "week": "Semana",
        "personal": "Recurrente",
        "today_hdr": "Hoy",
        "week_hdr": "Esta semana",
        "overdue": "Atrasado",
        "today_lbl": "Hoy",
        "empty_today": "*(sin elementos vencidos o de hoy)*",
        "empty_week": "*(sin elementos esta semana)*",
        "generated": "Generado",
        "comment_hint": "Use \">\" después de un elemento para comentar o dar instrucciones.",
    },
    "it": {
        "week": "Settimana",
        "personal": "Ricorrente",
        "today_hdr": "Oggi",
        "week_hdr": "Questa settimana",
        "overdue": "In ritardo",
        "today_lbl": "Oggi",
        "empty_today": "*(nessun elemento scaduto o di oggi)*",
        "empty_week": "*(nessun elemento questa settimana)*",
        "generated": "Generato",
        "comment_hint": "Usa \">\" dopo un elemento per commentare o dare istruzioni.",
    },
}
