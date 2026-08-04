"""Statická podstránka s prioritizovaným športovým prehľadom."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from html import escape
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from .config import ACTIVE_HOURS_TZ

_OUTPUT_PATH = "docs/sport.html"
_LOCAL_TZ = ZoneInfo(ACTIVE_HOURS_TZ)
log = logging.getLogger(__name__)

# Zámerne jednoduché a vysvetliteľné pravidlá. Slúžia len na poradie športovej
# stránky; nikdy nevstupujú do Mimoriadne, Top tém ani do LLM výberu.
_HIGH_SIGNAL = (
    "slovensko", "slovensk", "reprezent", "olympi", "majstrovstv",
    "medail", "rekord", "titul", "finále", "finale", "postup",
    "liga majstrov", "svetový pohár", "world cup", "doping",
    "diskvalifik", "zranen",
)
_LOW_SIGNAL = (
    "live", "online prenos", "program", "tv tip", "kurz", "tipuj",
    "stávk", "fotogaléri", "fotogaleri", "preview", "tip na zápas",
)


def _safe_url(value: object) -> str:
    url = str(value or "").strip()
    parsed = urlparse(url)
    return url if parsed.scheme in {"http", "https"} and parsed.netloc else ""


def _ago(ts: float) -> str:
    minutes = max(0, int((datetime.now(timezone.utc).timestamp() - ts) / 60))
    if minutes < 1:
        return "práve teraz"
    if minutes < 60:
        return f"pred {minutes} min"
    return f"pred {minutes // 60} h"


def _priority(article: dict) -> int:
    """Vráti lokálne priority skóre športovej správy."""
    text = " ".join((str(article.get("t", "")), str(article.get("p", "")))).lower()
    high = sum(1 for keyword in _HIGH_SIGNAL if keyword in text)
    low = sum(1 for keyword in _LOW_SIGNAL if keyword in text)
    # Číslo je zámerne malé: zdôrazní význam, ale čerstvosť stále rozhoduje pri remíze.
    return max(0, high * 2 - low * 3)


def _rank_articles(articles: list[dict]) -> list[dict]:
    """Zoradí články podľa redakčnej relevancie, potom podľa čerstvosti."""
    return sorted(
        articles,
        key=lambda article: (_priority(article), float(article.get("ts", 0))),
        reverse=True,
    )


def _article_title(article: dict) -> str:
    title = escape(str(article.get("t", "")))
    url = _safe_url(article.get("l"))
    if url:
        return (
            f'<a href="{escape(url, quote=True)}" target="_blank" '
            f'rel="noopener">{title}</a>'
        )
    return title


def _render_featured(articles: list[dict]) -> str:
    if not articles:
        return '<div class="empty">Športový prehľad sa naplní po najbližšom úspešnom zbere.</div>'
    cards = []
    for rank, article in enumerate(articles[:5], start=1):
        css_class = "sport-topic sport-lead" if rank == 1 else "sport-topic sport-secondary"
        cards.append(
            f'<article class="{css_class}">'
            f'<div class="topic-rank">{rank:02d}</div><div class="topic-body">'
            f'<span class="topic-source">{escape(str(article.get("s", "Šport")))}</span>'
            f'<h2>{_article_title(article)}</h2>'
            f'<p>{escape(str(article.get("p", "")))}</p>'
            f'<span class="topic-time">{_ago(float(article.get("ts", 0)))}</span>'
            '</div></article>'
        )
    return '<div class="sport-board">' + ''.join(cards) + '</div>'


def _render_stream(articles: list[dict]) -> str:
    if not articles:
        return ''
    rows = []
    for article in sorted(articles, key=lambda item: -float(item.get("ts", 0))):
        ts = float(article.get("ts", 0))
        rows.append(
            '<article class="sport-row">'
            f'<time>{datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(_LOCAL_TZ).strftime("%H:%M")}</time>'
            f'<div><span class="source">{escape(str(article.get("s", "Šport")))}</span>'
            f'<h3>{_article_title(article)}</h3>'
            f'<p>{escape(str(article.get("p", "")))}</p></div>'
            f'<span class="age">{_ago(ts)}</span></article>'
        )
    return ''.join(rows)


def build_sport_html(state) -> str:
    articles = state.sport_recent_window(24)
    ranked = _rank_articles(articles)
    featured = ranked[:5]
    featured_ids = {str(article.get("u", "")) for article in featured}
    stream = [article for article in articles if str(article.get("u", "")) not in featured_ids]
    generated = datetime.now(timezone.utc).timestamp()
    return f"""<!doctype html>
<html lang="sk">
<head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="600"><title>Šport | SK News Agent</title>
  <style>
    :root {{ --forest:#123d2d; --green:#16824c; --green-strong:#0b6337; --green-soft:#e9f7ef; --ink:#13251d; --muted:#66766e; --line:#d7e3db; --canvas:#f5f8f6; --surface:#fff; }}
    * {{ box-sizing:border-box; }} html {{ scroll-behavior:smooth; }} body {{ margin:0; background:var(--canvas); color:var(--ink); font:16px/1.5 "IBM Plex Sans",Arial,sans-serif; }}
    header {{ background:var(--forest); color:white; }} .bar,main {{ max-width:1240px; margin:auto; padding-left:32px; padding-right:32px; }} .bar {{ min-height:70px; display:flex; align-items:center; gap:28px; }}
    .brand {{ font:700 22px Georgia,serif; white-space:nowrap; }} nav {{ display:flex; gap:24px; flex-wrap:wrap; }} nav a {{ color:#d8eadf; text-decoration:none; font-size:14px; }} nav a.active {{ color:#fff; font-weight:700; }}
    main {{ padding-top:40px; padding-bottom:58px; max-width:1080px; }} .eyebrow {{ color:var(--green); font:700 11px monospace; letter-spacing:.12em; text-transform:uppercase; }} h1 {{ font:700 38px/1.1 Georgia,serif; margin:4px 0 7px; }} .intro {{ margin:0 0 24px; color:var(--muted); }}
    .note {{ background:var(--green-soft); border-left:4px solid var(--green); padding:12px 16px; color:#24553b; font-size:14px; margin-bottom:30px; }}
    .section-head {{ display:flex; align-items:end; justify-content:space-between; gap:16px; margin:0 0 13px; }} .section-head h2 {{ margin:0; font:700 28px/1.15 Georgia,serif; }} .section-meta {{ font:12px monospace; color:var(--muted); white-space:nowrap; }}
    .sport-board {{ display:grid; grid-template-columns:1.05fr 1.55fr; border:1px solid var(--line); background:var(--surface); }} .sport-topic {{ display:grid; grid-template-columns:44px 1fr; gap:12px; padding:22px 20px; border-bottom:1px solid var(--line); }} .sport-lead {{ grid-row:span 4; background:var(--forest); color:#fff; padding:32px 28px; border:0; }} .sport-secondary:last-child {{ border-bottom:0; }}
    .topic-rank {{ color:var(--green); font:700 14px monospace; padding-top:4px; }} .sport-lead .topic-rank {{ color:#8ad2a5; }} .topic-source,.topic-time {{ display:block; font:12px monospace; }} .topic-source {{ color:var(--green); font-weight:700; }} .sport-lead .topic-source,.sport-lead .topic-time {{ color:#a7d9b6; }}
    .topic-body h2 {{ font:700 20px/1.2 Georgia,serif; margin:4px 0 6px; }} .sport-lead .topic-body h2 {{ font-size:34px; line-height:1.14; margin-top:18px; }} .topic-body h2 a {{ color:inherit; text-decoration:none; }} .topic-body h2 a:hover,.sport-row h3 a:hover {{ color:var(--green); text-decoration:underline; }} .sport-lead .topic-body h2 a:hover {{ color:#b9ebc8; }} .topic-body p {{ color:var(--muted); font-size:14px; margin:0 0 8px; }} .sport-lead .topic-body p {{ color:#e1f1e6; font-size:16px; margin:18px 0; }}
    .stream-section {{ margin-top:42px; }} .list {{ background:var(--surface); border:1px solid var(--line); }} .sport-row {{ display:grid; grid-template-columns:62px 1fr 82px; gap:18px; padding:18px 20px; border-bottom:1px solid var(--line); }} .sport-row:last-child {{ border-bottom:0; }} time,.age,.source {{ font:12px monospace; color:var(--muted); }} .source {{ color:var(--green); font-weight:700; }} .sport-row h3 {{ font:700 18px/1.25 Georgia,serif; margin:3px 0 5px; }} .sport-row h3 a {{ color:inherit; text-decoration:none; }} .sport-row p {{ color:var(--muted); font-size:14px; margin:0; }} .age {{ text-align:right; white-space:nowrap; }} .empty {{ background:var(--surface); border:1px solid var(--line); padding:26px; color:var(--muted); }}
    @media(max-width:760px) {{ .bar,main {{ padding-left:18px; padding-right:18px; }} .bar {{ padding-top:16px; padding-bottom:16px; align-items:flex-start; flex-direction:column; gap:10px; }} nav {{ gap:14px; }} h1 {{ font-size:31px; }} .sport-board {{ grid-template-columns:1fr; }} .sport-lead {{ grid-row:auto; padding:26px 20px; }} .sport-lead .topic-body h2 {{ font-size:28px; margin-top:12px; }} .sport-row {{ grid-template-columns:46px 1fr; gap:10px; padding:16px; }} .age {{ display:none; }} .section-head h2 {{ font-size:25px; }} }}
  </style>
</head>
<body data-ts="{generated:.6f}">
  <header><div class="bar"><div class="brand">SK News Agent</div><nav aria-label="Hlavná navigácia"><a href="index.html">Prehľad</a><a href="index.html#media-radar">Media Radar</a><a class="active" href="sport.html" aria-current="page">Šport</a><a href="audit.html">História výberov</a></nav></div></header>
  <main><div class="eyebrow">Športový radar · posledných 24 hodín</div><h1>Šport</h1><p class="intro">Výber najrelevantnejších športových správ a úplný pracovný tok pre redakciu.</p>
    <div class="note">Poradie je automatické a slúži iba tejto stránke: zvýhodňuje slovenskú relevanciu a veľké športové udalosti, nižšie radí live formáty, programy a kurzy. Športové témy naďalej môžu byť vybrané aj do Mimoriadne a Top tém.</div>
    <section aria-labelledby="featured-heading"><div class="section-head"><div><div class="eyebrow">Redakčný výber</div><h2 id="featured-heading">Sledovať</h2></div><span class="section-meta">Vybraných: {len(featured)}</span></div>{_render_featured(featured)}</section>
    <section class="stream-section" aria-labelledby="stream-heading"><div class="section-head"><div><div class="eyebrow">Úplný tok</div><h2 id="stream-heading">Najnovšie správy</h2></div><span class="section-meta">{len(stream)} ďalších</span></div><div class="list">{_render_stream(stream) or '<p class="empty">Žiadne ďalšie športové správy v tomto okne.</p>'}</div></section>
  </main>
  <script>(function () {{ var pageTimestamp=Number(document.body.getAttribute('data-ts'))||0; function checkForUpdate() {{ fetch('version.json?check='+Date.now(),{{cache:'no-store'}}).then(function(r){{return r.ok?r.json():null;}}).then(function(v){{if(v&&Number(v.generated_ts)>pageTimestamp)location.reload();}}).catch(function(){{}}); }} setInterval(checkForUpdate,60000); }})();</script>
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
