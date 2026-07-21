"""
Sitemap kolektor — pre weby bez RSS, ktoré ponúkajú sitemap.

Dva režimy (Source.kind):
- "news_sitemap": Google News sitemap — titulok, link aj čas publikovania
  priamo v XML (napr. tnlive.sk/api/v2/sitemap-news). Ideálny prípad.
- "sitemap": klasický sitemap index → pod-sitemapy s <loc> + <lastmod>,
  ale BEZ titulkov (napr. ta3.com). Titulok sa odvodí zo slugu ako fallback
  a pre čerstvé URL sa dá obohatiť fetchom článku (viď enrich_titles —
  volá sa z main.py až PO deduplikácii, aby sme nefetchovali už videné).

Rovnaká filozofia ako rss.py: každý zdroj zlyháva izolovane, žiadna výnimka
nesmie uniknúť vyššie.
"""

from __future__ import annotations

import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests

from ..config import HTTP_TIMEOUT, USER_AGENT, Source
from .rss import Article, FetchResult

log = logging.getLogger(__name__)

_NS = {
    "sm": "http://www.sitemaps.org/schemas/sitemap/0.9",
    "news": "http://www.google.com/schemas/sitemap-news/0.9",
}

# Berieme len URL s lastmod/publication_date v tomto okne — sitemapy obsahujú
# aj roky staré články a tie nás nezaujímajú.
_FRESH_WINDOW_HOURS = 48

# Koľko pod-sitemáp z indexu maximálne otvoríme (najnovšie podľa lastmod).
_MAX_SUBSITEMAPS = 2

_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/xml, text/xml;q=0.9, */*;q=0.8",
    "Accept-Language": "sk,cs;q=0.8,en;q=0.5",
}


def _get(url: str) -> bytes:
    resp = requests.get(url, timeout=HTTP_TIMEOUT, headers=_HEADERS)
    resp.raise_for_status()
    return resp.content


def _parse_ts(value: str | None) -> float | None:
    """ISO 8601 (s 'Z' aj offsetom) → unix ts. Toleruje aj čisté dátumy."""
    if not value:
        return None
    value = value.strip()
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        pass
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").replace(
            tzinfo=timezone.utc
        ).timestamp()
    except ValueError:
        return None


def _uid(source_id: str, link: str) -> str:
    import hashlib
    return hashlib.sha256(f"{source_id}:{link}".encode("utf-8")).hexdigest()[:20]


def _slug_to_title(link: str) -> str:
    """Núdzový titulok zo slugu URL: '.../padla-vlada-123456' → 'Padla vlada'."""
    slug = link.rstrip("/").rsplit("/", 1)[-1]
    slug = re.sub(r"\.(html?|php)$", "", slug)
    slug = re.sub(r"[-_]?\d{4,}$", "", slug)  # odrež ID článku na konci
    words = slug.replace("-", " ").replace("_", " ").strip()
    return words[:1].upper() + words[1:] if words else link


# ---------------------------------------------------------------------------
# Režim "news_sitemap" — všetko priamo v XML
# ---------------------------------------------------------------------------

def fetch_news_sitemap(source: Source) -> FetchResult:
    try:
        root = ET.fromstring(_get(source.feed_url))
    except (requests.RequestException, ET.ParseError) as exc:
        log.warning("News sitemap %s zlyhal: %s", source.id, exc)
        return FetchResult(source=source, articles=[], error=str(exc))

    cutoff = time.time() - _FRESH_WINDOW_HOURS * 3600
    articles: list[Article] = []
    for url_el in root.findall("sm:url", _NS):
        link = (url_el.findtext("sm:loc", default="", namespaces=_NS) or "").strip()
        title = (url_el.findtext("news:news/news:title", default="", namespaces=_NS) or "").strip()
        ts = _parse_ts(url_el.findtext("news:news/news:publication_date", default=None, namespaces=_NS))
        if not link or not title:
            continue
        if ts is not None and ts < cutoff:
            continue
        articles.append(
            Article(
                uid=_uid(source.id, link),
                source_id=source.id,
                source_name=source.name,
                title=title,
                summary="",
                link=link,
                published_ts=ts,
            )
        )
    return FetchResult(source=source, articles=articles)


# ---------------------------------------------------------------------------
# Režim "sitemap" — index → pod-sitemapy, titulky zo slugov
# ---------------------------------------------------------------------------

def fetch_plain_sitemap(source: Source) -> FetchResult:
    try:
        root = ET.fromstring(_get(source.feed_url))
    except (requests.RequestException, ET.ParseError) as exc:
        log.warning("Sitemap %s zlyhal: %s", source.id, exc)
        return FetchResult(source=source, articles=[], error=str(exc))

    cutoff = time.time() - _FRESH_WINDOW_HOURS * 3600

    # Ak je to index, vyber pod-sitemapy s najnovším lastmod.
    subsitemaps: list[tuple[float, str]] = []
    if root.tag.endswith("sitemapindex"):
        for sm_el in root.findall("sm:sitemap", _NS):
            loc = (sm_el.findtext("sm:loc", default="", namespaces=_NS) or "").strip()
            ts = _parse_ts(sm_el.findtext("sm:lastmod", default=None, namespaces=_NS)) or 0.0
            if loc:
                subsitemaps.append((ts, loc))
        subsitemaps.sort(reverse=True)
        roots = []
        for _, loc in subsitemaps[:_MAX_SUBSITEMAPS]:
            try:
                roots.append(ET.fromstring(_get(loc)))
            except (requests.RequestException, ET.ParseError) as exc:
                log.warning("Pod-sitemap %s zlyhala: %s", loc, exc)
        if not roots:
            return FetchResult(source=source, articles=[], error="žiadna pod-sitemap sa nedala načítať")
    else:
        roots = [root]

    articles: list[Article] = []
    for r in roots:
        for url_el in r.findall("sm:url", _NS):
            link = (url_el.findtext("sm:loc", default="", namespaces=_NS) or "").strip()
            ts = _parse_ts(url_el.findtext("sm:lastmod", default=None, namespaces=_NS))
            if not link:
                continue
            if ts is None or ts < cutoff:
                continue  # bez času nevieme posúdiť čerstvosť — preskoč
            articles.append(
                Article(
                    uid=_uid(source.id, link),
                    source_id=source.id,
                    source_name=source.name,
                    title=_slug_to_title(link),
                    summary="",
                    link=link,
                    published_ts=ts,
                )
            )
    return FetchResult(source=source, articles=articles)


# ---------------------------------------------------------------------------
# Obohatenie titulkov fetchom článku (volá main.py LEN pre nové články)
# ---------------------------------------------------------------------------

_TITLE_RE = re.compile(
    r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']'
    r'|<title[^>]*>([^<]+)</title>',
    re.IGNORECASE,
)

# Poistka: max fetchov článkov na jeden beh (nech beh netrvá minúty).
MAX_TITLE_FETCHES_PER_RUN = 12


def enrich_titles(articles: list[Article]) -> list[Article]:
    """
    Pre články so slug-titulkom skúsi stiahnuť stránku a vytiahnuť skutočný
    titulok (og:title alebo <title>). Neúspech necháva slug verziu — nikdy
    nezlyháva. Vracia NOVÝ zoznam (Article je frozen).
    """
    out: list[Article] = []
    fetched = 0
    for a in articles:
        if fetched >= MAX_TITLE_FETCHES_PER_RUN:
            out.append(a)
            continue
        try:
            html = _get(a.link).decode("utf-8", errors="replace")
            fetched += 1
            m = _TITLE_RE.search(html)
            title = (m.group(1) or m.group(2)).strip() if m else ""
            # odrež " | TA3", " - ta3.com" a podobné prípony webu
            title = re.split(r"\s+[|\-–]\s+(?:ta3|TA3)[^|]*$", title)[0].strip()
            if title:
                a = Article(
                    uid=a.uid, source_id=a.source_id, source_name=a.source_name,
                    title=title[:300], summary=a.summary, link=a.link,
                    published_ts=a.published_ts,
                )
        except requests.RequestException as exc:
            log.debug("Obohatenie titulku %s zlyhalo: %s", a.link, exc)
        out.append(a)
    return out
