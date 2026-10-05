"""
OpenRouter klient — iba explicitné bezplatné varianty, bez auto-routera.

OpenAI-kompatibilný chat completions endpoint. Free modely majú 20 RPM
a denný strop podľa účtu (1 000/deň pri jednorazovom nákupe kreditov 10 $+).
Provider-side throttling v špičke sa prejaví ako 429 alebo 503 — oboje
klasifikujeme ako "skús ďalší model".
"""

from __future__ import annotations

import logging
import time

import requests

from ..config import LLM_TIMEOUT, OPENROUTER_API_KEY
from .gemini import LLMError, RateLimited

log = logging.getLogger(__name__)

_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"

# Deliberate allowlist, not just a suffix: never use a random safety model or
# an unreviewed paid variant. Provider price caps also fail closed on changes.
_FREE_MODELS = frozenset({
    "nvidia/nemotron-3-super-120b-a12b:free",
    "google/gemma-4-31b-it:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
})


def _quota_error(resp) -> RateLimited:
    headers = resp.headers
    provider_wide = resp.status_code == 429 and any(
        name in headers for name in ("X-RateLimit-Limit", "X-RateLimit-Reset")
    )
    try:
        seconds = float(headers.get("Retry-After", "60"))
    except (TypeError, ValueError):
        seconds = 60.0
    if provider_wide:
        try:
            seconds = max(seconds, float(headers.get("X-RateLimit-Reset", "0")) - time.time())
        except (TypeError, ValueError):
            pass
    return RateLimited(
        f"OpenRouter: HTTP {resp.status_code} (shared quota)" if provider_wide else
        f"OpenRouter: HTTP {resp.status_code} (provider limit/unavailable)",
        provider_wide=provider_wide, cooldown_seconds=seconds,
    )


def generate(
    model: str, system: str, user: str, max_tokens: int = 2048, *,
    response_schema: dict | None = None, timeout: float | None = None,
) -> str:
    if model not in _FREE_MODELS:
        raise LLMError("OpenRouter: model nie je v povolenom bezplatnom zozname")
    if not OPENROUTER_API_KEY:
        raise LLMError("OPENROUTER_API_KEY nie je nastavený", retryable_next=False)

    payload = {
        "model": model,
        "max_tokens": max_tokens + 2048,
        "temperature": 0.3,
        "provider": {
            "max_price": {"prompt": 0, "completion": 0, "request": 0},
            "require_parameters": True,
        },
        "reasoning": {"exclude": True, "effort": "low"} if model.startswith("nvidia/") else
                     {"exclude": True, "enabled": False},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if response_schema is not None:
        if model == "nvidia/nemotron-3-super-120b-a12b:free":
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "news_selection", "strict": True,
                                "schema": response_schema},
            }
        elif model == "google/gemma-4-31b-it:free":
            payload["response_format"] = {"type": "json_object"}
        # Ultra currently has no native response_format support. Its output
        # must still pass the same local validator before router acceptance.
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
            timeout=LLM_TIMEOUT if timeout is None else timeout,
        )
    except requests.RequestException as exc:
        raise LLMError(f"OpenRouter sieťová chyba ({type(exc).__name__})") from exc

    if resp.status_code in (429, 503):
        raise _quota_error(resp)
    if resp.status_code != 200:
        raise LLMError(f"OpenRouter {model}: HTTP {resp.status_code}",
                       retryable_next=resp.status_code not in (401, 402))

    try:
        data = resp.json()
        if data.get("error"):
            raise LLMError(f"OpenRouter {model}: error v úspešnej HTTP odpovedi")
        served_model = data.get("model", model)
        # Some providers report the canonical model without the :free suffix.
        # Free pricing is enforced in the request, not inferred from this label.
        if not isinstance(served_model, str) or (
            served_model.removesuffix(":free") != model.removesuffix(":free")
        ):
            raise LLMError(f"OpenRouter {model}: neočakávaná zmena modelu")
        choice = data["choices"][0]
        finish = choice.get("finish_reason")
        if finish not in (None, "stop"):
            raise LLMError(f"OpenRouter {model}: nedokončený/blokovaný výstup ({finish})")
        text = (choice["message"]["content"] or "").strip()
        usage = data.get("usage") or {}
        log.info("LLM usage model=openrouter/%s input=%s output=%s",
                 served_model, usage.get("prompt_tokens"), usage.get("completion_tokens"))
    except (KeyError, IndexError, ValueError, TypeError, AttributeError) as exc:
        raise LLMError(f"OpenRouter {model}: nečakaný formát odpovede") from exc

    if not text:
        raise LLMError(f"OpenRouter {model}: prázdna odpoveď")
    return text
