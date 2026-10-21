"""Safe, process-local LLM traces. No prompts, responses, URLs or credentials.

The optional JSON report belongs in runner.temp and an Actions artifact, NOT in
generated website/state commits. Diagnostics must never break news collection.
"""

from __future__ import annotations

import json
import logging
import os
import time
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

log = logging.getLogger(__name__)
_active_attempt: ContextVar[dict | None] = ContextVar("llm_attempt", default=None)
_reports: list[dict] = []
_ERROR_CODES = frozenset({
    "llm_error", "missing_api_key", "model_not_allowed", "http_error",
    "network_error", "request_timeout", "daily_quota", "rate_limit",
    "shared_quota", "provider_unavailable", "incomplete_output",
    "unexpected_response", "empty_response", "unexpected_model",
    "provider_error", "validation_error", "invalid_json", "missing_json_object",
    "wrong_root_fields", "selection_not_array", "empty_topics", "too_many_selections",
    "item_not_object", "missing_selection_field", "invalid_links", "link_not_string",
    "unknown_source_link", "invalid_source_url", "invalid_signals", "unexpected_error",
})


def safe_code(value: object) -> str:
    return value if isinstance(value, str) and value in _ERROR_CODES else "llm_error"


def reset() -> None:
    _reports.clear()


def token_count(value: object) -> int | None:
    return value if type(value) is int and value >= 0 else None


def note_request() -> None:
    attempt = _active_attempt.get()
    if attempt is not None:
        attempt["http_requested"] = True


def note_response(*, status: int, input_tokens=None, output_tokens=None,
                  reasoning_tokens=None, finish=None) -> None:
    attempt = _active_attempt.get()
    if attempt is None:
        return
    attempt["http_status"] = token_count(status)
    for name, value in (("input_tokens", input_tokens), ("output_tokens", output_tokens),
                        ("reasoning_tokens", reasoning_tokens)):
        if (count := token_count(value)) is not None:
            attempt[name] = count
    if finish is not None:
        # Provider strings are untrusted, even error/finish metadata.
        attempt["finish_reason"] = finish if finish in (
            "STOP", "MAX_TOKENS", "SAFETY", "RECITATION", "OTHER", "BLOCKLIST",
            "PROHIBITED_CONTENT", "SPII", "MALFORMED_FUNCTION_CALL",
            "stop", "length", "content_filter", "tool_calls", "error",
        ) else "other"


class TaskTrace:
    def __init__(self, task: str, system_chars: int, user_chars: int):
        self.started = time.perf_counter()
        self.record = {
            "id": uuid4().hex, "task": task if task in ("triage", "synthesis") else "generic",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "system_chars": system_chars, "user_chars": user_chars,
            "status": "running", "selected_model": None,
            "openrouter_entered": False, "attempts": [], "skips": [],
        }

    def attempt(self, provider: str, model: str, timeout: float) -> tuple[dict, object]:
        attempt = {
            "number": len(self.record["attempts"]) + 1, "provider": provider,
            "model": model, "timeout_seconds": round(timeout, 3),
            "status": "started", "http_requested": False,
        }
        self.record["attempts"].append(attempt)
        return attempt, _active_attempt.set(attempt)

    def restore(self, token) -> None:
        _active_attempt.reset(token)

    def skip(self, provider: str, code: str, model: str | None = None) -> None:
        self.record["skips"].append({"provider": provider, "model": model, "code": code})
        log.info("LLM task=%s provider=%s model=%s skipped=%s",
                 self.record["task"], provider, model or "-", code)

    def finish(self, status: str, model: str | None = None) -> None:
        self.record.update(status=status, selected_model=model,
                           seconds=round(time.perf_counter() - self.started, 3))
        self.record["openrouter_http_requests"] = sum(
            a["provider"] == "openrouter" and a["http_requested"]
            for a in self.record["attempts"]
        )
        _reports.append(self.record)
        log.info("LLM task=%s completed=%s selected=%s openrouter_entered=%s "
                 "openrouter_http_requests=%d",
                 self.record["task"], status, model or "none",
                 self.record["openrouter_entered"], self.record["openrouter_http_requests"])


def summary_lines() -> list[str]:
    # Import lazily to keep response observation independent of client imports.
    from ..config import GEMINI_API_KEY, OPENROUTER_API_KEY
    lines = [
        "### Diagnostika LLM / OpenRouter fallback",
        f"- Kľúč Gemini nastavený: **{'áno' if GEMINI_API_KEY else 'nie'}**; "
        f"OpenRouter: **{'áno' if OPENROUTER_API_KEY else 'nie'}** (hodnoty sa nezobrazujú).",
    ]
    if not _reports:
        return [*lines, "- V tomto behu nebola spustená žiadna LLM úloha."]
    for report in _reports:
        lines.extend([
            f"- **{report['task']}**: `{report['status']}`; "
            f"prijatý model: `{report['selected_model'] or 'žiadny'}`; "
            f"prechod na OpenRouter: **{'áno' if report['openrouter_entered'] else 'nie'}**; "
            f"HTTP požiadavky OpenRouter: **{report['openrouter_http_requests']}**.",
            "", "| Model | Výsledok | HTTP | Dôvod | Položka / pole | Čas |",
            "| --- | --- | --- | --- | --- | --- |",
        ])
        for a in report["attempts"]:
            location = f"{a.get('item_index', '—')} / {a.get('field', '—')}"
            lines.append(
                f"| {a['provider']}/{a['model']} | {a['status']} | "
                f"{a.get('http_status', '—')} | {a.get('error_code', '—')} | "
                f"{location} | {a.get('seconds', 0):.2f} s |"
            )
        for skip in report["skips"]:
            lines.append(f"- Preskočené `{skip['provider']}/{skip['model'] or '*'}`: "
                         f"`{skip['code']}`.")
        lines.append("")
    return lines


def write_report(path: str | None = None) -> bool:
    path = os.environ.get("LLM_DIAGNOSTICS_PATH", "") if path is None else path
    if not path:
        return False
    try:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        from ..config import GEMINI_API_KEY, OPENROUTER_API_KEY
        data = {
            "schema_version": 1, "recorded_at": datetime.now(timezone.utc).isoformat(),
            "keys_configured": {"gemini": bool(GEMINI_API_KEY),
                                "openrouter": bool(OPENROUTER_API_KEY)},
            "tasks": _reports,
        }
        target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except (OSError, TypeError, ValueError):
        log.warning("Diagnostický report LLM sa nepodarilo uložiť; beh pokračuje.")
        return False
