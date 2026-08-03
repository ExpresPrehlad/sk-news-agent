"""Statická podstránka so samostatným športovým prehľadom."""

from __future__ import annotations

import os
import logging
from datetime import datetime, timezone
from html import escape
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from .config import ACTIVE_HOURS_TZ

_OUTPUT_PATH = "docs/sport.html"
_LOCAL_TZ = ZoneInfo(ACTIVE_HOURS_TZ)
log = logging.getLogger(__name__)


def _safe_url(value: object) -> str:
    url = str(value or "").strip()
    parsed = urlparse(url)
    return url if parsed.scheme in {"http", "https"} and parsed.netloc else ""


def _ago(ts: float) -> str:
    minutes = int((datetime.now(timezone.utc).timestamp() - ts) / 60)
    if minutes < 1:
        return "práve teraz"
    if minutes < 60:
        return f"pred {minutes} min"
    return f"pred {minutes // 60} h"


def _render_articles(articles: list[dict]) -> str:
    if not articles:
        return (
            '<p class="empty">Športový prehľad sa naplní po najbližšom '
            "úspešnom zbere.</p>"
        )
    rows = []
    for article in sorted(articles, key=lambda item: -float(item.get("ts", 0)))[:40]:
        ts = float(article.get("ts", 0))
        title = escape(str(article.get("t", "")))
        url = _safe_url(article.get("l"))
        if url:
            title = (
                f'<a href="{escape(url, quote=True)}" target="_blank" '
                f'rel="noopener">{title}</a>'
            )
        rows.append(
            '<article class="sport-row">'
            f'<time>{datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(_LOCAL_TZ).strftime("%H:%M")}</time>'
            f'<div><span class="source">{escape(str(article.get("s", "Šport")))}</span>'
            f'<h2>{title}</h2>'
            f'<p>{escape(str(article.get("p", "")))}</p></div>'
            f'<span class="age">{_ago(ts)}</span>'
            "</article>"
        )
    return "".join(rows)


def build_sport_html(state) -> str:
    articles = state.sport_recent_window(24)
    generated = datetime.now(timezone.utc).timestamp()
    return f"""<!doctype html>
<html lang="sk">
<head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="600"><title>Šport | SK News Agent</title>
  <style>
    :root {{ --navy:#10243b; --ink:#10203a; --blue:#3158dc; --muted:#617089; --line:#d9e0e9; --paper:#f7f8fa; }}
    * {{ box-sizing:border-box; }} body {{ margin:0; background:var(--paper); color:var(--ink); font:16px/1.5 Arial,sans-serif; }}
    header {{ background:var(--navy); color:white; }} .bar, main {{ max-width:1240px; margin:auto; padding-left:32px; padding-right:32px; }}
    .bar {{ min-height:70px; display:flex; align-items:center; gap:28px; }} .brand {{ font:700 22px Georgia,serif; white-space:nowrap; }}
    nav {{ display:flex; gap:24px; flex-wrap:wrap; }} nav a {{ color:#dce7f7; text-decoration:none; font-size:14px; }} nav a.active {{ color:white; font-weight:700; }}
    main {{ padding-top:44px; padding-bottom:56px; max-width:1080px; }} .eyebrow {{ color:var(--blue); font:700 11px monospace; letter-spacing:.12em; text-transform:uppercase; }}
    h1 {{ font:700 38px/1.1 Georgia,serif; margin:4px 0 8px; }} .intro {{ color:var(--muted); max-width:760px; margin:0 0 30px; }}
    .note {{ background:#eaf0ff; border-left:4px solid var(--blue); padding:13px 16px; color:#29436e; font-size:14px; margin-bottom:24px; }}
    .list {{ background:white; border:1px solid var(--line); }} .sport-row {{ display:grid; grid-template-columns:62px 1fr 82px; gap:18px; padding:18px 20px; border-bottom:1px solid var(--line); }}
    .sport-row:last-child {{ border-bottom:0; }} time,.age,.source {{ font:12px monospace; color:var(--muted); }} .source {{ color:var(--blue); font-weight:700; }}
    h2 {{ font:700 18px/1.25 Georgia,serif; margin:3px 0 5px; }} h2 a {{ color:inherit; text-decoration:none; }} h2 a:hover {{ color:var(--blue); text-decoration:underline; }}
    .sport-row p {{ color:#536176; font-size:14px; margin:0; }} .age {{ text-align:right; white-space:nowrap; }} .empty {{ padding:26px; color:var(--muted); }}
    @media(max-width:700px) {{ .bar,main {{ padding-left:18px; padding-right:18px; }} .bar {{ padding-top:16px; padding-bottom:16px; align-items:flex-start; flex-direction:column; gap:10px; }} nav {{ gap:14px; }} h1 {{ font-size:31px; }} .sport-row {{ grid-template-columns:46px 1fr; gap:10px; padding:16px; }} .age {{ display:none; }} }}
  </style>
</head>
<body data-ts="{generated:.6f}">
  <header><div class="bar"><div class="brand">SK News Agent</div><nav aria-label="Hlavná navigácia">
    <a href="index.html">Prehľad</a><a href="index.html#media-radar">Media Radar</a><a class="active" href="sport.html" aria-current="page">Šport</a><a href="audit.html">História výberov</a>
  </nav></div></header>
  <main><div class="eyebrow">Posledných 24 hodín</div><h1>Športový prehľad</h1>
    <p class="intro">Samostatný pracovný prehľad športových správ pre redakciu.</p>
    <div class="note">Športové témy zostávajú plnohodnotnými kandidátmi pre Mimoriadne aj Top témy. Táto stránka iba zhromažďuje širší športový tok bez zásahu do hlavného výberu.</div>
    <section class="list" aria-label="Športové správy">{_render_articles(articles)}</section>
  </main>
  <script>
  (function () {{
    var pageTimestamp = Number(document.body.getAttribute('data-ts')) || 0;
    function checkForUpdate() {{
      fetch('version.json?check=' + Date.now(), {{ cache: 'no-store' }})
        .then(function (response) {{ return response.ok ? response.json() : null; }})
        .then(function (version) {{
          if (version && Number(version.generated_ts) > pageTimestamp) location.reload();
        }})
        .catch(function () {{}});
    }}
    setInterval(checkForUpdate, 60000);
  }})();
  </script>
</body></html>"""


def write_sport_page(state, output_path: str = _OUTPUT_PATH) -> None:
    """Vygeneruje stránku; zlyhanie nesmie zastaviť hlavný zber."""
    try:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        tmp = output_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(build_sport_html(state))
        os.replace(tmp, output_path)
    except OSError:
        log.exception("Generovanie športovej GitHub Pages stránky zlyhalo — beh pokračuje.")
