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

import os
from datetime import datetime, timezone
from html import escape

_OUTPUT_PATH = "docs/index.html"

_REFRESH_SECONDS = 180  # auto-reload — stránka sa dá nechať otvorenú v redakcii


def _fmt_time(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone().strftime("%H:%M · %d.%m.%Y")


def _ago(ts: float) -> str:
    mins = int((datetime.now(timezone.utc).timestamp() - ts) / 60)
    if mins < 1:
        return "práve teraz"
    if mins < 60:
        return f"pred {mins} min"
    hours = mins // 60
    return f"pred {hours} h {mins % 60} min" if mins % 60 else f"pred {hours} h"


def _render_alert_flash(alerts: list[dict]) -> str:
    if not alerts:
        return ""
    items = "".join(
        f'<div class="flash-item">'
        f'<span class="flash-title">{escape(a["title"])}</span>'
        f'<span class="flash-reason">{escape(a["reason"])}</span>'
        f"</div>"
        for a in alerts
    )
    return f'<div class="wire-flash" role="alert"><div class="flash-label">MIMORIADNE</div>{items}</div>'


def _render_topics(digest: dict) -> str:
    if not digest or not digest.get("topics"):
        return (
            '<div class="empty">Zatiaľ žiadny prehľad — prvá syntéza prebehne '
            "čoskoro po nazbieraní dostatku článkov.</div>"
        )
    topics = digest["topics"]
    model = digest.get("model", "")
    ts = digest.get("ts", 0)
    cards = []
    for i, t in enumerate(topics, start=1):
        links = "".join(
            f'<a href="{escape(link)}" target="_blank" rel="noopener">zdroj →</a>'
            for link in t.get("links", [])[:2]
        )
        cards.append(
            f'<article class="topic">'
            f'<div class="topic-rank">{i:02d}</div>'
            f'<div class="topic-body">'
            f'<h3>{escape(t["headline"])}</h3>'
            f'<p>{escape(t["perex"])}</p>'
            f'<div class="topic-links">{links}</div>'
            f"</div></article>"
        )
    meta = (
        f'<div class="section-meta">Aktualizované {_ago(ts)} · '
        f'<span class="mono">{escape(model)}</span></div>'
    )
    return meta + '<div class="topics">' + "".join(cards) + "</div>"


def _render_raw_feed(articles: list[dict]) -> str:
    if not articles:
        return '<div class="empty">Zatiaľ žiadne články v okne posledných hodín.</div>'
    by_source: dict[str, list[dict]] = {}
    for a in sorted(articles, key=lambda x: -float(x.get("ts", 0))):
        by_source.setdefault(a["s"], []).append(a)
    groups = []
    for source, items in sorted(by_source.items()):
        rows = "".join(
            f'<li><a href="{escape(a["l"])}" target="_blank" rel="noopener">'
            f'{escape(a["t"])}</a><span class="mono ts">{_ago(float(a.get("ts", 0)))}</span></li>'
            for a in items[:15]
        )
        groups.append(
            f'<div class="feed-group"><h4>{escape(source)} '
            f'<span class="mono count">{len(items)}</span></h4><ul>{rows}</ul></div>'
        )
    return "".join(groups)


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
  --ink: #15171C;
  --panel: #1E2128;
  --panel-2: #262A33;
  --text: #E8E6E1;
  --muted: #8A8F98;
  --amber: #E8A33D;
  --red: #C6432E;
  --rule: #33373F;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0; background: var(--ink); color: var(--text);
  font-family: "IBM Plex Sans", -apple-system, sans-serif;
  line-height: 1.5;
}
.mono { font-family: "IBM Plex Mono", ui-monospace, monospace; }
a { color: var(--amber); text-decoration: none; }
a:hover, a:focus-visible { text-decoration: underline; }
a:focus-visible, .pill:focus-visible { outline: 2px solid var(--amber); outline-offset: 2px; }

.wire-flash {
  background: linear-gradient(180deg, #2a1510, #1c0f0c);
  border-bottom: 2px solid var(--red);
  padding: 14px 20px;
}
@media (prefers-reduced-motion: no-preference) {
  .wire-flash { animation: flash-pulse 2.4s ease-in-out infinite; }
}
@keyframes flash-pulse {
  0%, 100% { border-bottom-color: var(--red); }
  50% { border-bottom-color: var(--amber); }
}
.flash-label {
  font-family: "IBM Plex Mono", monospace; font-size: 12px; letter-spacing: 0.15em;
  color: var(--red); font-weight: 700; margin-bottom: 6px;
}
.flash-item { margin: 4px 0; }
.flash-title { font-weight: 600; margin-right: 10px; }
.flash-reason { color: var(--muted); font-size: 14px; }

header {
  padding: 28px 24px 16px; border-bottom: 1px solid var(--amber);
  display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap; gap: 8px;
}
.masthead { font-family: "IBM Plex Mono", monospace; font-size: 13px; letter-spacing: 0.15em;
  color: var(--amber); text-transform: uppercase; }
.masthead b { color: var(--text); letter-spacing: 0.02em; }
.updated { font-family: "IBM Plex Mono", monospace; font-size: 12px; color: var(--muted); }

main { max-width: 1100px; margin: 0 auto; padding: 24px; display: grid;
  grid-template-columns: 1.5fr 1fr; gap: 32px; }
@media (max-width: 860px) { main { grid-template-columns: 1fr; } }

h2 { font-size: 15px; text-transform: uppercase; letter-spacing: 0.1em;
  color: var(--muted); margin: 0 0 4px; font-family: "IBM Plex Mono", monospace; }
.section-meta { font-size: 12px; color: var(--muted); margin-bottom: 14px; }

.topic { display: flex; gap: 14px; background: var(--panel); border-radius: 6px;
  padding: 16px 18px; margin-bottom: 12px; border: 1px solid var(--rule); }
.topic-rank { font-family: "IBM Plex Mono", monospace; color: var(--amber);
  font-size: 20px; font-weight: 700; min-width: 32px; }
.topic h3 { margin: 0 0 6px; font-size: 17px; }
.topic p { margin: 0 0 8px; color: #C9C7C1; font-size: 14.5px; }
.topic-links a { font-size: 12px; margin-right: 12px; font-family: "IBM Plex Mono", monospace; }

.feed-group { margin-bottom: 18px; }
.feed-group h4 { font-size: 13px; color: var(--muted); margin: 0 0 6px;
  font-family: "IBM Plex Mono", monospace; text-transform: uppercase; letter-spacing: 0.05em; }
.feed-group .count { color: var(--amber); }
.feed-group ul { list-style: none; margin: 0; padding: 0; border-left: 2px solid var(--rule); }
.feed-group li { padding: 5px 0 5px 12px; display: flex; justify-content: space-between;
  gap: 10px; font-size: 13.5px; border-bottom: 1px solid #23262d; }
.feed-group li a { color: var(--text); }
.feed-group .ts { color: var(--muted); font-size: 11px; white-space: nowrap; }

.empty { color: var(--muted); font-size: 13.5px; font-style: italic; }

footer { max-width: 1100px; margin: 0 auto; padding: 20px 24px 40px;
  border-top: 1px solid var(--rule); display: flex; flex-wrap: wrap;
  align-items: center; gap: 10px; }
.pill { font-family: "IBM Plex Mono", monospace; font-size: 11px; padding: 4px 9px;
  border-radius: 999px; border: 1px solid var(--rule); }
.pill-ok { color: #7FB08A; border-color: #2E4A34; }
.pill-fail { color: var(--red); border-color: #4A2620; }
.footer-note { font-size: 11.5px; color: var(--muted); margin-left: auto;
  font-family: "IBM Plex Mono", monospace; }
"""


def build_html(state) -> str:
    now_str = datetime.now(timezone.utc).astimezone().strftime("%H:%M:%S · %d.%m.%Y")
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
<title>SK News Agent — Wire</title>
<style>{_CSS}</style>
</head>
<body>
{alerts_flash}
<header>
  <div class="masthead">SK News Agent · <b>Wire</b></div>
  <div class="updated">Aktualizované {now_str}</div>
</header>
<main>
  <section>
    <h2>Top témy</h2>
    {topics_html}
  </section>
  <section>
    <h2>Surový prúd (12 h)</h2>
    {raw_html}
  </section>
</main>
<footer>
  {sources_html}
  <span class="footer-note">beží automaticky ~každých 15 min</span>
</footer>
</body>
</html>
"""


def write_page(state, path: str = _OUTPUT_PATH) -> None:
    """Zapíše stránku na disk. Nikdy nevyhadzuje výnimku vyššie — stránka
    je vylepšenie, nie kritická cesta; jej zlyhanie nesmie zhodiť beh."""
    import logging
    log = logging.getLogger(__name__)
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        html = build_html(state)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(html)
        os.replace(tmp, path)
    except Exception:  # noqa: BLE001 — stránka nesmie zhodiť beh
        log.exception("Generovanie GitHub Pages stránky zlyhalo — beh pokračuje.")
