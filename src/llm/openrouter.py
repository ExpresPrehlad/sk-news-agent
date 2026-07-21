"""
OpenRouter klient (free modely, :free suffix + auto-router).

OpenAI-kompatibilný chat completions endpoint. Free modely majú 20 RPM
a denný strop podľa účtu (1 000/deň pri jednorazovom nákupe kreditov 10 $+).
Provider-side throttling v špičke sa prejaví ako 429 alebo 503 — oboje
klasifikujeme ako "skús ďalší model".
"""

from __future__ import annotations

import logging

import requests

from ..config import LLM_TIMEOUT, OPENROUTER_API_KEY
from .gemini import LLMError, RateLimited

log = logging.getLogger(__name__)

_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"


def generate(model: str, system: str, user: str, max_tokens: int = 2048) -> str:
    if not OPENROUTER_API_KEY:
        raise LLMError("OPENROUTER_API_KEY nie je nastavený", retryable_next=True)

    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": 0.3,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    try:
        resp = requests.post(
            _ENDPOINT,
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                # OpenRouter odporúča identifikáciu aplikácie:
                "HTTP-Referer": "https://github.com/ExpresPrehlad/sk-news-agent",
                "X-Title": "sk-news-agent",
            },
            json=payload,
            timeout=LLM_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise LLMError(f"OpenRouter sieťová chyba: {exc}") from exc

    if resp.status_code in (429, 503):
        raise RateLimited(f"OpenRouter {model}: {resp.status_code} (limit/preťaženie)")
    if resp.status_code != 200:
        raise LLMError(f"OpenRouter {model}: HTTP {resp.status_code}: {resp.text[:300]}")

    try:
        data = resp.json()
        text = (data["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, ValueError) as exc:
        raise LLMError(f"OpenRouter {model}: nečakaný formát odpovede: {exc}") from exc

    if not text:
        raise LLMError(f"OpenRouter {model}: prázdna odpoveď")
    return text
