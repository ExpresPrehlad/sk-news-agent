"""
Gemini klient (Google AI Studio, free tier).

Voláme REST endpoint priamo cez requests — bez google SDK, nech držíme
závislosti minimálne. Free tier limity (RPM/RPD) sa prejavia ako HTTP 429;
klasifikáciu chýb rieši router, my tu len prekladáme HTTP na výnimky.
"""

from __future__ import annotations

import logging
import math

import requests

from ..config import GEMINI_API_KEY, LLM_TIMEOUT

log = logging.getLogger(__name__)

_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_FREE_MODELS = frozenset({
    "gemini-3.5-flash-lite", "gemini-3.1-flash-lite",
    "gemini-3.5-flash", "gemini-3.8-flash",
})


class LLMError(Exception):
    """Základná chyba LLM volania."""

    def __init__(self, message: str, retryable_next: bool = True):
        super().__init__(message)
        # retryable_next=True → router má skúsiť ďalší model v reťazi.
        self.retryable_next = retryable_next


class RateLimited(LLMError):
    """Quota/backpressure, optionally shared across all provider models."""

    def __init__(self, message: str, *, provider_wide: bool = False,
                 cooldown_seconds: float = 60.0):
        super().__init__(message)
        self.provider_wide = provider_wide
        self.cooldown_seconds = max(1.0, min(86400.0, cooldown_seconds)) \
            if math.isfinite(cooldown_seconds) else 60.0


def _rate_error(resp, model: str) -> RateLimited:
    seconds = 60.0
    daily = False
    try:
        seconds = max(seconds, float(resp.headers.get("Retry-After", "0")))
    except (TypeError, ValueError):
        pass
    try:
        for detail in resp.json().get("error", {}).get("details", []):
            delay = detail.get("retryDelay")
            if isinstance(delay, str) and delay.endswith("s"):
                seconds = max(seconds, float(delay[:-1]))
            for violation in detail.get("violations", []):
                quota = str(violation.get("quotaId", "")).lower().replace("_", "")
                daily = daily or "perday" in quota
    except (ValueError, TypeError, AttributeError):
        pass
    return RateLimited(
        f"Gemini {model}: {'daily quota' if daily else 'rate limit'} (429)",
        cooldown_seconds=86400.0 if daily else seconds,
    )


def generate(
    model: str, system: str, user: str, max_tokens: int = 2048, *,
    response_schema: dict | None = None, timeout: float | None = None,
) -> str:
    if model not in _FREE_MODELS:
        raise LLMError("Gemini: model nie je v overenom free-tier zozname")
    if not GEMINI_API_KEY:
        raise LLMError("GEMINI_API_KEY nie je nastavený", retryable_next=False)

    payload = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {
            "temperature": 0.3,
            # Thinking shares the output budget. Keep room for JSON without
            # adding requests, tools, grounding or a paid service tier.
            "maxOutputTokens": max_tokens + 2048,
            "thinkingConfig": {"thinkingLevel": "LOW", "includeThoughts": False},
        },
    }
    if response_schema is not None:
        payload["generationConfig"].update({
            "responseMimeType": "application/json",
            "responseJsonSchema": response_schema,
        })
    try:
        resp = requests.post(
            _ENDPOINT.format(model=model),
            headers={"x-goog-api-key": GEMINI_API_KEY},
            json=payload,
            timeout=LLM_TIMEOUT if timeout is None else timeout,
        )
    except requests.RequestException as exc:
        # Request exceptions can contain a URL/API key. Do not log their text.
        raise LLMError(f"Gemini sieťová chyba ({type(exc).__name__})") from exc

    if resp.status_code == 429:
        raise _rate_error(resp, model)
    if resp.status_code != 200:
        raise LLMError(f"Gemini {model}: HTTP {resp.status_code}",
                       retryable_next=resp.status_code != 401)

    try:
        data = resp.json()
        candidate = data["candidates"][0]
        finish = candidate.get("finishReason")
        if finish not in (None, "STOP"):
            raise LLMError(f"Gemini {model}: nedokončený/blokovaný výstup ({finish})")
        parts = candidate["content"]["parts"]
        text = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
        usage = data.get("usageMetadata") or {}
        log.info("LLM usage model=gemini/%s input=%s output=%s thoughts=%s",
                 model, usage.get("promptTokenCount"), usage.get("candidatesTokenCount"),
                 usage.get("thoughtsTokenCount"))
    except (KeyError, IndexError, ValueError, TypeError, AttributeError) as exc:
        raise LLMError(f"Gemini {model}: nečakaný formát odpovede") from exc

    if not text:
        raise LLMError(f"Gemini {model}: prázdna odpoveď (safety block?)")
    return text
