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
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from .config import ACTIVE_HOURS_TZ

_OUTPUT_PATH = "docs/index.html"

_REFRESH_SECONDS = 180  # auto-reload — stránka sa dá nechať otvorenú v redakcii
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
        f"{items}</div></section>"
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
    for i, t in enumerate(topics, start=1):
        links = "".join(
            f'<a href="{escape(url)}" target="_blank" rel="noopener">{escape(source)} →</a>'
            for source, url in t.get("links", [])[:2]
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
    meta = f'<div class="section-meta">Aktualizované {_ago(ts)}</div>'
    return meta + '<div class="topics">' + "".join(cards) + "</div>"


_VISIBLE_PER_GROUP = 3
_MAX_PER_GROUP = 15


def _render_feed_item(a: dict) -> str:
    return (
        f'<li><a href="{escape(a["l"])}" target="_blank" rel="noopener">'
        f'{escape(a["t"])}</a><span class="mono ts">{_ago(float(a.get("ts", 0)))}</span></li>'
    )


def _render_raw_feed(articles: list[dict]) -> str:
    if not articles:
        return '<div class="empty">Zatiaľ žiadne články v okne posledných hodín.</div>'
    by_source: dict[str, list[dict]] = {}
    for a in sorted(articles, key=lambda x: -float(x.get("ts", 0))):
        by_source.setdefault(a["s"], []).append(a)
    groups = []
    for source, items in sorted(by_source.items()):
        visible = items[:_VISIBLE_PER_GROUP]
        rest = items[_VISIBLE_PER_GROUP:_MAX_PER_GROUP]
        visible_rows = "".join(_render_feed_item(a) for a in visible)
        html = (
            f'<div class="feed-group"><h4>{escape(source)} '
            f'<span class="mono count">{len(items)}</span></h4>'
            f"<ul>{visible_rows}</ul>"
        )
        if rest:
            rest_rows = "".join(_render_feed_item(a) for a in rest)
            html += (
                f'<details class="feed-more">'
                f"<summary>Zobraziť ďalších {len(rest)} →</summary>"
                f"<ul>{rest_rows}</ul></details>"
            )
        html += "</div>"
        groups.append(html)
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
"""


def build_html(state) -> str:
    now = datetime.now(timezone.utc)
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
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;700&family=IBM+Plex+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<title>SK News Agent — Wire</title>
<style>{_CSS}</style>
</head>
<body>
<header class="site-header">
  <div class="header-inner">
    <div class="brand-row">
      <div class="masthead">SK News Agent <b>Prehľad</b></div>
      <div class="updated">
        Aktualizované {now_str}
        <span id="live-ago" class="mono" data-ts="{generated_ts_ms}"></span>
      </div>
    </div>
    <nav aria-label="Hlavná navigácia">
      <a href="#top-temy">Top témy</a>
      <a href="#spravodajsky-prud">Spravodajský prúd</a>
      <a href="audit.html">História výberov</a>
    </nav>
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
  <aside id="spravodajsky-prud" class="feed-panel">
    <div class="section-heading">
      <div>
        <div class="eyebrow">Posledných 12 hodín</div>
        <h2>Spravodajský prúd</h2>
      </div>
    </div>
    {raw_html}
  </aside>
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
}})();
</script>
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
