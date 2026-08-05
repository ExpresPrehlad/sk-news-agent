"""Statická história športovej prioritizácie s exportom do Excelu."""

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
            f'<tr class="sport-audit-row" data-category="{escape(category, quote=True)}" '
            f'data-source="{escape(str(event.get("source", "")), quote=True)}">'
            f'<td>{escape(date)}</td><td>{escape(time)}</td>'
            f'<td>{escape(str(event.get("source", "—")))}</td>'
            f'<td><span class="category {escape(category, quote=True)}">{label}</span></td>'
            f'<td class="score">{escape(str(event.get("score", 0)))}</td>'
            f'<td>{escape(reasons)}</td><td class="title">{_link(event.get("link"), event.get("title"))}</td>'
            f'<td>{escape(str(event.get("perex", "")))}</td></tr>'
        )
    return "".join(result)


def build_sport_audit_html(events: list[dict]) -> str:
    rows = _rows(events)
    sources = sorted({str(event.get("source", "")) for event in events if event.get("source")})
    featured_count = sum(event.get("category") == "redakcny_vyber" for event in events)
    if not rows:
        rows = '<tr><td colspan="8" class="empty">Záznamy pribudnú po najbližšom športovom zbere.</td></tr>'
    source_buttons = "".join(
        f'<button data-source-filter="{escape(source, quote=True)}">{escape(source)}</button>'
        for source in sources
    )
    generated = datetime.now(timezone.utc).astimezone(_LOCAL_TZ).strftime("%H:%M · %d.%m.%Y")
    return f"""<!doctype html><html lang="sk"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>História športu | SK News Agent</title>
<style>
:root{{--forest:#123d2d;--green:#16824c;--soft:#e9f7ef;--ink:#13251d;--muted:#66766e;--line:#d7e3db;--canvas:#f5f8f6;--surface:#fff}}*{{box-sizing:border-box}}body{{margin:0;background:var(--canvas);color:var(--ink);font:15px/1.45 Arial,sans-serif}}header{{background:var(--forest);color:#fff}}.bar,main{{max-width:1240px;margin:auto;padding-left:32px;padding-right:32px}}.bar{{min-height:70px;display:flex;align-items:center;gap:28px}}.brand{{font:700 22px Georgia,serif}}nav{{display:flex;gap:20px;flex-wrap:wrap}}nav a{{color:#d8eadf;text-decoration:none;font-size:14px}}nav a.active{{color:#fff;font-weight:700}}main{{padding-top:38px;padding-bottom:60px}}.eyebrow{{color:var(--green);font:700 11px monospace;letter-spacing:.12em;text-transform:uppercase}}h1{{font:700 36px/1.1 Georgia,serif;margin:4px 0 8px}}.intro{{color:var(--muted);max-width:760px;margin:0 0 24px}}.toolbar{{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 14px}}button{{border:1px solid var(--line);background:var(--surface);color:var(--muted);border-radius:999px;padding:7px 12px;cursor:pointer}}button.active{{background:var(--green);border-color:var(--green);color:#fff;font-weight:700}}.export{{margin-left:auto;border-radius:4px;color:var(--green);font-weight:700}}.table-wrap{{overflow:auto;background:var(--surface);border:1px solid var(--line)}}table{{border-collapse:collapse;width:100%;min-width:1180px;font-size:13px}}th{{background:var(--forest);color:#e6f2ea;text-align:left;padding:10px;white-space:nowrap;font-size:11px;text-transform:uppercase;letter-spacing:.06em}}td{{padding:10px;border-bottom:1px solid var(--line);vertical-align:top}}tr:hover{{background:#f7fbf8}}td:nth-child(1),td:nth-child(2),td:nth-child(3),.score{{white-space:nowrap;font:12px monospace;color:var(--muted)}}.title{{font-weight:700}}a{{color:var(--green-strong,#0b6337);text-decoration:none}}a:hover{{text-decoration:underline}}.category{{font-size:11px;font-weight:700;white-space:nowrap;color:var(--green)}}.category.redakcny_vyber{{color:#0b6337}}.empty{{padding:28px;text-align:center;color:var(--muted)}}.no-results{{padding:18px;color:var(--muted)}}@media(max-width:700px){{.bar,main{{padding-left:18px;padding-right:18px}}.bar{{padding-top:16px;padding-bottom:16px;align-items:flex-start;flex-direction:column;gap:10px}}h1{{font-size:30px}}.export{{margin-left:0}}}}
</style></head><body><header><div class="bar"><div class="brand">SK News Agent</div><nav><a href="index.html">Prehľad</a><a href="index.html#media-radar">Media Radar</a><a href="sport.html">Šport</a><a class="active" href="sport-audit.html">História športu</a><a href="audit.html">História výberov</a></nav></div></header><main><div class="eyebrow">Audit športovej prioritizácie</div><h1>História športových výberov</h1><p class="intro">Každá nová športová správa je zaznamenaná s vydavateľom, skóre, dôvodom a výsledkom prioritizácie. Export CSV otvoríte priamo v Exceli.</p><div class="toolbar"><button class="active" data-category-filter="all">Všetko ({len(events)})</button><button data-category-filter="redakcny_vyber">Redakčný výber ({featured_count})</button><button data-category-filter="sport_radar">Šport Radar ({len(events)-featured_count})</button>{source_buttons}<button class="export" type="button">Stiahnuť CSV pre Excel</button></div><div class="table-wrap"><table id="sport-audit"><thead><tr><th>Dátum</th><th>Čas</th><th>Vydavateľ</th><th>Výsledok</th><th>Skóre</th><th>Dôvod</th><th>Téma</th><th>Popis</th></tr></thead><tbody>{rows}</tbody></table></div><div class="no-results" hidden>Pre tento filter nie sú žiadne záznamy.</div></main><script>(function(){{var rows=[].slice.call(document.querySelectorAll('.sport-audit-row')),category='all',source='all',buttons=[].slice.call(document.querySelectorAll('[data-category-filter],[data-source-filter]')),empty=document.querySelector('.no-results');function apply(){{var shown=0;rows.forEach(function(row){{var visible=(category==='all'||row.dataset.category===category)&&(source==='all'||row.dataset.source===source);row.hidden=!visible;if(visible)shown++;}});empty.hidden=shown>0;}}buttons.forEach(function(button){{button.addEventListener('click',function(){{if(button.dataset.categoryFilter!==undefined)category=button.dataset.categoryFilter;else source=button.dataset.sourceFilter;buttons.forEach(function(item){{var active=(item.dataset.categoryFilter===category)||(item.dataset.sourceFilter===source);item.classList.toggle('active',active);}});apply();}});}});document.querySelector('.export').addEventListener('click',function(){{var lines=[['Dátum','Čas','Vydavateľ','Výsledok','Skóre','Dôvod','Téma','Popis']];rows.filter(function(row){{return !row.hidden;}}).forEach(function(row){{lines.push([].slice.call(row.cells).map(function(cell){{return cell.innerText.trim();}}));}});var csv='\uFEFF'+lines.map(function(line){{return line.map(function(value){{return '"'+value.replace(/"/g,'""')+'"';}}).join(';');}}).join('\r\n');var url=URL.createObjectURL(new Blob([csv],{{type:'text/csv;charset=utf-8;'}})),link=document.createElement('a');link.href=url;link.download='historia-sportovych-vyberov.csv';link.style.display='none';document.body.appendChild(link);link.click();setTimeout(function(){{URL.revokeObjectURL(url);link.remove();}},1000);}});apply();}})();</script></body></html>"""


def write_sport_audit_page(output_path: str = _OUTPUT_PATH) -> None:
    try:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        tmp = output_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(build_sport_audit_html(read_recent_sport_events(SPORT_SELECTION_LOG_DIR)))
        os.replace(tmp, output_path)
    except OSError:
        # Audit nesmie zablokovať zber správ.
        return
