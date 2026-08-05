"""Deterministická kontrola čerstvosti kandidátov pre MIMORIADNE."""

from __future__ import annotations

import time
from collections.abc import Iterable
from typing import TypeVar

T = TypeVar("T")


def is_fresh_for_triage(
    published_ts: float | None,
    *,
    max_age_hours: float,
    now_ts: float | None = None,
) -> bool:
    """Neznámy čas povolí, známy čas musí byť v stanovenom okne.

    Niektoré homepage a sitemap zdroje čas publikovania neposkytujú. Tie
    nemôžeme automaticky vyradiť; proti ich opakovaniu slúži dlhšia pamäť UID.
    """
    if published_ts is None:
        return True
    try:
        published = float(published_ts)
    except (TypeError, ValueError):
        return True
    now = time.time() if now_ts is None else float(now_ts)
    return published >= now - max_age_hours * 3600


def fresh_triage_articles(
    articles: Iterable[T],
    *,
    max_age_hours: float,
    now_ts: float | None = None,
) -> list[T]:
    """Vráti iba články vhodné na posúdenie ako MIMORIADNE."""
    now = time.time() if now_ts is None else float(now_ts)
    return [
        article
        for article in articles
        if is_fresh_for_triage(
            getattr(article, "published_ts", None),
            max_age_hours=max_age_hours,
            now_ts=now,
        )
    ]
