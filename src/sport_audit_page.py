"""Jednoduchý archív športových výberov pre GitHub Pages."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from html import escape
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from .config import ACTIVE_HOURS_TZ, SPORT_SELECTION_LOG_DIR
from .sport_selection_log import read_recent_sport_events

_OUTPUT_PATH = "docs/sport-audit.html"
_LOCAL_TZ = ZoneInfo(ACTIVE_HOURS_TZ)


def _fmt(ts: object) -> tuple[str, str]:
    try:
        value = datetime.fromtimestamp(float(ts), tz=timezone.utc).astimezone(_LOCAL_TZ)
        return value.strftime("%d.%m.%Y"), value.strftime("%H:%M:%S")
    except (TypeError, ValueError, OSError):
        return "—", "—"


def _link(url: object, title: object) -> str:
    parsed = urlparse(str(url or ""))
    text = escape(str(title or "Bez názvu"))
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return f'<a href="{escape(str(url), quote=True)}" target="_blank" rel="noopener">{text}</a>'
    return text


def _rows(events: list[dict]) -> str:
    result = []
    for event in events:
        date, time = _fmt(event.get("recorded_ts"))
        category = str(event.get("category", "sport_radar"))
        label = "Redakčný výber" if category == "redakcny_vyber" else "Šport Radar"
        reasons = "; ".join(str(item) for item in event.get("reasons", []) if item)
        result.append(
            f'<tr class="archive-row {escape(category, quote=True)}" '
            f'data-type="{escape(category, quote=True)}">'
            f'<td class="date-cell">{escape(date)}</td><td class="time-cell">{escape(time)}</td>'
            f'<td><span class="type-label">{label}</span></td>'
            f'<td class="title-cell">{_link(event.get("link"), event.get("title"))}</td>'
            f'<td class="detail-cell">{escape(str(event.get("perex", "")))}</td>'
            f'<td class="source-cell">{escape(str(event.get("source", "—")))}</td>'
            f'<td class="reason-cell">{escape(reasons)}</td></tr>'
        )
    return "".join(result)


def build_sport_audit_html(events: list[dict]) -> str:
    rows = _rows(events)
    row_count = len(events)
    featured_count = sum(event.get("category") == "redakcny_vyber" for event in events)
    radar_count = row_count - featured_count
    if not rows:
        rows = '<tr class="empty-row"><td colspan="7">Archív je zatiaľ prázdny. Prvé záznamy pribudnú po najbližšom športovom zbere.</td></tr>'
    generated = datetime.now(timezone.utc).astimezone(_LOCAL_TZ).strftime("%H:%M:%S · %d.%m.%Y")
    return f"""<!DOCTYPE html>
<html lang="sk"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;700&family=IBM+Plex+Sans:wght@400;500;600;700&family=Newsreader:opsz,wght@6..72,600;6..72,700&display=swap" rel="stylesheet">
<title>SK News Agent — História športu</title><style>
:root{{--canvas:#F5F8F6;--surface:#FFF;--text:#13251D;--forest:#123D2D;--green:#16824C;--green-soft:#E9F7EF;--muted:#66766E;--rule:#D7E3DB;--rule-strong:#C4D5CA}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--canvas);color:var(--text);font:15px/1.45 "IBM Plex Sans",Arial,sans-serif;-webkit-font-smoothing:antialiased}}a{{color:var(--green);text-decoration:none}}a:hover,a:focus-visible{{text-decoration:underline}}button:focus-visible,a:focus-visible{{outline:3px solid rgba(22,130,76,.25);outline-offset:3px}}.site-header{{background:var(--forest);color:#fff}}.header-inner{{max-width:1380px;min-height:64px;margin:0 auto;padding:0 30px;display:grid;grid-template-columns:auto minmax(0,1fr) auto;align-items:center;gap:38px}}.masthead{{font:700 23px "Newsreader",Georgia,serif;letter-spacing:-.025em;white-space:nowrap}}.masthead b{{color:#A6DEC0;margin-left:8px;padding-left:10px;border-left:1px solid rgba(255,255,255,.28);font:500 13px "IBM Plex Sans",sans-serif;letter-spacing:.02em;text-transform:uppercase}}nav{{display:flex;gap:6px}}nav a{{display:inline-flex;align-items:center;min-height:64px;padding:0 13px;color:#D8EADF;font-size:13px;border-bottom:3px solid transparent}}nav a:hover,nav a:focus-visible{{color:#fff;border-bottom-color:#83D7A8;text-decoration:none}}nav a.active{{color:#fff;border-bottom-color:#83D7A8}}.updated{{color:#B5D0C0;font:10.5px "IBM Plex Mono",monospace;white-space:nowrap}}main{{max-width:1380px;margin:0 auto;padding:30px 30px 60px}}.page-head{{display:flex;justify-content:space-between;align-items:flex-end;gap:24px;margin-bottom:18px}}.eyebrow{{color:var(--green);font:700 10px "IBM Plex Mono",monospace;letter-spacing:.14em;text-transform:uppercase}}h1{{font:700 34px "Newsreader",Georgia,serif;letter-spacing:-.025em;margin:2px 0 3px}}.intro{{color:var(--muted);margin:0;max-width:760px;font-size:13.5px}}.archive-count{{color:var(--muted);font:11px "IBM Plex Mono",monospace}}.toolbar{{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap;margin-bottom:14px}}.filters{{display:flex;gap:7px;flex-wrap:wrap}}button{{cursor:pointer;border:1px solid var(--rule-strong);background:var(--surface);color:var(--muted);font:500 12px "IBM Plex Sans",sans-serif}}.filters button{{min-height:34px;padding:6px 12px;border-radius:999px}}.filters button span{{color:#84948B;margin-left:4px;font-size:10px}}.filters button:hover{{color:var(--green);border-color:#9BCEAE}}.filters button.active{{color:#fff;background:var(--green);border-color:var(--green)}}.filters button.active span{{color:#D8F1E2}}.copy-button{{min-height:36px;padding:7px 12px;border-radius:3px;color:var(--green)}}.copy-button:hover{{background:var(--green-soft);border-color:#9BCEAE}}.copy-button.copied{{color:#146C3F;background:#E1F4E8;border-color:#9BCEAE}}.table-hint{{display:none;color:var(--muted);font-size:11.5px;margin:0 0 7px}}.table-wrap{{overflow:auto;background:var(--surface);border:1px solid var(--rule-strong)}}table{{width:100%;min-width:1120px;border-collapse:collapse;table-layout:fixed;font-size:12.5px}}col.date{{width:92px}}col.time{{width:78px}}col.type{{width:130px}}col.title{{width:27%}}col.detail{{width:32%}}col.source{{width:118px}}col.reason{{width:20%}}thead{{position:sticky;top:0;z-index:1}}th{{padding:10px 12px;background:var(--forest);color:#E2F0E7;border-right:1px solid #2A5A45;text-align:left;font:600 10.5px "IBM Plex Sans",sans-serif;letter-spacing:.06em;text-transform:uppercase}}th:last-child{{border-right:0}}td{{padding:10px 12px;border-bottom:1px solid var(--rule);vertical-align:top;overflow-wrap:anywhere}}tbody tr:hover{{background:#F7FBF8}}.archive-row[hidden]{{display:none}}.date-cell,.time-cell{{color:var(--muted);font:11px "IBM Plex Mono",monospace;white-space:nowrap}}.type-label{{color:var(--green);font-size:11px;font-weight:700;white-space:nowrap}}.title-cell{{font-weight:600}}.detail-cell,.reason-cell{{color:#526A5E}}.source-cell{{color:var(--green);font:500 11px "IBM Plex Mono",monospace;white-space:nowrap}}.empty-row td{{padding:30px;color:var(--muted);text-align:center;font-style:italic}}.no-results{{padding:24px;color:var(--muted);text-align:center;font-size:13px}}@media(max-width:900px){{.header-inner{{grid-template-columns:auto 1fr;gap:20px}}.updated{{display:none}}nav{{justify-self:end}}}}@media(max-width:680px){{.header-inner{{min-height:0;padding:13px 17px 0;display:block}}.masthead{{font-size:20px}}nav{{margin-top:7px;overflow-x:auto}}nav a{{min-height:42px;padding:0 8px;font-size:12px;white-space:nowrap}}main{{padding:22px 14px 40px}}.page-head{{display:block}}h1{{font-size:30px}}.archive-count{{display:block;margin-top:8px}}.copy-button{{width:100%}}.table-hint{{display:block}}.table-wrap{{margin-left:-14px;margin-right:-14px;border-left:0;border-right:0}}}}
</style></head><body><header class="site-header"><div class="header-inner"><div class="masthead">SK News Agent <b>Šport</b></div><nav aria-label="Hlavná navigácia"><a href="index.html#top-temy">Prehľad</a><a href="index.html#media-radar">Media Radar</a><a href="sport.html">Šport</a><a class="active" href="sport-audit.html" aria-current="page">História športu</a><a href="audit.html">História výberov</a></nav><div class="updated">Aktualizované {generated}</div></div></header><main><div class="page-head"><div><div class="eyebrow">Archív športových výberov</div><h1>História športových výberov</h1><p class="intro">Jednoduchý chronologický zoznam správ zachytených športovým modulom. Čas označuje moment, keď systém výber zaznamenal.</p></div><span class="archive-count"><span id="visible-count">{row_count}</span> záznamov</span></div><div class="toolbar"><div class="filters" aria-label="Filtrovanie záznamov"><button class="active" type="button" data-filter="all" aria-pressed="true">Všetko <span>{row_count}</span></button><button type="button" data-filter="redakcny_vyber" aria-pressed="false">Redakčný výber <span>{featured_count}</span></button><button type="button" data-filter="sport_radar" aria-pressed="false">Šport Radar <span>{radar_count}</span></button></div><button class="copy-button" type="button">Kopírovať zobrazené do Excelu</button></div><p class="table-hint">Potiahnutím tabuľky doľava zobrazíte ďalšie stĺpce.</p><div class="table-wrap"><table id="archive-table"><colgroup><col class="date"><col class="time"><col class="type"><col class="title"><col class="detail"><col class="source"><col class="reason"></colgroup><thead><tr><th>Dátum</th><th>Čas</th><th>Kategória</th><th>Téma</th><th>Popis</th><th>Vydavateľ</th><th>Dôvod výberu</th></tr></thead><tbody>{rows}</tbody></table></div><div class="no-results" hidden>V tejto kategórii nie sú žiadne záznamy.</div></main><script>(function(){{var buttons=[].slice.call(document.querySelectorAll('[data-filter]')),rows=[].slice.call(document.querySelectorAll('.archive-row')),visibleCount=document.getElementById('visible-count'),noResults=document.querySelector('.no-results'),copyButton=document.querySelector('.copy-button');buttons.forEach(function(button){{button.addEventListener('click',function(){{var filter=button.getAttribute('data-filter'),shown=0;buttons.forEach(function(item){{var active=item===button;item.classList.toggle('active',active);item.setAttribute('aria-pressed',active?'true':'false');}});rows.forEach(function(row){{row.hidden=filter!=='all'&&row.getAttribute('data-type')!==filter;if(!row.hidden)shown+=1;}});visibleCount.textContent=String(shown);noResults.hidden=shown>0;}});}});function copyText(value){{if(navigator.clipboard&&navigator.clipboard.writeText)return navigator.clipboard.writeText(value);var area=document.createElement('textarea');area.value=value;area.style.position='fixed';area.style.opacity='0';document.body.appendChild(area);area.select();document.execCommand('copy');area.remove();return Promise.resolve();}}copyButton.addEventListener('click',function(){{var headers=[].slice.call(document.querySelectorAll('#archive-table th')).map(function(cell){{return cell.innerText.trim();}}),visibleRows=rows.filter(function(row){{return !row.hidden;}}),lines=[headers].concat(visibleRows.map(function(row){{return [].slice.call(row.cells).map(function(cell){{return cell.innerText.replace(/\\s+/g,' ').trim();}});}})),tsv=lines.map(function(line){{return line.join('\t');}}).join('\n');copyText(tsv).then(function(){{copyButton.textContent='Skopírované';copyButton.classList.add('copied');window.setTimeout(function(){{copyButton.textContent='Kopírovať zobrazené do Excelu';copyButton.classList.remove('copied');}},1800);}});}});}})();</script></body></html>"""


def write_sport_audit_page(output_path: str = _OUTPUT_PATH) -> None:
    try:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        tmp = output_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(build_sport_audit_html(read_recent_sport_events(SPORT_SELECTION_LOG_DIR)))
        os.replace(tmp, output_path)
    except OSError:
        return
