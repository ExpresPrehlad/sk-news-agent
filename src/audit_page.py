"""Statická, ľudsky čitateľná história LLM výberov pre GitHub Pages."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from html import escape
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from .config import ACTIVE_HOURS_TZ, SELECTION_LOG_DIR
from .selection_log import read_recent_events

_OUTPUT_PATH = "docs/audit.html"
_LOCAL_TZ = ZoneInfo(ACTIVE_HOURS_TZ)
_MAX_EVENTS = 200

_SIGNAL_LABELS = {
    "direct_slovak_relevance": "priama väzba na SR",
    "ongoing_danger": "trvajúce ohrozenie",
    "public_impact": "verejný dosah",
    "strategic_infrastructure": "strategická infraštruktúra",
    "mass_casualty": "veľa obetí",
    "terrorism": "terorizmus",
    "public_transport": "verejná doprava",
    "hazardous_materials": "nebezpečné látky",
}


def _fmt_datetime(ts: float) -> str:
    try:
        return (
            datetime.fromtimestamp(float(ts), tz=timezone.utc)
            .astimezone(_LOCAL_TZ)
            .strftime("%H:%M · %d.%m.%Y")
        )
    except (TypeError, ValueError, OSError):
        return "neznámy čas"


def _safe_link(url: str, label: str) -> str:
    parsed = urlparse(str(url))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return (
        f'<a href="{escape(str(url), quote=True)}" target="_blank" '
        f'rel="noopener">{escape(label)} →</a>'
    )


def _render_selected(event: dict) -> str:
    event_type = event.get("event_type")
    selected = event.get("selected")
    if event.get("decision_valid") is False:
        return (
            '<div class="empty-selection invalid">'
            "Výstup modelu sa nepodarilo spracovať.</div>"
        )
    if not isinstance(selected, list) or not selected:
        return '<div class="empty-selection">Model nevybral nič.</div>'

    rows = []
    for index, item in enumerate(selected, start=1):
        if not isinstance(item, dict):
            continue
        title = item.get("title") if event_type == "triage" else item.get("headline")
        detail = item.get("reason") if event_type == "triage" else item.get("perex")
        signals = item.get("signals") if isinstance(item.get("signals"), dict) else {}
        signal_items = []
        if signals.get("geography"):
            signal_items.append(str(signals["geography"]))
        if signals.get("event_type"):
            signal_items.append(str(signals["event_type"]))
        signal_items.extend(
            label for key, label in _SIGNAL_LABELS.items() if signals.get(key) is True
        )
        signals_html = "".join(
            f'<span class="signal">{escape(label)}</span>'
            for label in signal_items
        )
        links = []
        for link in item.get("links") or []:
            if isinstance(link, dict):
                rendered = _safe_link(link.get("url", ""), link.get("source", "zdroj"))
            else:
                rendered = _safe_link(str(link), "zdroj")
            if rendered:
                links.append(rendered)
        rows.append(
            '<li class="selection">'
            f'<span class="rank">{index:02d}</span>'
            '<div>'
            f'<h3>{escape(str(title or "Bez názvu"))}</h3>'
            f'<p>{escape(str(detail or ""))}</p>'
            f'<div class="signals">{signals_html}</div>'
            f'<div class="links">{"".join(links)}</div>'
            "</div></li>"
        )
    return '<ol class="selections">' + "".join(rows) + "</ol>"


def _render_candidates(event: dict) -> str:
    if event.get("event_type") != "triage":
        return ""
    input_data = event.get("input") if isinstance(event.get("input"), dict) else {}
    candidates = input_data.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return ""
    rows = []
    for candidate in candidates[:40]:
        if not isinstance(candidate, dict):
            continue
        source = escape(str(candidate.get("source") or "zdroj"))
        title = escape(str(candidate.get("title") or "Bez názvu"))
        url = candidate.get("link", "")
        rendered = _safe_link(url, str(candidate.get("title") or "Bez názvu"))
        title_html = rendered if rendered else title
        rows.append(f"<li><span>{source}</span>{title_html}</li>")
    return (
        '<details class="candidates">'
        f"<summary>Vstupné kandidáty ({len(candidates)}) — kontrola "
        "možných prehliadnutí</summary>"
        f'<ul>{"".join(rows)}</ul></details>'
    )


def _render_event(event: dict) -> str:
    event_type = event.get("event_type", "")
    is_triage = event_type == "triage"
    label = "Mimoriadne" if is_triage else "TOP témy"
    css_type = "triage" if is_triage else "synthesis"
    count = int(event.get("selection_count", 0) or 0)
    model = escape(str(event.get("model") or "neznámy model"))
    run_id = escape(str(event.get("run_id") or "")[:8])
    revision = escape(str(event.get("code_revision") or "")[:7])
    published = event.get("published")
    publish_label = "publikované" if published else "nepublikované"
    publish_class = "ok" if published else "fail"
    decision_valid = event.get("decision_valid", True)
    decision_html = (
        ' · <span class="fail">neparsovateľný výstup</span>'
        if not decision_valid
        else ""
    )
    input_data = event.get("input") if isinstance(event.get("input"), dict) else {}
    input_count = int(input_data.get("article_count", 0) or 0)
    policy_version = escape(str(input_data.get("policy_version") or ""))
    policy_html = f" · politika {policy_version}" if policy_version else ""
    revision_html = f" · rev. {revision}" if revision else ""
    return (
        f'<article class="event {css_type}" data-type="{css_type}">'
        '<div class="event-head">'
        f'<span class="badge">{label}</span>'
        f'<strong>{count} vybraných</strong>'
        f'<time>{_fmt_datetime(event.get("recorded_ts", 0))}</time>'
        "</div>"
        f'<div class="meta">{model} · vstup {input_count} článkov · beh {run_id}'
        f'{revision_html}{policy_html} · '
        f'<span class="{publish_class}">{publish_label}</span>'
        f"{decision_html}</div>"
        f"{_render_selected(event)}"
        f"{_render_candidates(event)}"
        "</article>"
    )


def build_audit_html(events: list[dict]) -> str:
    cards = "".join(_render_event(event) for event in events)
    if not cards:
        cards = (
            '<div class="empty">Audit je zatiaľ prázdny. Prvý záznam pribudne '
            "po najbližšej úspešnej triáži alebo syntéze.</div>"
        )
    generated = datetime.now(timezone.utc).astimezone(_LOCAL_TZ).strftime(
        "%H:%M:%S · %d.%m.%Y"
    )
    return f"""<!DOCTYPE html>
<html lang="sk">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;700&family=IBM+Plex+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<title>SK News Agent — História výberov</title>
<style>
:root {{
  --ink:#15171C; --panel:#1E2128; --text:#E8E6E1; --muted:#8A8F98;
  --amber:#E8A33D; --red:#C6432E; --blue:#5B91C7; --rule:#33373F;
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--ink); color:var(--text);
  font-family:"IBM Plex Sans",-apple-system,sans-serif; line-height:1.5; }}
a {{ color:var(--amber); text-decoration:none; }}
a:hover, a:focus-visible {{ text-decoration:underline; }}
header {{ padding:24px; border-bottom:1px solid var(--amber); }}
.bar {{ max-width:1000px; margin:0 auto; display:flex; justify-content:space-between;
  align-items:baseline; flex-wrap:wrap; gap:10px; }}
.masthead, .meta, time, button {{ font-family:"IBM Plex Mono",monospace; }}
.masthead {{ color:var(--amber); font-size:13px; letter-spacing:.12em;
  text-transform:uppercase; }}
.updated {{ color:var(--muted); font-size:12px; }}
main {{ max-width:1000px; margin:0 auto; padding:28px 24px 60px; }}
h1 {{ font-size:25px; margin:0 0 6px; }}
.intro {{ color:var(--muted); margin:0 0 18px; max-width:760px; }}
.filters {{ display:flex; gap:8px; margin-bottom:24px; flex-wrap:wrap; }}
button {{ cursor:pointer; color:var(--text); background:var(--panel);
  border:1px solid var(--rule); border-radius:4px; padding:7px 11px; }}
button.active {{ color:var(--ink); background:var(--amber); border-color:var(--amber); }}
.event {{ background:var(--panel); border:1px solid var(--rule); border-left:3px solid var(--blue);
  border-radius:6px; margin-bottom:14px; padding:16px 18px; }}
.event.triage {{ border-left-color:var(--red); }}
.event-head {{ display:flex; align-items:center; gap:10px; flex-wrap:wrap; }}
.event-head time {{ color:var(--muted); font-size:12px; margin-left:auto; }}
.badge {{ font-family:"IBM Plex Mono",monospace; font-size:11px; letter-spacing:.08em;
  text-transform:uppercase; color:var(--blue); }}
.triage .badge {{ color:var(--red); }}
.meta {{ color:var(--muted); font-size:11px; margin:5px 0 10px; }}
.ok {{ color:#7FB08A; }} .fail {{ color:var(--red); }}
.selections {{ list-style:none; margin:0; padding:0; }}
.selection {{ display:grid; grid-template-columns:32px 1fr; gap:10px;
  padding:11px 0; border-top:1px solid var(--rule); }}
.rank {{ color:var(--amber); font-family:"IBM Plex Mono",monospace; font-weight:700; }}
.selection h3 {{ font-size:15px; margin:0 0 3px; }}
.selection p {{ color:#C9C7C1; font-size:13px; margin:0 0 5px; }}
.signals {{ display:flex; gap:5px; flex-wrap:wrap; margin:0 0 6px; }}
.signal {{ color:#B8C9D9; background:#25313D; border:1px solid #34475A;
  border-radius:999px; padding:1px 6px; font:10px "IBM Plex Mono",monospace; }}
.links a {{ font-family:"IBM Plex Mono",monospace; font-size:11px; margin-right:12px; }}
.candidates {{ border-top:1px solid var(--rule); margin-top:8px; padding-top:8px; }}
.candidates summary {{ color:var(--muted); cursor:pointer;
  font:11px "IBM Plex Mono",monospace; }}
.candidates ul {{ list-style:none; margin:8px 0 0; padding:0; }}
.candidates li {{ display:grid; grid-template-columns:110px 1fr; gap:8px;
  padding:3px 0; font-size:11.5px; }}
.candidates li span {{ color:var(--muted); }}
.candidates li a {{ color:#C9C7C1; }}
.empty-selection, .empty {{ color:var(--muted); font-style:italic; font-size:13px; }}
.empty-selection {{ border-top:1px solid var(--rule); padding-top:10px; }}
@media (max-width:600px) {{ .event-head time {{ width:100%; margin-left:0; }} }}
</style>
</head>
<body>
<header><div class="bar">
  <div class="masthead"><a href="index.html">SK News Agent · Wire</a> / História výberov</div>
  <div class="updated">Vygenerované {generated}</div>
</div></header>
<main>
  <h1>História výberov</h1>
  <p class="intro">Audit rozhodnutí modelov: čo bolo v jednotlivých behoch
  označené ako mimoriadne a ktoré témy sa dostali do prehľadu. Pri triáži
  možno rozbaliť aj všetky vstupné kandidáty a skontrolovať možné prehliadnutia.</p>
  <div class="filters" aria-label="Filtrovanie záznamov">
    <button class="active" data-filter="all">Všetko</button>
    <button data-filter="triage">Mimoriadne</button>
    <button data-filter="synthesis">TOP témy</button>
  </div>
  <div id="events">{cards}</div>
</main>
<script>
(function () {{
  var buttons = document.querySelectorAll('[data-filter]');
  var events = document.querySelectorAll('.event');
  buttons.forEach(function (button) {{
    button.addEventListener('click', function () {{
      var filter = button.getAttribute('data-filter');
      buttons.forEach(function (item) {{ item.classList.remove('active'); }});
      button.classList.add('active');
      events.forEach(function (event) {{
        event.hidden = filter !== 'all' && event.getAttribute('data-type') !== filter;
      }});
    }});
  }});
}})();
</script>
</body>
</html>
"""


def write_audit_page(
    log_directory: str = SELECTION_LOG_DIR,
    path: str = _OUTPUT_PATH,
) -> None:
    """Vygeneruje auditnú stránku; zlyhanie nikdy nezastaví hlavný beh."""
    import logging

    page_log = logging.getLogger(__name__)
    try:
        events = read_recent_events(log_directory, _MAX_EVENTS)
        html = build_audit_html(events)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as file:
            file.write(html)
        os.replace(tmp, path)
    except Exception:  # noqa: BLE001 — stránka nesmie zhodiť beh
        page_log.exception(
            "Generovanie auditnej GitHub Pages stránky zlyhalo — beh pokračuje."
        )
