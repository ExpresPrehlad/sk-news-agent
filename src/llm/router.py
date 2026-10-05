"""Task-specific, free-model fallback with validation before acceptance."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from ..config import (
    GEMINI_MODELS, GEMINI_TRIAGE_MODELS, GEMINI_SYNTHESIS_MODELS,
    OPENROUTER_MODELS, LLM_TIMEOUT, LLM_CHAIN_TIMEOUT,
)
from . import gemini, openrouter
from .gemini import LLMError, RateLimited

log = logging.getLogger(__name__)

# Process-local only: no new writes to generated state or selection logs.
_cooldowns: dict[str, float] = {}


class AllModelsFailed(Exception):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def generate(
    system: str, user: str, max_tokens: int = 2048, *,
    task: str = "generic", response_schema: dict | None = None,
    validator: Callable[[str], None] | None = None,
) -> tuple[str, str]:
    errors: list[str] = []
    models = {
        "triage": GEMINI_TRIAGE_MODELS,
        "synthesis": GEMINI_SYNTHESIS_MODELS,
    }.get(task, GEMINI_MODELS)
    deadline = time.monotonic() + LLM_CHAIN_TIMEOUT
    for provider, client, chain in (
        ("gemini", gemini, models), ("openrouter", openrouter, OPENROUTER_MODELS),
    ):
        # Reserve at least one normal request for the independent fallback.
        provider_deadline = deadline - min(LLM_TIMEOUT, LLM_CHAIN_TIMEOUT / 3) \
            if provider == "gemini" else deadline
        for model in chain:
            model_id = f"{provider}/{model}"
            now = time.monotonic()
            if now >= deadline:
                raise AllModelsFailed([*errors, "LLM chain time budget exhausted"])
            if now >= provider_deadline:
                errors.append(f"{provider}: time reserved for fallback provider")
                break
            if _cooldowns.get(provider, 0) > now:
                errors.append(f"{provider}: shared quota cooldown")
                break
            if _cooldowns.get(model_id, 0) > now:
                errors.append(f"{model_id}: endpoint cooldown")
                continue
            started = time.monotonic()
            try:
                text = client.generate(
                    model, system, user, max_tokens,
                    response_schema=response_schema,
                    timeout=min(LLM_TIMEOUT, provider_deadline - now),
                )
                if validator is not None:
                    try:
                        validator(text)
                    except (ValueError, TypeError, KeyError, AttributeError) as exc:
                        # Never log article text or arbitrary provider output.
                        raise LLMError(f"invalid {task} output ({type(exc).__name__})") from exc
                log.info("LLM task=%s model=%s valid=true seconds=%.2f",
                         task, model_id, time.monotonic() - started)
                return text, model_id
            except LLMError as exc:
                log.warning("LLM task=%s model=%s seconds=%.2f failed: %s",
                            task, model_id, time.monotonic() - started, exc)
                errors.append(f"{model_id}: {exc}")
                if isinstance(exc, RateLimited):
                    scope = provider if exc.provider_wide else model_id
                    _cooldowns[scope] = time.monotonic() + exc.cooldown_seconds
                if not exc.retryable_next or (
                    isinstance(exc, RateLimited) and exc.provider_wide
                ):
                    break  # Other provider may work; never escalate to paid.
    raise AllModelsFailed(errors)
