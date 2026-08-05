"""Statická podstránka s prioritizovaným športovým prehľadom."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from html import escape, unescape
import re
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from .config import ACTIVE_HOURS_TZ

_OUTPUT_PATH = "docs/sport.html"
_LOCAL_TZ = ZoneInfo(ACTIVE_HOURS_TZ)
log = logging.getLogger(__name__)

# Prísny filter pre Redakčný výber. Slúži len športovej stránke; nikdy
# nevstupuje do Mimoriadne, Top tém ani do LLM výberu.
_SLOVAK_SIGNAL = (
    "slovensko", "slovensk", "slováci", "slovák", "reprezentácia",
    "bratislav", "košic", "žilina", "trnava", "nitra", "trenčín",
    "prešov", "poprad", "banská bystrica",
)
_GLOBAL_EVENT_SIGNAL = (
    "olympi", "majstrovstv sveta", "world championship", "liga majstrov",
    "champions league", "wimbledon", "roland garros", "us open",
    "australian open", "super bowl", "formula 1", "veľká cena", "grand prix",
    "finále nba", "finále nhl", "futbalové euro", "euro 20",
)
_HIGH_SIGNAL = _SLOVAK_SIGNAL + _GLOBAL_EVENT_SIGNAL + ("rekord",)
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


def _is_featured(article: dict) -> bool:
    """Určí, či článok patrí do prísneho redakčného výberu."""
    text = " ".join((str(article.get("t", "")), str(article.get("p", "")))).lower()
    # Prevádzkové formáty nie sú samostatnou redakčnou témou, ani pri veľkej súťaži.
    if any(keyword in text for keyword in _LOW_SIGNAL):
        return False
    # Domáca udalosť alebo preukázateľná väzba na Slovensko má prednosť.
    if any(keyword in text for keyword in _SLOVAK_SIGNAL):
        return True
    # Zahraničný obsah sa vyberá iba pri rekorde alebo konkrétnom globálnom podujatí.
    return "rekord" in text or any(keyword in text for keyword in _GLOBAL_EVENT_SIGNAL)


def _rank_articles(articles: list[dict]) -> list[dict]:
    """Zoradí články podľa redakčnej relevancie, potom podľa čerstvosti."""
    return sorted(
        articles,
        key=lambda article: (_priority(article), float(article.get("ts", 0))),
        reverse=True,
    )


def _featured_articles(articles: list[dict]) -> list[dict]:
    return [article for article in _rank_articles(articles) if _is_featured(article)][:5]


def _article_title(article: dict) -> str:
    title = _display_text(article.get("t", ""), article.get("s", ""))
    title = escape(title)
    url = _safe_url(article.get("l"))
    if url:
        return (
            f'<a href="{escape(url, quote=True)}" target="_blank" '
            f'rel="noopener">{title}</a>'
        )
    return title


def _display_text(value: object, source: object = "") -> str:
    """Opraví staršie Google News záznamy ešte pred ich zobrazením."""
    text = " ".join(unescape(str(value or "")).split()).strip()
    source_name = str(source or "").strip()
    if source_name:
        text = re.sub(
            rf"\s*(?:[-–—]\s*)?{re.escape(source_name)}\s*$", "", text,
            flags=re.IGNORECASE,
        ).strip()
    return text


def _render_featured(articles: list[dict]) -> str:
    if not articles:
        return '<div class="empty">V tomto okne zatiaľ nie je téma, ktorá spĺňa kritériá redakčného výberu.</div>'
    cards = []
    for rank, article in enumerate(articles[:5], start=1):
        css_class = "sport-topic sport-lead" if rank == 1 else "sport-topic sport-secondary"
        cards.append(
            f'<article class="{css_class}">'
            f'<div class="topic-rank">{rank:02d}</div><div class="topic-body">'
            f'<span class="topic-source">{escape(str(article.get("s", "Šport")))}</span>'
            f'<h2>{_article_title(article)}</h2>'
            f'<p>{escape(_display_text(article.get("p", ""), article.get("s", "")))}</p>'
            f'<span class="topic-time">{_ago(float(article.get("ts", 0)))}</span>'
            '</div></article>'
        )
    return '<div class="sport-board">' + ''.join(cards) + '</div>'


def _render_sport_radar(articles: list[dict]) -> str:
    if not articles:
        return '<div class="empty">Zatiaľ žiadne športové správy v tomto okne.</div>'
    sorted_articles = sorted(articles, key=lambda item: -float(item.get("ts", 0)))
    source_counts: dict[str, int] = {}
    for article in sorted_articles:
        source = str(article.get("s", "Šport"))
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
    rows = []
    for index, article in enumerate(sorted_articles):
        ts = float(article.get("ts", 0))
        rows.append(
            f'<li class="sport-row" data-source="{escape(str(article.get("s", "Šport")), quote=True)}" '
            f'data-radar-index="{index}">'
            f'<time>{datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(_LOCAL_TZ).strftime("%H:%M")}</time>'
            f'<div><span class="source">{escape(str(article.get("s", "Šport")))}</span>'
            f'<h3>{_article_title(article)}</h3>'
            f'<p>{escape(_display_text(article.get("p", ""), article.get("s", "")))}</p></div>'
            f'<span class="age">{_ago(ts)}</span></li>'
        )
    return (
        '<div class="radar-filters" aria-label="Filtrovať podľa vydavateľa">'
        + ''.join(filters) + '</div><ol class="sport-list">' + ''.join(rows)
        + '</ol><button class="radar-more" type="button">Zobraziť ďalšie správy</button>'
        + '<div class="radar-empty" hidden>Pre tohto vydavateľa nie sú v okne žiadne správy.</div>'
    )


def build_sport_html(state, generated_at: datetime | None = None) -> str:
    articles = state.sport_recent_window(24)
    ranked = _rank_articles(articles)
    featured = _featured_articles(ranked)
    # Články majú stabilné UID z collectora. Porovnanie objektov je poistka pre
    # ručne vytvorený alebo neúplný záznam bez UID.
    featured_ids = {str(article["u"]) for article in featured if article.get("u")}
    stream = [
        article for article in articles
        if str(article.get("u", "")) not in featured_ids and article not in featured
    ]
    now = generated_at or datetime.now(timezone.utc)
    generated = now.timestamp()
    generated_ts_ms = int(generated * 1000)
    generated_label = now.astimezone(_LOCAL_TZ).strftime("%H:%M:%S · %d.%m.%Y")
    return f"""<!doctype html>
<html lang="sk">
<head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="600"><title>Šport | SK News Agent</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;700&family=IBM+Plex+Sans:wght@400;500;600;700&family=Newsreader:opsz,wght@6..72,600;6..72,700&display=swap" rel="stylesheet">
  <style>
    :root {{ --forest:#123d2d; --green:#16824c; --green-strong:#0b6337; --green-soft:#e9f7ef; --ink:#13251d; --muted:#66766e; --line:#d7e3db; --canvas:#f5f8f6; --surface:#fff; }}
    * {{ box-sizing:border-box; }} html {{ scroll-behavior:smooth; }} body {{ margin:0; background:var(--canvas); color:var(--ink); font-family:"IBM Plex Sans",-apple-system,sans-serif; line-height:1.45; -webkit-font-smoothing:antialiased; }}
    header {{ background:var(--forest); color:white; }} .bar,main {{ max-width:1380px; margin:auto; padding-left:30px; padding-right:30px; }} .bar {{ min-height:64px; display:grid; grid-template-columns:auto minmax(0,1fr) auto; align-items:center; gap:38px; }}
    .brand {{ font:700 23px "Newsreader",Georgia,serif; letter-spacing:-.025em; white-space:nowrap; }} nav {{ display:flex; gap:6px; flex-wrap:wrap; }} nav a {{ display:inline-flex; align-items:center; min-height:64px; padding:0 13px; color:#d8eadf; text-decoration:none; font-size:13px; border-bottom:3px solid transparent; }} nav a:hover,nav a:focus-visible {{ color:#fff; border-bottom-color:#83d7a8; }} nav a.active {{ color:#fff; border-bottom-color:#83d7a8; font-weight:700; }}
    .updated {{ color:#b5d0c0; font:10.5px "IBM Plex Mono",monospace; white-space:nowrap; }} .updated .stale-warning {{ color:#ffb4a9; font-weight:700; }}
    main {{ padding-top:22px; padding-bottom:42px; }} .eyebrow {{ color:var(--green); font-family:"IBM Plex Mono",monospace; font-size:11px; font-weight:700; letter-spacing:.14em; text-transform:uppercase; }}
    .section-head {{ display:flex; align-items:end; justify-content:space-between; gap:16px; margin:0; }} .section-head h2 {{ margin:0; font-family:"Newsreader",Georgia,serif; font-size:29px; line-height:1.1; font-weight:700; letter-spacing:-.025em; }} .section-meta {{ font:11px "IBM Plex Mono",monospace; color:var(--muted); white-space:nowrap; }}
    .sport-board {{ min-height:400px; display:grid; grid-template-columns:minmax(360px,.9fr) minmax(520px,1.35fr); grid-template-rows:repeat(4,minmax(91px,auto)); border:1px solid var(--line); background:var(--surface); }} .sport-topic {{ display:grid; grid-template-columns:34px minmax(0,1fr); gap:8px; padding:12px 20px; align-items:center; border-bottom:1px solid var(--line); }} .sport-lead {{ grid-column:1; grid-row:1 / 5; align-content:center; gap:10px; padding:30px; background:var(--forest); color:#fff; border:0; }} .sport-secondary {{ grid-column:2; }} .sport-secondary:last-child {{ border-bottom:0; }}
    .topic-rank {{ color:var(--green); font:700 14px monospace; padding-top:4px; }} .sport-lead .topic-rank {{ color:#8ad2a5; }} .topic-source,.topic-time {{ display:block; font:12px monospace; }} .topic-source {{ color:var(--green); font-weight:700; }} .sport-lead .topic-source,.sport-lead .topic-time {{ color:#a7d9b6; }}
    .topic-body h2 {{ font-family:"Newsreader",Georgia,serif; font-size:19.5px; line-height:1.23; font-weight:700; letter-spacing:-.015em; margin:0 0 3px; display:-webkit-box; -webkit-box-orient:vertical; -webkit-line-clamp:2; overflow:hidden; }} .sport-lead .topic-body h2 {{ color:#fff; font-size:clamp(27px,2.35vw,38px); line-height:1.08; margin:0 0 15px; -webkit-line-clamp:4; }} .topic-body h2 a {{ color:inherit; text-decoration:none; }} .topic-body h2 a:hover,.sport-row h3 a:hover {{ color:var(--green); text-decoration:none; }} .sport-lead .topic-body h2 a:hover {{ color:#b9ebc8; }} .topic-body p {{ color:var(--muted); font-size:13.5px; line-height:1.35; margin:0 0 4px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }} .sport-lead .topic-body p {{ color:#cfe3d6; font-size:16px; line-height:1.5; margin:0 0 18px; display:-webkit-box; -webkit-box-orient:vertical; -webkit-line-clamp:4; white-space:normal; }}
    .stream-section {{ margin-top:32px; }} .stream-section .section-head {{ padding-bottom:12px; border-bottom:2px solid var(--forest); }} .radar-filters {{ display:flex; flex-wrap:wrap; gap:8px; margin:0 0 14px; }} .radar-filter {{ appearance:none; border:1px solid var(--line); border-radius:999px; background:var(--surface); color:var(--muted); cursor:pointer; padding:8px 12px; font:12px/1 "IBM Plex Sans",Arial,sans-serif; }} .radar-filter span {{ font:11px "IBM Plex Mono",monospace; margin-left:4px; }} .radar-filter:hover,.radar-filter:focus-visible {{ border-color:var(--green); color:var(--green-strong); }} .radar-filter.is-active {{ color:#fff; background:var(--green); border-color:var(--green); font-weight:700; }} .sport-list {{ list-style:none; margin:0; padding:0; background:var(--surface); border:1px solid var(--line); }} .sport-row {{ display:grid; grid-template-columns:62px minmax(0,1fr) 82px; gap:18px; padding:15px 18px; border-bottom:1px solid var(--line); }} .sport-row[hidden] {{ display:none; }} .sport-row:last-child {{ border-bottom:0; }} time,.age,.source {{ font:11px "IBM Plex Mono",monospace; color:var(--muted); }} .source {{ color:var(--green); font-weight:700; }} .sport-row h3 {{ font:700 18px/1.2 "Newsreader",Georgia,serif; margin:3px 0 4px; }} .sport-row h3 a {{ color:inherit; text-decoration:none; }} .sport-row p {{ color:var(--muted); font-size:13.5px; margin:0; }} .age {{ text-align:right; white-space:nowrap; }} .radar-more {{ display:block; margin:14px auto 0; border:0; background:none; color:var(--green-strong); cursor:pointer; font:700 13px "IBM Plex Sans",Arial,sans-serif; }} .radar-empty {{ padding:20px; background:var(--surface); border:1px solid var(--line); color:var(--muted); }} .empty {{ background:var(--surface); border:1px solid var(--line); padding:26px; color:var(--muted); }}
    @media(max-width:900px) {{ .bar {{ grid-template-columns:auto 1fr; gap:20px; }} .updated {{ display:none; }} nav {{ justify-self:end; }} }}
    @media(max-width:760px) {{ .bar,main {{ padding-left:18px; padding-right:18px; }} .bar {{ min-height:0; padding-top:14px; display:block; }} nav {{ margin-top:7px; overflow-x:auto; flex-wrap:nowrap; }} nav a {{ min-height:42px; padding:0 8px; white-space:nowrap; }} main {{ padding-top:22px; }} .sport-board {{ min-height:0; grid-template-columns:1fr; grid-template-rows:auto; }} .sport-lead,.sport-secondary {{ grid-column:1; grid-row:auto; }} .sport-lead {{ padding:26px 20px; }} .sport-lead .topic-body h2 {{ font-size:29px; }} .sport-row {{ grid-template-columns:46px minmax(0,1fr); gap:10px; padding:15px; }} .age {{ display:none; }} .section-head h2 {{ font-size:26px; }} }}
  </style>
</head>
<body data-ts="{generated:.6f}">
  <header><div class="bar"><div class="brand">SK News Agent</div><nav aria-label="Hlavná navigácia"><a href="index.html">Prehľad</a><a href="index.html#media-radar">Media Radar</a><a class="active" href="sport.html" aria-current="page">Šport</a><a href="sport-audit.html">História športu</a><a href="audit.html">História výberov</a></nav><div class="updated">Aktualizované {generated_label} <span id="live-ago" data-ts="{generated_ts_ms}"></span></div></div></header>
  <main><section aria-labelledby="featured-heading"><div class="section-head"><div><div class="eyebrow">Redakčný výber</div><h2 id="featured-heading">Top športové témy</h2></div></div>{_render_featured(featured)}</section>
    <section class="stream-section" aria-labelledby="radar-heading"><div class="section-head"><div><div class="eyebrow">Posledných 24 hodín</div><h2 id="radar-heading">Šport Radar</h2></div><span class="section-meta">{len(stream)} správ</span></div>{_render_sport_radar(stream)}</section>
  </main>
  <script>(function () {{ var pageTimestamp=Number(document.body.getAttribute('data-ts'))||0; var ago=document.getElementById('live-ago'); function tick() {{ if(!ago)return; var mins=Math.max(0,Math.floor((Date.now()-Number(ago.getAttribute('data-ts')))/60000)); var text=mins<1?'práve teraz':mins<60?('pred '+mins+' min'):('pred '+(mins/60).toFixed(1)+' h'); ago.textContent='('+text+')'; ago.classList.toggle('stale-warning',mins>60); }} tick(); setInterval(tick,30000); var limit=18; var expanded=false; function activeFilter() {{ var active=document.querySelector('.radar-filter.is-active'); return active?active.getAttribute('data-filter'):'all'; }} function matchingRows() {{ var filter=activeFilter(); return Array.prototype.slice.call(document.querySelectorAll('.sport-row')).filter(function(row) {{ return filter==='all'||row.getAttribute('data-source')===filter; }}); }} function renderRows() {{ var rows=matchingRows(); rows.forEach(function(row,index) {{ row.hidden=!expanded&&index>=limit; }}); Array.prototype.slice.call(document.querySelectorAll('.sport-row')).forEach(function(row) {{ if(rows.indexOf(row)===-1) row.hidden=true; }}); var empty=document.querySelector('.radar-empty'); if(empty) empty.hidden=rows.length>0; var more=document.querySelector('.radar-more'); if(more) more.hidden=expanded||rows.length<=limit; }} Array.prototype.forEach.call(document.querySelectorAll('.radar-filter'),function(button) {{ button.addEventListener('click',function() {{ Array.prototype.forEach.call(document.querySelectorAll('.radar-filter'),function(item) {{ item.classList.remove('is-active'); item.setAttribute('aria-pressed','false'); }}); button.classList.add('is-active'); button.setAttribute('aria-pressed','true'); expanded=false; renderRows(); }}); }}); var more=document.querySelector('.radar-more'); if(more) more.addEventListener('click',function() {{ expanded=true; renderRows(); }}); renderRows(); function checkForUpdate() {{ fetch('version.json?check='+Date.now(),{{cache:'no-store'}}).then(function(r){{return r.ok?r.json():null;}}).then(function(v){{if(v&&Number(v.generated_ts)>pageTimestamp)location.reload();}}).catch(function(){{}}); }} setInterval(checkForUpdate,60000); }})();</script>
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
