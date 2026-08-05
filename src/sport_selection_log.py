"""Append-only história lokálneho prioritizovania športových správ."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from .sport_page import (
    _GLOBAL_EVENT_SIGNAL,
    _LOW_SIGNAL,
    _SLOVAK_SIGNAL,
    _is_featured,
    _priority,
)

log = logging.getLogger(__name__)
SCHEMA_VERSION = 1


def _reasons(title: str, perex: str) -> list[str]:
    text = f"{title} {perex}".lower()
    reasons: list[str] = []
    if any(signal in text for signal in _SLOVAK_SIGNAL):
        reasons.append("slovenská väzba alebo udalosť na Slovensku")
    if "rekord" in text:
        reasons.append("rekord")
    if any(signal in text for signal in _GLOBAL_EVENT_SIGNAL):
        reasons.append("globálne sledované podujatie")
    if any(signal in text for signal in _LOW_SIGNAL):
        reasons.append("pracovný formát s nižšou prioritou")
    return reasons or ["bežná správa v Šport Radare"]


class SportSelectionLog:
    """Ukladá jeden záznam pre každú novú športovú správu."""

    def __init__(self, directory: str):
        self.directory = Path(directory)

    def record_articles(self, articles: list) -> bool:
        if not articles:
            return True
        now = datetime.now(timezone.utc)
        records = []
        for article in articles:
            title = str(article.title or "")[:500]
            perex = str(article.summary or "")[:600]
            selected = _is_featured({"t": title, "p": perex})
            records.append({
                "schema_version": SCHEMA_VERSION,
                "recorded_at": now.isoformat().replace("+00:00", "Z"),
                "recorded_ts": now.timestamp(),
                "source": str(article.source_name or "")[:100],
                "title": title,
                "perex": perex,
                "link": str(article.link or "")[:1200],
                "score": _priority({"t": title, "p": perex}),
                "category": "redakcny_vyber" if selected else "sport_radar",
                "reasons": _reasons(title, perex),
            })
        path = self.directory / f"{now:%Y-%m}.jsonl"
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8", newline="\n") as handle:
                for record in records:
                    handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            return True
        except (OSError, TypeError, ValueError):
            log.exception("Športový audit %s sa nepodarilo zapísať — beh pokračuje.", path)
            return False


def read_recent_sport_events(directory: str, limit: int = 1000) -> list[dict]:
    """Načíta najnovšie záznamy, newest-first, pre statickú auditnú stránku."""
    if limit <= 0:
        return []
    root = Path(directory)
    events: list[dict] = []
    try:
        for path in sorted(root.glob("????-??.jsonl"), reverse=True):
            with path.open("r", encoding="utf-8") as handle:
                file_events = []
                for line in handle:
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(record, dict):
                        file_events.append(record)
            events.extend(reversed(file_events))
            if len(events) >= limit:
                break
    except OSError:
        log.exception("Športové auditné logy sa nepodarilo načítať.")
    return events[:limit]
