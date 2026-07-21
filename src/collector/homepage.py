"""
Homepage kolektor — pre weby bez RSS aj bez funkčného sitemapu, ktoré ale
serverovo renderujú titulnú stránku s odkazmi na články (napr. noviny.sk).

Princíp: stiahni homepage HTML, regexom vyber článkové URL podľa vzoru
zdroja, titulky nechaj na enrichment (og:title fetch v main.py — rovnaká
cesta ako ta3/hn sitemap zdroje). Žiadna enumerácia ID — berú sa výhradne
odkazy, ktoré stránka sama zverejnila.

Čas publikácie pri prvom objavení nie je známy (published_ts=None) —
článok sa považuje za nový v momente, keď sa prvýkrát objaví na titulke,
čo je pre redakčný monitoring presne ten správny signál.
"""

from __future__ import annotations

import hashlib
import logging
import re

import requests

from ..config import HTTP_TIMEOUT, USER_AGENT, Source
from .rss import Article, FetchResult

log = logging.getLogger(__name__)

# Vzory článkových URL podľa zdroja. Kľúč = Source.id.
# noviny.sk: /<rubrika>/<číselné-id>-<slug>
_URL_PATTERNS: dict[str, re.Pattern] = {
    "noviny": re.compile(
        r'href="(https?://(?:www\.)?noviny\.sk/[a-z0-9-]+/\d{4,}-[a-z0-9-]+)"',
        re.IGNORECASE,
    ),
}

# Poistka proti anomálii (rozbitá stránka plná odkazov a pod.)
_MAX_LINKS_PER_FETCH = 60


def fetch_homepage(source: Source) -> FetchResult:
    """Stiahne homepage a vyberie článkové odkazy. Nikdy nevyhadzuje výnimku."""
    pattern = _URL_PATTERNS.get(source.id)
    if pattern is None:
        return FetchResult(
            source=source, articles=[],
            error=f"chýba URL vzor pre homepage zdroj '{source.id}'",
        )

    try:
        resp = requests.get(
            source.feed_url,
            timeout=HTTP_TIMEOUT,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "sk,cs;q=0.8,en;q=0.5",
            },
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.warning("Homepage %s zlyhala: %s", source.id, exc)
        return FetchResult(source=source, articles=[], error=f"HTTP: {exc}")

    if resp.headers.get("cf-mitigated", "").lower() == "challenge":
        return FetchResult(source=source, articles=[], error="Cloudflare challenge")

    html = resp.text
    seen_links: set[str] = set()
    articles: list[Article] = []
    for m in pattern.finditer(html):
        link = m.group(1)
        if link in seen_links:
            continue
        seen_links.add(link)
        if len(articles) >= _MAX_LINKS_PER_FETCH:
            break
        uid = hashlib.sha256(f"{source.id}:{link}".encode("utf-8")).hexdigest()[:20]
        # Titulok zatiaľ zo slugu — skutočný doplní enrichment v main.py.
        slug = link.rstrip("/").rsplit("/", 1)[-1]
        slug = re.sub(r"^\d+-", "", slug)
        title = slug.replace("-", " ").strip()
        title = title[:1].upper() + title[1:] if title else link
        articles.append(
            Article(
                uid=uid,
                source_id=source.id,
                source_name=source.name,
                title=title,
                summary="",
                link=link,
                published_ts=None,
            )
        )

    if not articles:
        return FetchResult(
            source=source, articles=[],
            error="homepage sa načítala, ale nenašli sa žiadne článkové odkazy "
                  "(zmena štruktúry stránky?)",
        )
    return FetchResult(source=source, articles=articles)
