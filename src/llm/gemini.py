"""
Gemini klient (Google AI Studio, free tier).

Voláme REST endpoint priamo cez requests — bez google SDK, nech držíme
závislosti minimálne. Free tier limity (RPM/RPD) sa prejavia ako HTTP 429;
klasifikáciu chýb rieši router, my tu len prekladáme HTTP na výnimky.
"""

from __future__ import annotations

import logging

import requests

from ..config import GEMINI_API_KEY, LLM_TIMEOUT

log = logging.getLogger(__name__)

_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class LLMError(Exception):
    """Základná chyba LLM volania."""

    def __init__(self, message: str, retryable_next: bool = True):
        super().__init__(message)
        # retryable_next=True → router má skúsiť ďalší model v reťazi.
        self.retryable_next = retryable_next


class RateLimited(LLMError):
    """HTTP 429 — vyčerpaný limit, jednoznačný signál posunúť sa ďalej."""


def generate(model: str, system: str, user: str, max_tokens: int = 2048) -> str:
    if not GEMINI_API_KEY:
        raise LLMError("GEMINI_API_KEY nie je nastavený", retryable_next=True)

    payload = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": max_tokens,
        },
    }
    try:
        resp = requests.post(
            _ENDPOINT.format(model=model),
            params={"key": GEMINI_API_KEY},
            json=payload,
            timeout=LLM_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise LLMError(f"Gemini sieťová chyba: {exc}") from exc

    if resp.status_code == 429:
        raise RateLimited(f"Gemini {model}: rate limit (429)")
    if resp.status_code != 200:
        raise LLMError(f"Gemini {model}: HTTP {resp.status_code}: {resp.text[:300]}")

    try:
        data = resp.json()
        parts = data["candidates"][0]["content"]["parts"]
        text = "".join(p.get("text", "") for p in parts).strip()
    except (KeyError, IndexError, ValueError) as exc:
        raise LLMError(f"Gemini {model}: nečakaný formát odpovede: {exc}") from exc

    if not text:
        raise LLMError(f"Gemini {model}: prázdna odpoveď (safety block?)")
    return text
