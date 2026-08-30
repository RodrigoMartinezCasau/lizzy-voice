"""Detección fuzzy del wake word «Lizzy» — rechaza el nombre anterior."""

from __future__ import annotations

import difflib
import re

from jarvis.lights.commands import preprocess_command_text

WAKE_CANONICAL = "lizzy"

# Ya no se responde a Jarvis ni alias antiguos
LEGACY_WAKE = re.compile(
    r"\b(?:jarvis|jarv[ií]s|garvis|garbage|service|servis|gervis|yarvis|charvis)\b",
    re.I,
)

LIZZY_PATTERN = re.compile(
    r"(?:"
    r"hey[\s,]*(?:lizzy|lizzie|lisi|lisy|licy|lizy|luci|lucy|lisie|lizzi|li[sx]i)"
    r"|"
    r"(?:ok|oye|ey|ei)[\s,]*(?:lizzy|lizzie|lisi|licy|lizy)"
    r"|"
    r"\b(?:lizzy|lizzie|lisi|lisy|licy|lizy|luci|lucy|lizzi)\b"
    r")",
    re.I,
)

WAKE_ALIASES = frozenset(
    {
        "lizzy",
        "lizzie",
        "lisi",
        "lissy",
        "lisy",
        "lysi",
        "licy",
        "licie",
        "lizzi",
        "lizy",
        "luci",
        "lucy",
        "lisie",
        "lixi",
        "liche",
        "lazy",
        "easy",
        "lisi.",
        "lizy.",
    }
)


def build_wake_prefix_pattern(wake_name: str = WAKE_CANONICAL) -> re.Pattern[str]:
    name = re.escape(wake_name.lower())
    variants = "|".join(
        re.escape(v)
        for v in sorted(
            {wake_name.lower(), "lizzie", "lisi", "lisy", "licy", "lizy", "luci", "lucy"},
            key=len,
            reverse=True,
        )
    )
    return re.compile(
        rf"^[\s¡!¿?]*(?:hey[\s,]*(?:{variants})|{name}|{variants})[\s!.:;,-]*",
        re.I,
    )


def _word_like_lizzy(word: str) -> bool:
    w = word.lower().strip(".,!?¡¿")
    if not w or len(w) < 3:
        return False
    if w in WAKE_ALIASES:
        return True
    if difflib.SequenceMatcher(None, w, WAKE_CANONICAL).ratio() >= 0.58:
        return True
    if difflib.SequenceMatcher(None, w, "lizzie").ratio() >= 0.62:
        return True
    if len(w) >= 4 and w.startswith(("liz", "lis", "lic", "luc")):
        if difflib.SequenceMatcher(None, w, WAKE_CANONICAL).ratio() >= 0.5:
            return True
    return False


def _has_lizzy_signal(text: str) -> bool:
    if LIZZY_PATTERN.search(text):
        return True
    low = preprocess_command_text(text)
    if "lizz" in low or "lisy" in low or "lisi" in low or "licy" in low:
        return True
    words = re.findall(r"\b[\wáéíóúñ]+", low, flags=re.I)
    return any(_word_like_lizzy(word) for word in words)


def looks_like_wake(text: str) -> bool:
    """True si la frase activa a Lizzy. Jarvis explícito → False."""
    if not text or not text.strip():
        return False
    if LEGACY_WAKE.search(text) and not _has_lizzy_signal(text):
        return False
    if LIZZY_PATTERN.search(text):
        return True
    low = preprocess_command_text(text)
    if "lizz" in low or "lisi" in low or "lisy" in low or "licy" in low:
        return True
    words = re.findall(r"\b[\wáéíóúñ]+", low, flags=re.I)
    for word in words:
        if _word_like_lizzy(word):
            return True
    if re.search(r"\b(?:hey|oye|ey|ei)\b", low, re.I):
        for word in words:
            if len(word) >= 3 and difflib.SequenceMatcher(
                None, word, WAKE_CANONICAL
            ).ratio() >= 0.48:
                return True
    return False
