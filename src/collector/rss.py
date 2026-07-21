"""
RSS collector.

Princípy:
- Každý zdroj zlyháva izolovane: chyba jedného feedu nezhodí beh, len sa
  zaznamená do výsledku (aby ju bolo vidieť v logoch aj v health checku).
- Feed sťahujeme sami cez requests (timeout, vlastný User-Agent) a feedparseru
  dávame už stiahnutý obsah — feedparser sám o sebe timeout nepodporuje.
- Výstupom je jednotný zoznam Article bez ohľadu na formát feedu (RSS/Atom).
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass

import feedparser
import requests

from ..config import HTTP_TIMEOUT, USER_AGENT, Source

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Article:
    uid: str          # stabilný hash na deduplikáciu
    source_id: str
    source_name: str
    title: str
    summary: str      # perex (môže byť prázdny)
    link: str
    published_ts: float | None  # unix timestamp, ak ho feed uvádza


@dataclass
class FetchResult:
    source: Source
    articles: list[Article]
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def _make_uid(source_id: str, entry) -> str:
    """
    Stabilný identifikátor článku. Preferujeme guid/id z feedu, fallback je
    link, posledná záchrana titulok. Hashujeme, aby stav ostal kompaktný.
    """
    raw = entry.get("id") or entry.get("link") or entry.get("title") or ""
    return hashlib.sha256(f"{source_id}:{raw}".encode("utf-8")).hexdigest()[:20]


def _entry_timestamp(entry) -> float | None:
    for key in ("published_parsed", "updated_parsed"):
        parsed = entry.get(key)
        if parsed:
            try:
                return time.mktime(parsed)
            except (ValueError, OverflowError):
                continue
    return None


def _clean(text: str | None) -> str:
    """Ochrana proti HTML zvyškom a whitespace šumu v titulkoch/perexoch."""
    if not text:
        return ""
    # feedparser HTML väčšinou odstráni sám; toto je lacná druhá línia.
    import re
    text = re.sub(r"<[^>]+>", "", text)
    return " ".join(text.split()).strip()


def fetch_source(source: Source) -> FetchResult:
    """Stiahne a naparsuje jeden zdroj. Nikdy nevyhadzuje výnimku."""
    try:
        resp = requests.get(
            source.feed_url,
            timeout=HTTP_TIMEOUT,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
                "Accept-Language": "sk,cs;q=0.8,en;q=0.5",
            },
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.warning("Feed %s zlyhal: %s", source.id, exc)
        return FetchResult(source=source, articles=[], error=f"HTTP: {exc}")

    parsed = feedparser.parse(resp.content)
    if parsed.bozo and not parsed.entries:
        # bozo=True s nulou entries = feed je reálne rozbitý, nie len "škaredý"
        err = str(getattr(parsed, "bozo_exception", "neznáma chyba parsovania"))
        log.warning("Feed %s sa nedá parsovať: %s", source.id, err)
        return FetchResult(source=source, articles=[], error=f"parse: {err}")

    articles: list[Article] = []
    for entry in parsed.entries:
        title = _clean(entry.get("title"))
        link = (entry.get("link") or "").strip()
        if not title or not link:
            continue  # bez titulku alebo linku je položka pre redakciu bezcenná
        articles.append(
            Article(
                uid=_make_uid(source.id, entry),
                source_id=source.id,
                source_name=source.name,
                title=title,
                summary=_clean(entry.get("summary") or entry.get("description")),
                link=link,
                published_ts=_entry_timestamp(entry),
            )
        )

    return FetchResult(source=source, articles=articles)


def fetch_all(sources: list[Source]) -> list[FetchResult]:
    """
    Sekvenčne stiahne všetky zapnuté zdroje, dispatch podľa Source.kind.
    Import sitemap modulu je vnútri funkcie kvôli kruhovej závislosti
    (sitemap.py importuje Article/FetchResult odtiaľto).
    """
    from .sitemap import fetch_news_sitemap, fetch_plain_sitemap

    dispatch = {
        "rss": fetch_source,
        "news_sitemap": fetch_news_sitemap,
        "sitemap": fetch_plain_sitemap,
    }
    results: list[FetchResult] = []
    for s in sources:
        if not s.enabled:
            continue
        fn = dispatch.get(s.kind)
        if fn is None:
            log.error("Neznámy kind '%s' pre zdroj %s — preskakujem.", s.kind, s.id)
            continue
        results.append(fn(s))
    return results
