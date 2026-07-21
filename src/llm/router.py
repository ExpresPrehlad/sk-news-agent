"""
LLM router — eskalačná reťaz.

Poradie: Gemini modely (najvyšší free RPD) → OpenRouter free zoznam →
openrouter/free auto-router. Prvý úspech vyhráva; každé zlyhanie sa
zaloguje a pokračuje sa ďalej. Ak padne všetko, vyhodí AllModelsFailed —
volajúci rozhodne, či to je dôvod na Discord error alert.

Vracia (text, model_id), aby výstup mohol niesť indikátor modelu —
redakcia má vedieť, kedy číta výstup zo slabšieho fallback modelu.
"""

from __future__ import annotations

import logging

from ..config import GEMINI_MODELS, OPENROUTER_MODELS
from . import gemini, openrouter
from .gemini import LLMError

log = logging.getLogger(__name__)


class AllModelsFailed(Exception):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def generate(system: str, user: str, max_tokens: int = 2048) -> tuple[str, str]:
    errors: list[str] = []

    for model in GEMINI_MODELS:
        try:
            text = gemini.generate(model, system, user, max_tokens)
            return text, f"gemini/{model}"
        except LLMError as exc:
            log.warning("Model gemini/%s zlyhal: %s", model, exc)
            errors.append(f"gemini/{model}: {exc}")

    for model in OPENROUTER_MODELS:
        try:
            text = openrouter.generate(model, system, user, max_tokens)
            return text, f"openrouter/{model}"
        except LLMError as exc:
            log.warning("Model openrouter/%s zlyhal: %s", model, exc)
            errors.append(f"openrouter/{model}: {exc}")

    raise AllModelsFailed(errors)
