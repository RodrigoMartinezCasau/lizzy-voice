"""Utilidades para alinear TTS y efectos visuales."""

from __future__ import annotations

import re


def split_speech_phrases(text: str) -> list[str]:
    """Parte el texto en frases para sincronizar pulsos LED con la locución."""
    cleaned = text.strip()
    if not cleaned:
        return []
    parts = re.split(r"(?<=[.!?…])\s+|\s*(?<=\.)\s*", cleaned)
    phrases = [p.strip() for p in parts if p.strip()]
    if not phrases:
        return [cleaned]
    merged: list[str] = []
    for phrase in phrases:
        if merged and len(phrase) < 12:
            merged[-1] = f"{merged[-1]} {phrase}"
        else:
            merged.append(phrase)
    return merged


def count_speech_cycles(text: str) -> int:
    """Latidos LED ≈ una pulsación cada ~2 palabras o por frase."""
    words = len(text.split())
    phrases = split_speech_phrases(text)
    return max(1, max(len(phrases) * 2, words // 2))
