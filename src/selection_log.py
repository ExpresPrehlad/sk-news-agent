"""
Dlhodobý audit rozhodnutí LLM.

Každá úspešne parsovaná triáž a syntéza pridá jeden samostatný JSON objekt
na riadok do mesačného súboru ``data/selection_logs/YYYY-MM.jsonl``.
Log je oddelený od krátkodobého prevádzkového state.json a nikdy sa neprerezáva.

Zlyhanie auditného zápisu nesmie ovplyvniť zber, Discord ani uloženie stavu.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1


class SelectionLog:
    """Append-only auditný log pre jeden beh collectora."""

    def __init__(self, directory: str):
        self.directory = Path(directory)
        self.run_id = uuid4().hex
        self.code_revision = os.environ.get("GITHUB_SHA", "")
        self.trigger = os.environ.get("GITHUB_EVENT_NAME", "local")

    def record_triage(
        self,
        *,
        articles: list[dict],
        context_count: int,
        alerts: list,
        model: str,
        published: bool,
        decision_valid: bool,
    ) -> bool:
        selected = [
            {
                "title": alert.title,
                "reason": alert.reason,
                "links": list(alert.links),
            }
            for alert in alerts
        ]
        return self._append(
            event_type="triage",
            model=model,
            input_data={
                "article_count": len(articles),
                "context_article_count": context_count,
            },
            selected=selected,
            published=published,
            decision_valid=decision_valid,
        )

    def record_synthesis(
        self,
        *,
        articles: list[dict],
        already_featured_count: int,
        topics: list,
        model: str,
        published: bool,
        forced: bool,
    ) -> bool:
        selected = [
            {
                "headline": topic.headline,
                "perex": topic.perex,
                "links": [
                    {"source": source, "url": url}
                    for source, url in topic.links
                ],
            }
            for topic in topics
        ]
        return self._append(
            event_type="synthesis",
            model=model,
            input_data={
                "article_count": len(articles),
                "already_featured_count": already_featured_count,
                "forced": forced,
            },
            selected=selected,
            published=published,
            decision_valid=True,
        )

    def _append(
        self,
        *,
        event_type: str,
        model: str,
        input_data: dict,
        selected: list[dict],
        published: bool,
        decision_valid: bool,
    ) -> bool:
        now = datetime.now(timezone.utc)
        record = {
            "schema_version": SCHEMA_VERSION,
            "recorded_at": now.isoformat().replace("+00:00", "Z"),
            "recorded_ts": now.timestamp(),
            "run_id": self.run_id,
            "event_type": event_type,
            "model": model,
            "code_revision": self.code_revision,
            "trigger": self.trigger,
            "input": input_data,
            "selection_count": len(selected),
            "selected": selected,
            "published": published,
            "decision_valid": decision_valid,
        }
        path = self.directory / f"{now:%Y-%m}.jsonl"
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            # Jediný kompaktný zápis minimalizuje riziko polovičného riadku.
            line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
            with path.open("a", encoding="utf-8", newline="\n") as file:
                file.write(line + "\n")
            return True
        except (OSError, TypeError, ValueError):
            log.exception(
                "Auditný log %s sa nepodarilo zapísať — beh pokračuje.",
                path,
            )
            return False


def read_recent_events(directory: str, limit: int = 200) -> list[dict]:
    """Načíta najnovšie validné udalosti pre statickú auditnú stránku."""
    if limit <= 0:
        return []
    root = Path(directory)
    events: list[dict] = []
    try:
        paths = sorted(root.glob("????-??.jsonl"), reverse=True)
        for path in paths:
            file_events = []
            with path.open("r", encoding="utf-8") as file:
                for line_number, line in enumerate(file, start=1):
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        log.warning(
                            "Auditný log %s:%d obsahuje nevalidný riadok.",
                            path,
                            line_number,
                        )
                        continue
                    if isinstance(record, dict):
                        file_events.append(record)
            events.extend(reversed(file_events))
            if len(events) >= limit:
                break
    except OSError:
        log.exception("Auditné logy sa nepodarilo načítať.")
    return events[:limit]
