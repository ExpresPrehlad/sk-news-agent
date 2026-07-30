"""
Generátor statickej stránky pre GitHub Pages (docs/index.html).

Prečo statický HTML a nie API/JS aplikácia: 0 € rozpočet, žiadny build krok,
žiadny ďalší hosting — súbor sa vygeneruje pri každom behu a GitHub Pages ho
servíruje priamo z /docs na main vetve. Číta sa výhradne z State (perzistuje
sa aj medzi behmi, keď sa syntéza/triáž nespúšťala), takže stránka je vždy
aktuálna k poslednému behu, nie len k poslednému behu s LLM aktivitou.

Bezpečnosť: všetok text z článkov/titulkov ide cez html.escape() — sú to
dáta z externých RSS/sitemap zdrojov, nie dôveryhodný vstup.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from html import escape
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from .config import ACTIVE_HOURS_TZ

_OUTPUT_PATH = "docs/index.html"
_VERSION_PATH = "docs/version.json"

_REFRESH_SECONDS = 600  # záložný reload; nový obsah zachytí ľahší version polling
_UPDATE_CHECK_MS = 60_000
_LOCAL_TZ = ZoneInfo(ACTIVE_HOURS_TZ)


def _fmt_time(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(_LOCAL_TZ).strftime("%H:%M · %d.%m.%Y")


def _ago(ts: float) -> str:
    mins = int((datetime.now(timezone.utc).timestamp() - ts) / 60)
    if mins < 1:
        return "práve teraz"
    if mins < 60:
        return f"pred {mins} min"
    hours = mins // 60
    return f"pred {hours} h {mins % 60} min" if mins % 60 else f"pred {hours} h"


def _safe_http_url(value: object) -> str:
    """Vráti bezpečnú http(s) URL alebo prázdny reťazec."""
    url = str(value or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return url


def _render_alert_item(alert: dict) -> str:
    content = (
        f'<span class="flash-copy">'
        f'<span class="flash-title">{escape(str(alert.get("title", "")))}</span>'
        f'<span class="flash-reason">{escape(str(alert.get("reason", "")))}</span>'
        f"</span>"
    )
    links = alert.get("links")
    first_link = links[0] if isinstance(links, list) and links else ""
    url = _safe_http_url(first_link)
    if url:
        return (
            f'<a class="flash-item" href="{escape(url, quote=True)}" '
            f'target="_blank" rel="noopener">{content}'
            f'<span class="flash-cta">Otvoriť zdroj <span aria-hidden="true">→</span></span></a>'
        )
    return f'<div class="flash-item">{content}</div>'


def _render_alert_flash(alerts: list[dict]) -> str:
    if not alerts:
        return ""
    items = "".join(
        _render_alert_item(alert)
        for alert in alerts
    )
    return (
        f'<section class="wire-flash" aria-labelledby="flash-heading">'
        f'<div class="flash-inner"><div class="flash-label" id="flash-heading">'
        f'<span class="flash-dot" aria-hidden="true"></span>Mimoriadne</div>'
        f'<div class="flash-list">{items}</div></div></section>'
    )


def _render_topics(digest: dict) -> str:
    if not digest or not digest.get("topics"):
        return (
            '<div class="empty">Zatiaľ žiadny prehľad — prvá syntéza prebehne '
            "čoskoro po nazbieraní dostatku článkov.</div>"
        )
    topics = digest["topics"]
    ts = digest.get("ts", 0)
    cards = []
    for i, t in enumerate(topics[:5], start=1):
        safe_links = [
            (str(source), safe_url)
            for source, url in t.get("links", [])[:2]
            if (safe_url := _safe_http_url(url))
        ]
        links = "".join(
            f'<a href="{escape(url, quote=True)}" target="_blank" rel="noopener">'
            f'{escape(source)} <span aria-hidden="true">→</span></a>'
            for source, url in safe_links
        )
        headline = escape(str(t["headline"]))
        if safe_links:
            headline = (
                f'<a href="{escape(safe_links[0][1], quote=True)}" '
                f'target="_blank" rel="noopener">{headline}</a>'
            )
        topic_class = "topic topic-lead" if i == 1 else "topic topic-secondary"
        cards.append(
            f'<article class="{topic_class}">'
            f'<div class="topic-rank">{i:02d}</div>'
            f'<div class="topic-body">'
            f'<h3>{headline}</h3>'
            f'<p>{escape(t["perex"])}</p>'
            f'<div class="topic-links">{links}</div>'
            f"</div></article>"
        )
    meta = f'<div class="section-meta">Aktualizované {_ago(ts)}</div>'
    return meta + '<div class="topics-board">' + "".join(cards) + "</div>"


def _render_feed_item(a: dict, index: int) -> str:
    source = str(a.get("s", "?"))
    url = _safe_http_url(a.get("l"))
    title = escape(str(a.get("t", "")))
    if url:
        title = (
            f'<a href="{escape(url, quote=True)}" target="_blank" rel="noopener">'
            f"{title}</a>"
        )
    local_time = datetime.fromtimestamp(
        float(a.get("ts", 0)), tz=timezone.utc
    ).astimezone(_LOCAL_TZ).strftime("%H:%M")
    return (
        f'<li class="radar-row" data-source="{escape(source, quote=True)}" '
        f'data-radar-index="{index}">'
        f'<time datetime="{escape(datetime.fromtimestamp(float(a.get("ts", 0)), tz=timezone.utc).isoformat(), quote=True)}">'
        f"{local_time}</time>"
        f'<span class="radar-source">{escape(source)}</span>'
        f'<span class="radar-title">{title}</span>'
        f'<span class="radar-age">{_ago(float(a.get("ts", 0)))}</span></li>'
    )


def _render_raw_feed(articles: list[dict]) -> str:
    if not articles:
        return '<div class="empty">Zatiaľ žiadne články v okne posledných hodín.</div>'
    sorted_articles = sorted(
        articles, key=lambda item: -float(item.get("ts", 0))
    )
    source_counts: dict[str, int] = {}
    for article in sorted_articles:
        source = str(article.get("s", "?"))
        source_counts[source] = source_counts.get(source, 0) + 1
    filters = [
        '<button class="radar-filter is-active" type="button" data-filter="all" '
        'aria-pressed="true">Všetky</button>'
    ]
    filters.extend(
        f'<button class="radar-filter" type="button" '
        f'data-filter="{escape(source, quote=True)}" aria-pressed="false">'
        f'{escape(source)} <span>{count}</span></button>'
        for source, count in sorted(source_counts.items())
    )
    rows = "".join(
        _render_feed_item(article, index)
        for index, article in enumerate(sorted_articles)
    )
    return (
        f'<div class="radar-filters" aria-label="Filtrovať podľa zdroja">'
        f'{"".join(filters)}</div>'
        f'<ol class="radar-list">{rows}</ol>'
        f'<button class="radar-more" type="button">Zobraziť ďalšie správy</button>'
        f'<div class="radar-empty" hidden>Pre tento zdroj nie sú v okne žiadne správy.</div>'
    )


def _render_sources(status: dict) -> str:
    if not status:
        return ""
    pills = []
    for s in sorted(status.values(), key=lambda x: x.get("name", "")):
        ok = s.get("ok", True)
        cls = "pill-ok" if ok else "pill-fail"
        title = escape(s.get("error") or "OK")
        pills.append(
            f'<span class="pill {cls}" title="{title}">{escape(s.get("name", "?"))}</span>'
        )
    return "".join(pills)


_CSS = """
:root {
  --canvas: #F4F6F8;
  --surface: #FFFFFF;
  --surface-soft: #F8FAFC;
  --text: #172033;
  --muted: #667085;
  --amber: #A85F00;
  --amber-soft: #FFF4E5;
  --red: #B42318;
  --red-soft: #FFF1F0;
  --red-rule: #F2B8B5;
  --rule: #E2E6EA;
  --rule-strong: #D0D5DD;
  --success: #277443;
  --shadow: 0 1px 2px rgba(16, 24, 40, 0.04), 0 5px 18px rgba(16, 24, 40, 0.04);
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0; background: var(--canvas); color: var(--text);
  font-family: "IBM Plex Sans", -apple-system, sans-serif;
  line-height: 1.55;
  -webkit-font-smoothing: antialiased;
}
.mono { font-family: "IBM Plex Mono", ui-monospace, monospace; }
a { color: var(--amber); text-decoration: none; }
a:hover, a:focus-visible { text-decoration: underline; }
a:focus-visible, summary:focus-visible {
  outline: 3px solid rgba(168, 95, 0, 0.28); outline-offset: 3px; border-radius: 3px;
}

.wire-flash {
  background: var(--red-soft);
  border-top: 1px solid var(--red-rule);
  border-bottom: 1px solid var(--red-rule);
}
.flash-inner {
  max-width: 1320px;
  margin: 0 auto;
  padding: 18px 28px 20px;
}
.flash-label {
  display: flex; align-items: center; gap: 8px;
  font-family: "IBM Plex Mono", monospace; font-size: 12px; letter-spacing: 0.12em;
  text-transform: uppercase; color: var(--red); font-weight: 700; margin-bottom: 8px;
}
.flash-dot {
  width: 8px; height: 8px; border-radius: 50%; background: var(--red);
  box-shadow: 0 0 0 4px rgba(180, 35, 24, 0.10);
}
.flash-item {
  display: grid; grid-template-columns: minmax(0, 1fr) auto;
  align-items: center; gap: 24px; padding: 9px 0; color: inherit;
}
.flash-item + .flash-item { border-top: 1px solid rgba(180, 35, 24, 0.14); }
.flash-copy { display: block; min-width: 0; }
.flash-title {
  display: block; color: var(--text); font-size: 16px; font-weight: 600;
  line-height: 1.4;
}
.flash-item:hover, .flash-item:focus-visible { text-decoration: none; }
.flash-item:hover .flash-title, .flash-item:focus-visible .flash-title {
  color: var(--red); text-decoration: underline;
}
.flash-reason {
  display: block; color: var(--muted); font-size: 13.5px; margin-top: 3px;
  max-width: 950px;
}
.flash-cta {
  color: var(--red); font-size: 13px; font-weight: 600; white-space: nowrap;
}

.site-header {
  background: rgba(255, 255, 255, 0.96);
  border-bottom: 1px solid var(--rule);
}
.header-inner {
  max-width: 1320px; margin: 0 auto; padding: 20px 28px 0;
}
.brand-row {
  display: flex; justify-content: space-between; align-items: baseline;
  flex-wrap: wrap; gap: 10px 24px;
}
.masthead {
  font-size: 19px; font-weight: 600; letter-spacing: -0.02em; color: var(--text);
}
.masthead b {
  color: var(--amber); font-weight: 500; margin-left: 8px;
  padding-left: 10px; border-left: 1px solid var(--rule-strong);
}
.updated { font-family: "IBM Plex Mono", monospace; font-size: 12px; color: var(--muted); }
.updated .stale-warning { color: var(--red); font-weight: 700; }
nav { display: flex; gap: 28px; margin-top: 15px; }
nav a {
  display: inline-flex; align-items: center; min-height: 40px;
  color: var(--muted); font-size: 13.5px; font-weight: 500;
  border-bottom: 2px solid transparent;
}
nav a:hover, nav a:focus-visible {
  color: var(--text); border-bottom-color: var(--amber); text-decoration: none;
}

main {
  max-width: 1320px; margin: 0 auto; padding: 34px 28px 44px;
  display: grid; grid-template-columns: minmax(0, 1.65fr) minmax(320px, 0.95fr);
  align-items: start; gap: 32px;
}
section, aside { scroll-margin-top: 20px; }
.section-heading {
  display: flex; justify-content: space-between; align-items: end; margin-bottom: 5px;
}
.eyebrow {
  color: var(--amber); font-family: "IBM Plex Mono", monospace;
  font-size: 11px; font-weight: 700; letter-spacing: 0.11em; text-transform: uppercase;
  margin-bottom: 2px;
}
h2 {
  color: var(--text); font-size: 25px; line-height: 1.25; letter-spacing: -0.025em;
  margin: 0; font-weight: 600;
}
.section-meta { font-size: 12.5px; color: var(--muted); margin: 0 0 16px; }

.topic {
  display: flex; gap: 17px; background: var(--surface); border-radius: 10px;
  padding: 20px 22px; margin-bottom: 14px; border: 1px solid var(--rule);
  box-shadow: var(--shadow); transition: border-color 150ms ease, transform 150ms ease;
}
.topic:hover { border-color: #C7CDD4; transform: translateY(-1px); }
.topic-rank {
  display: flex; align-items: center; justify-content: center; flex: 0 0 42px;
  width: 42px; height: 34px; border-radius: 7px; background: var(--amber-soft);
  font-family: "IBM Plex Mono", monospace; color: var(--amber);
  font-size: 15px; font-weight: 700;
}
.topic-body { min-width: 0; }
.topic h3 {
  margin: 0 0 7px; font-size: 18px; line-height: 1.4; letter-spacing: -0.012em;
}
.topic p {
  margin: 0 0 11px; color: #475467; font-size: 14.5px; line-height: 1.55;
  max-width: 72ch;
}
.topic-links { display: flex; flex-wrap: wrap; gap: 7px; }
.topic-links a {
  display: inline-flex; align-items: center; min-height: 27px;
  padding: 2px 8px; border-radius: 999px; background: var(--amber-soft);
  font-size: 11px; font-weight: 600; font-family: "IBM Plex Mono", monospace;
}
.topic-links a:hover, .topic-links a:focus-visible { text-decoration: none; background: #FDE8C8; }

.feed-panel {
  background: var(--surface); border: 1px solid var(--rule); border-radius: 10px;
  padding: 20px 20px 12px; box-shadow: var(--shadow);
}
.feed-panel .section-heading { margin-bottom: 20px; }
.feed-panel h2 { font-size: 21px; }
.feed-group { margin-bottom: 22px; }
.feed-group h4 {
  display: flex; align-items: center; gap: 8px;
  font-size: 12px; color: var(--muted); margin: 0 0 7px;
  font-family: "IBM Plex Mono", monospace; text-transform: uppercase; letter-spacing: 0.06em;
}
.feed-group .count { color: var(--amber); }
.feed-group ul { list-style: none; margin: 0; padding: 0; border-top: 1px solid var(--rule); }
.feed-group li {
  padding: 9px 0; display: grid; grid-template-columns: minmax(0, 1fr) auto;
  align-items: start; gap: 12px; font-size: 13.5px; border-bottom: 1px solid var(--rule);
}
.feed-group li a { color: var(--text); }
.feed-group li a:hover, .feed-group li a:focus-visible { color: var(--amber); }
.feed-group .ts { color: var(--muted); font-size: 11px; white-space: nowrap; }

.feed-more { margin-top: 2px; }
.feed-more summary {
  cursor: pointer; list-style: none; font-family: "IBM Plex Mono", monospace;
  font-size: 11.5px; color: var(--amber); padding: 9px 0; user-select: none;
}
.feed-more summary::-webkit-details-marker { display: none; }
.feed-more summary::marker { content: ""; }
.feed-more[open] summary { color: var(--muted); }

.empty { color: var(--muted); font-size: 13.5px; font-style: italic; }

footer {
  background: var(--surface); padding: 22px max(28px, calc((100% - 1264px) / 2)) 34px;
  border-top: 1px solid var(--rule); display: flex; flex-wrap: wrap;
  align-items: center; gap: 10px;
}
.pill { font-family: "IBM Plex Mono", monospace; font-size: 11px; padding: 4px 9px;
  border-radius: 999px; border: 1px solid var(--rule); }
.pill-ok { color: var(--success); border-color: #A9D6B8; background: #F0FAF3; }
.pill-fail { color: var(--red); border-color: var(--red-rule); background: var(--red-soft); }
.footer-note { font-size: 11.5px; color: var(--muted); margin-left: auto;
  font-family: "IBM Plex Mono", monospace; }
.footer-link { font-size: 11.5px; font-family: "IBM Plex Mono", monospace; }

@media (max-width: 920px) {
  main { grid-template-columns: 1fr; }
  .feed-panel { margin-top: 4px; }
}
@media (max-width: 640px) {
  .header-inner { padding: 16px 18px 0; }
  .brand-row { display: block; }
  .updated { margin-top: 5px; font-size: 10.5px; }
  nav { gap: 19px; margin-top: 12px; overflow-x: auto; }
  nav a { white-space: nowrap; min-height: 42px; font-size: 12.5px; }
  .flash-inner { padding: 15px 18px 17px; }
  .flash-item { grid-template-columns: 1fr; gap: 7px; }
  .flash-title { font-size: 15px; }
  .flash-cta { justify-self: start; }
  main { padding: 25px 16px 34px; gap: 24px; }
  h2 { font-size: 23px; }
  .topic { gap: 12px; padding: 16px; }
  .topic-rank { flex-basis: 36px; width: 36px; height: 30px; font-size: 13px; }
  .topic h3 { font-size: 16.5px; }
  .topic p { font-size: 14px; }
  .feed-panel { padding: 18px 16px 8px; }
  .feed-group li { grid-template-columns: 1fr; gap: 3px; }
  .feed-group .ts { font-size: 10.5px; }
  footer { padding: 20px 18px 30px; }
  .footer-note { width: 100%; margin-left: 0; }
}

/* News Briefing v2 ------------------------------------------------------ */
:root {
  --canvas: #FAF9F6;
  --surface: #FFFFFF;
  --surface-soft: #F2F5F8;
  --text: #102033;
  --navy: #0B1F33;
  --navy-soft: #173651;
  --muted: #64748B;
  --blue: #2563EB;
  --blue-soft: #EAF1FF;
  --red: #D7263D;
  --red-dark: #A91328;
  --red-soft: #FFF4F5;
  --red-rule: #F1C3C9;
  --rule: #DCE2E8;
  --rule-strong: #C8D0D9;
  --success: #277443;
  --shadow: none;
}
body { background: var(--canvas); color: var(--text); line-height: 1.45; }
a { color: var(--blue); }
a:focus-visible, button:focus-visible, summary:focus-visible {
  outline: 3px solid rgba(37, 99, 235, 0.28); outline-offset: 3px;
}

.site-header { background: var(--navy); border: 0; color: #FFFFFF; }
.header-inner {
  max-width: 1380px; min-height: 64px; margin: 0 auto; padding: 0 30px;
  display: grid; grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center; gap: 38px;
}
.masthead {
  color: #FFFFFF; font-family: "Newsreader", Georgia, serif;
  font-size: 23px; font-weight: 700; letter-spacing: -0.025em; white-space: nowrap;
}
.masthead b {
  color: #9EC1FF; border-left-color: rgba(255, 255, 255, 0.28);
  font-family: "IBM Plex Sans", sans-serif; font-size: 13px; font-weight: 500;
  letter-spacing: 0.02em; text-transform: uppercase;
}
.updated { color: #AFC0D2; font-size: 11.5px; white-space: nowrap; }
.updated .stale-warning { color: #FF8D9A; }
nav { margin: 0; gap: 6px; }
nav a {
  min-height: 64px; padding: 0 13px; color: #D7E2EC; font-size: 14px;
  border-bottom: 3px solid transparent;
}
nav a:hover, nav a:focus-visible {
  color: #FFFFFF; border-bottom-color: #78A7FF; text-decoration: none;
}

.wire-flash { background: #FFFFFF; border: 0; border-bottom: 1px solid var(--red-rule); }
.flash-inner {
  max-width: 1380px; margin: 0 auto; padding: 10px 30px;
  display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 20px; align-items: stretch;
}
.flash-label {
  margin: 0; padding: 7px 18px 7px 0; border-right: 1px solid var(--red-rule);
  align-self: center; color: var(--red); font-size: 11.5px;
}
.flash-dot { width: 7px; height: 7px; background: var(--red); }
.flash-list {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(390px, 1fr));
  gap: 0 22px; min-width: 0;
}
.flash-item {
  display: grid; grid-template-columns: minmax(0, 1fr) auto;
  gap: 14px; padding: 6px 0; min-height: 61px;
}
.flash-item + .flash-item { border-top: 0; }
.flash-title {
  display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2;
  overflow: hidden; font-size: 15px; line-height: 1.3;
}
.flash-reason {
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  margin-top: 1px; font-size: 12.5px;
}
.flash-cta { color: var(--red); font-size: 12.5px; }
.flash-item:hover .flash-title, .flash-item:focus-visible .flash-title { color: var(--red); }

main { max-width: 1380px; margin: 0 auto; padding: 22px 30px 42px; display: block; }
.section-heading { margin: 0; }
.eyebrow {
  color: var(--blue); font-size: 11px; letter-spacing: 0.14em; margin-bottom: 0;
}
h2 {
  font-family: "Newsreader", Georgia, serif; font-size: 29px; font-weight: 700;
  letter-spacing: -0.025em;
}
.section-meta { margin: 2px 0 10px; font-size: 12.5px; }

.topics-board {
  min-height: 400px; display: grid;
  grid-template-columns: minmax(360px, 0.9fr) minmax(520px, 1.35fr);
  grid-template-rows: repeat(4, minmax(91px, auto));
  background: var(--surface); border: 1px solid var(--rule-strong);
}
.topic { margin: 0; border: 0; border-radius: 0; box-shadow: none; transform: none; }
.topic:hover { border-color: inherit; transform: none; }
.topic-rank {
  background: transparent; border-radius: 0; width: auto; height: auto;
  align-items: flex-start; justify-content: flex-start; color: var(--blue);
  font-size: 13px; line-height: 1.4;
}
.topic h3 {
  font-family: "Newsreader", Georgia, serif; color: var(--text);
  font-weight: 700; letter-spacing: -0.015em;
}
.topic h3 a { color: inherit; }
.topic h3 a:hover, .topic h3 a:focus-visible { color: var(--blue); text-decoration: none; }
.topic p { color: #526274; }
.topic-links { gap: 14px; }
.topic-links a {
  min-height: auto; padding: 0; border-radius: 0; background: transparent;
  color: var(--blue); font-size: 11.5px; font-weight: 500;
}
.topic-links a:hover, .topic-links a:focus-visible {
  background: transparent; text-decoration: underline;
}
.topic-lead {
  grid-column: 1; grid-row: 1 / 5; display: grid;
  grid-template-columns: 34px minmax(0, 1fr); align-content: center;
  gap: 10px; padding: 30px; background: var(--navy); color: #FFFFFF;
}
.topic-lead .topic-rank { color: #82ACFF; font-size: 14px; }
.topic-lead h3 {
  color: #FFFFFF; font-size: clamp(27px, 2.35vw, 38px); line-height: 1.08;
  margin: 0 0 15px;
}
.topic-lead h3 a:hover, .topic-lead h3 a:focus-visible { color: #B9D2FF; }
.topic-lead p {
  color: #C8D5E2; font-size: 16px; line-height: 1.5; margin-bottom: 18px;
  display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 4; overflow: hidden;
}
.topic-lead .topic-links a { color: #AFCBFF; }
.topic-secondary {
  grid-column: 2; display: grid; grid-template-columns: 34px minmax(0, 1fr);
  gap: 8px; align-items: center; padding: 12px 20px;
  border-bottom: 1px solid var(--rule);
}
.topic-secondary:last-child { border-bottom: 0; }
.topic-secondary h3 {
  margin: 0 0 3px; font-size: 19.5px; line-height: 1.23;
  display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; overflow: hidden;
}
.topic-secondary p {
  margin: 0 0 4px; font-size: 13.5px; line-height: 1.35;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}

.feed-panel {
  margin-top: 30px; padding: 0; background: transparent;
  border: 0; border-radius: 0; box-shadow: none;
}
.feed-panel .section-heading {
  padding-bottom: 10px; margin-bottom: 0; border-bottom: 2px solid var(--navy);
}
.feed-panel h2 { font-size: 29px; }
.radar-filters {
  display: flex; gap: 7px; padding: 13px 0; overflow-x: auto;
  border-bottom: 1px solid var(--rule);
}
.radar-filter, .radar-more {
  border: 1px solid var(--rule-strong); background: var(--surface); color: var(--muted);
  font: 500 13px "IBM Plex Sans", sans-serif; cursor: pointer;
}
.radar-filter {
  min-height: 33px; padding: 5px 11px; border-radius: 999px; white-space: nowrap;
}
.radar-filter span { margin-left: 4px; color: #8A98A8; font-size: 11px; }
.radar-filter:hover { color: var(--blue); border-color: #AFC6F5; }
.radar-filter.is-active {
  color: #FFFFFF; background: var(--blue); border-color: var(--blue);
}
.radar-filter.is-active span { color: #DCE8FF; }
.radar-list { list-style: none; margin: 0; padding: 0; background: var(--surface); }
.radar-row {
  display: grid; grid-template-columns: 62px 112px minmax(0, 1fr) 100px;
  align-items: center; gap: 12px; min-height: 48px; padding: 8px 14px;
  border-bottom: 1px solid var(--rule); font-size: 14.5px;
}
.radar-row[hidden] { display: none; }
.radar-row time, .radar-age {
  color: var(--muted); font: 12px "IBM Plex Mono", monospace; white-space: nowrap;
}
.radar-source {
  color: var(--navy-soft); font-size: 12px; font-weight: 700;
  letter-spacing: 0.035em; text-transform: uppercase;
}
.radar-title { min-width: 0; }
.radar-title a { color: var(--text); font-weight: 500; }
.radar-title a:hover, .radar-title a:focus-visible { color: var(--blue); text-decoration: none; }
.radar-age { text-align: right; }
.radar-more {
  display: block; margin: 16px auto 0; min-height: 38px; padding: 7px 15px;
  border-radius: 3px; color: var(--blue);
}
.radar-more:hover { background: var(--blue-soft); border-color: #AFC6F5; }
.radar-more[hidden] { display: none; }
.radar-empty { padding: 22px 0; color: var(--muted); font-size: 14px; }

footer { background: var(--navy); border: 0; color: #B7C7D6; }
.pill { border-color: #41566A; }
.pill-ok { color: #A4DBB4; border-color: #37614A; background: transparent; }
.pill-fail { color: #FF9BA7; border-color: #74404A; background: transparent; }
.footer-link { color: #AFCBFF; }
.footer-note { color: #8FA3B6; }

@media (max-width: 980px) {
  .header-inner { grid-template-columns: auto 1fr; gap: 20px; }
  .updated { display: none; }
  nav { justify-self: end; }
  .topics-board {
    min-height: 0; grid-template-columns: 1fr; grid-template-rows: auto;
  }
  .topic-lead { grid-column: 1; grid-row: auto; min-height: 300px; }
  .topic-secondary { grid-column: 1; }
}
@media (max-width: 680px) {
  .header-inner {
    min-height: 0; padding: 13px 17px 0; display: block;
  }
  .masthead { font-size: 20px; }
  nav { gap: 2px; margin-top: 7px; overflow-x: auto; }
  nav a { min-height: 42px; padding: 0 8px; font-size: 12px; white-space: nowrap; }
  .flash-inner {
    padding: 9px 17px 11px; display: block;
  }
  .flash-label {
    min-height: 28px; padding: 0; border: 0;
  }
  .flash-list { display: block; }
  .flash-item { grid-template-columns: 1fr; gap: 3px; padding: 7px 0; }
  .flash-item + .flash-item { border-top: 1px solid var(--red-rule); }
  .flash-title, .flash-reason { white-space: normal; }
  .flash-title {
    display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2;
  }
  .flash-reason {
    display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2;
  }
  main { padding: 20px 14px 32px; }
  .topics-board { border-left: 0; border-right: 0; }
  .topic-lead {
    min-height: 290px; padding: 25px 18px;
    grid-template-columns: 27px minmax(0, 1fr);
  }
  .topic-lead h3 { font-size: 29px; }
  .topic-secondary {
    padding: 15px 10px; grid-template-columns: 27px minmax(0, 1fr);
  }
  .topic-secondary h3 { font-size: 18px; }
  .topic-secondary p {
    font-size: 14px;
    white-space: normal; display: -webkit-box; -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
  }
  .radar-row {
    grid-template-columns: 47px minmax(0, 1fr) auto;
    gap: 8px; padding: 10px 4px;
  }
  .radar-source { grid-column: 2; grid-row: 1; }
  .radar-title { grid-column: 2 / 4; grid-row: 2; }
  .radar-age { grid-column: 3; grid-row: 1; }
  .radar-row time { grid-column: 1; grid-row: 1 / 3; align-self: start; padding-top: 2px; }
}
"""


def build_html(state, generated_at: datetime | None = None) -> str:
    now = generated_at or datetime.now(timezone.utc)
    now_str = now.astimezone(_LOCAL_TZ).strftime("%H:%M:%S · %d.%m.%Y")
    generated_ts_ms = int(now.timestamp() * 1000)
    alerts_flash = _render_alert_flash(state.recent_alerts_window(3))
    topics_html = _render_topics(state.last_digest)
    raw_html = _render_raw_feed(state.recent_window(12))
    sources_html = _render_sources(state.source_status)

    return f"""<!DOCTYPE html>
<html lang="sk">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="{_REFRESH_SECONDS}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;700&family=IBM+Plex+Sans:wght@400;500;600;700&family=Newsreader:opsz,wght@6..72,600;6..72,700&display=swap" rel="stylesheet">
<title>SK News Agent — Prehľad</title>
<style>{_CSS}</style>
</head>
<body>
<header class="site-header">
  <div class="header-inner">
    <div class="masthead">SK News Agent <b>Prehľad</b></div>
    <nav aria-label="Hlavná navigácia">
      <a href="#top-temy">Prehľad</a>
      <a href="#media-radar">Media Radar</a>
      <a href="audit.html">História výberov</a>
    </nav>
    <div class="updated">
      Aktualizované {now_str}
      <span id="live-ago" class="mono" data-ts="{generated_ts_ms}"></span>
    </div>
  </div>
</header>
{alerts_flash}
<main>
  <section id="top-temy" class="top-section">
    <div class="section-heading">
      <div>
        <div class="eyebrow">Redakčný výber</div>
        <h2>Top témy</h2>
      </div>
    </div>
    {topics_html}
  </section>
  <section id="media-radar" class="feed-panel">
    <div class="section-heading">
      <div>
        <div class="eyebrow">Posledných 12 hodín</div>
        <h2>Media Radar</h2>
      </div>
    </div>
    {raw_html}
  </section>
</main>
<footer>
  {sources_html}
  <a class="footer-link" href="audit.html">História výberov →</a>
  <span class="footer-note">beží automaticky, GitHub cron je "best-effort" (môže meškať)</span>
</footer>
<script>
// Poctivý živý indikátor "pred X" — tiká aj keď stránka len leží otvorená
// medzi auto-refreshmi. Ak toto číslo rastie nezvyčajne dlho bez resetu,
// je to znak, že GitHub Actions cron nejaký čas nebežal (známa vlastnosť
// platformy — schedule trigger je "best-effort", nie garantovaný).
(function () {{
  var el = document.getElementById('live-ago');
  if (!el) return;
  var ts = parseInt(el.getAttribute('data-ts'), 10);
  function tick() {{
    var mins = Math.floor((Date.now() - ts) / 60000);
    var text = mins < 1 ? 'práve teraz' : mins < 60 ? ('pred ' + mins + ' min')
      : ('pred ' + (mins / 60).toFixed(1) + ' h');
    el.textContent = '(' + text + ')';
    el.classList.toggle('stale-warning', mins > 60);
  }}
  tick();
  setInterval(tick, 30000);

  // GitHub cron ani nasadenie Pages nemajú presnú minútu. Namiesto slepého
  // reloadu často kontrolujeme iba malý version.json a stránku obnovíme až
  // vtedy, keď je skutočne dostupný novší vygenerovaný obsah.
  function checkForUpdate() {{
    fetch('version.json?check=' + Date.now(), {{ cache: 'no-store' }})
      .then(function (response) {{ return response.ok ? response.json() : null; }})
      .then(function (version) {{
        var latest = version && Number(version.generated_ts);
        if (!latest || latest <= ts) return;
        var nextUrl = new URL(window.location.href);
        nextUrl.searchParams.set('v', String(latest));
        window.location.replace(nextUrl.toString());
      }})
      .catch(function () {{ /* 10-minútový meta refresh zostáva ako poistka */ }});
  }}
  setInterval(checkForUpdate, {_UPDATE_CHECK_MS});
}})();

// Media Radar: jeden chronologický tok s rýchlym filtrovaním podľa zdroja.
(function () {{
  var filters = Array.prototype.slice.call(document.querySelectorAll('.radar-filter'));
  var rows = Array.prototype.slice.call(document.querySelectorAll('.radar-row'));
  var more = document.querySelector('.radar-more');
  var empty = document.querySelector('.radar-empty');
  if (!filters.length || !rows.length || !more) return;

  var activeFilter = 'all';
  var visibleLimit = 12;

  function renderRadar() {{
    var matches = rows.filter(function (row) {{
      return activeFilter === 'all' || row.getAttribute('data-source') === activeFilter;
    }});
    rows.forEach(function (row) {{ row.hidden = true; }});
    matches.slice(0, visibleLimit).forEach(function (row) {{ row.hidden = false; }});
    more.hidden = matches.length <= visibleLimit;
    empty.hidden = matches.length > 0;
  }}

  filters.forEach(function (button) {{
    button.addEventListener('click', function () {{
      activeFilter = button.getAttribute('data-filter') || 'all';
      visibleLimit = 12;
      filters.forEach(function (item) {{
        var active = item === button;
        item.classList.toggle('is-active', active);
        item.setAttribute('aria-pressed', active ? 'true' : 'false');
      }});
      renderRadar();
    }});
  }});

  more.addEventListener('click', function () {{
    visibleLimit += 12;
    renderRadar();
  }});

  renderRadar();
}})();
</script>
</body>
</html>
"""


def write_page(
    state,
    path: str = _OUTPUT_PATH,
    version_path: str | None = _VERSION_PATH,
) -> None:
    """Zapíše stránku na disk. Nikdy nevyhadzuje výnimku vyššie — stránka
    je vylepšenie, nie kritická cesta; jej zlyhanie nesmie zhodiť beh."""
    import logging
    log = logging.getLogger(__name__)
    try:
        generated_at = datetime.now(timezone.utc)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        html = build_html(state, generated_at)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(html)
        os.replace(tmp, path)
        if version_path:
            generated_ts_ms = int(generated_at.timestamp() * 1000)
            os.makedirs(os.path.dirname(version_path) or ".", exist_ok=True)
            version_tmp = version_path + ".tmp"
            with open(version_tmp, "w", encoding="utf-8") as f:
                json.dump({"generated_ts": generated_ts_ms}, f, separators=(",", ":"))
                f.write("\n")
            os.replace(version_tmp, version_path)
    except Exception:  # noqa: BLE001 — stránka nesmie zhodiť beh
        log.exception("Generovanie GitHub Pages stránky zlyhalo — beh pokračuje.")
