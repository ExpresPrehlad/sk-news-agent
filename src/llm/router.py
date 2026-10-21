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
from . import diagnostics
from .contracts import SelectionValidationError
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
    trace = diagnostics.TaskTrace(task, len(system), len(user))
    try:
        result = _generate(system, user, max_tokens, task=task,
                           response_schema=response_schema, validator=validator, trace=trace)
    except AllModelsFailed:
        trace.finish("failed")
        raise
    except Exception:
        trace.finish("unexpected_error")
        raise
    trace.finish("success", result[1])
    return result


def _generate(
    system: str, user: str, max_tokens: int, *, task: str,
    response_schema: dict | None, validator: Callable[[str], None] | None,
    trace: diagnostics.TaskTrace,
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
        if provider == "openrouter":
            trace.record["openrouter_entered"] = True
            log.info("LLM task=%s provider_transition=gemini->openrouter", task)
        # Reserve at least one normal request for the independent fallback.
        provider_deadline = deadline - min(LLM_TIMEOUT, LLM_CHAIN_TIMEOUT / 3) \
            if provider == "gemini" else deadline
        for model in chain:
            model_id = f"{provider}/{model}"
            now = time.monotonic()
            if now >= deadline:
                trace.skip(provider, "chain_budget_exhausted", model)
                raise AllModelsFailed([*errors, "LLM chain time budget exhausted"])
            if now >= provider_deadline:
                trace.skip(provider, "reserved_for_fallback", model)
                errors.append(f"{provider}: time reserved for fallback provider")
                break
            if _cooldowns.get(provider, 0) > now:
                trace.skip(provider, "shared_quota_cooldown", model)
                errors.append(f"{provider}: shared quota cooldown")
                break
            if _cooldowns.get(model_id, 0) > now:
                trace.skip(provider, "endpoint_cooldown", model)
                errors.append(f"{model_id}: endpoint cooldown")
                continue
            started = time.monotonic()
            timeout = min(LLM_TIMEOUT, provider_deadline - now)
            attempt, token = trace.attempt(provider, model, timeout)
            log.info("LLM task=%s model=%s attempt=%d started=true timeout=%.2f",
                     task, model_id, attempt["number"], timeout)
            try:
                text = client.generate(
                    model, system, user, max_tokens,
                    response_schema=response_schema,
                    timeout=timeout,
                )
                attempt["response_chars"] = len(text)
                if validator is not None:
                    try:
                        validator(text)
                    except (ValueError, TypeError, KeyError, AttributeError) as exc:
                        # Never log article text or arbitrary provider output.
                        code = "validation_error"
                        if isinstance(exc, SelectionValidationError):
                            code = diagnostics.safe_code(exc.code)
                            if type(exc.item_index) is int:
                                attempt["item_index"] = exc.item_index
                            if exc.field in ("headline", "perex", "title", "reason"):
                                attempt["field"] = exc.field
                        attempt["error_code"] = code
                        raise LLMError(f"invalid {task} output ({code})", code=code) from exc
                attempt.update(status="accepted", seconds=round(time.monotonic() - started, 3))
                log.info("LLM task=%s model=%s valid=true seconds=%.2f",
                         task, model_id, time.monotonic() - started)
                return text, model_id
            except LLMError as exc:
                attempt.update(status="failed", seconds=round(time.monotonic() - started, 3),
                               error_code=diagnostics.safe_code(exc.code))
                log.warning("LLM task=%s model=%s seconds=%.2f failed: %s",
                            task, model_id, time.monotonic() - started, exc)
                errors.append(f"{model_id}: {exc}")
                if isinstance(exc, RateLimited):
                    scope = provider if exc.provider_wide else model_id
                    _cooldowns[scope] = time.monotonic() + exc.cooldown_seconds
                if not exc.retryable_next or (
                    isinstance(exc, RateLimited) and exc.provider_wide
                ):
                    trace.skip(provider, "shared_quota_stop" if isinstance(exc, RateLimited)
                               and exc.provider_wide else "provider_stopped_after_error")
                    break  # Other provider may work; never escalate to paid.
            except Exception:
                attempt.update(status="failed", seconds=round(time.monotonic() - started, 3),
                               error_code="unexpected_error")
                raise
            finally:
                trace.restore(token)
    raise AllModelsFailed(errors)
