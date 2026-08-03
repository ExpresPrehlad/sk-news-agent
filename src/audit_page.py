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

def _fmt_datetime_parts(ts: float) -> tuple[str, str, str]:
    try:
        value = datetime.fromtimestamp(
            float(ts), tz=timezone.utc
        ).astimezone(_LOCAL_TZ)
        return (
            value.strftime("%d.%m.%Y"),
            value.strftime("%H:%M:%S"),
            value.isoformat(),
        )
    except (TypeError, ValueError, OSError):
        return ("—", "—", "")


def _safe_link(url: str, label: str) -> str:
    parsed = urlparse(str(url))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return (
        f'<a href="{escape(str(url), quote=True)}" target="_blank" '
        f'rel="noopener">{escape(label)} →</a>'
    )


def _render_source_links(item: dict) -> str:
    links = []
    for link in item.get("links") or []:
        if isinstance(link, dict):
            rendered = _safe_link(link.get("url", ""), link.get("source", "zdroj"))
        else:
            rendered = _safe_link(str(link), "zdroj")
        if rendered:
            links.append(rendered)
    return '<span class="source-separator"> · </span>'.join(links) or "—"


def _render_event_rows(event: dict) -> str:
    event_type = event.get("event_type")
    selected = event.get("selected")
    if not isinstance(selected, list) or not selected:
        return ""

    rows = []
    date_label, time_label, datetime_value = _fmt_datetime_parts(
        event.get("recorded_ts", 0)
    )
    is_triage = event_type == "triage"
    type_label = "Mimoriadne" if is_triage else "Top téma"
    css_type = "triage" if is_triage else "synthesis"
    published = bool(event.get("published"))
    status_label = "Publikované" if published else "Nepublikované"
    status_class = "published" if published else "unpublished"
    for item in selected:
        if not isinstance(item, dict):
            continue
        title = item.get("title") if is_triage else item.get("headline")
        detail = item.get("reason") if is_triage else item.get("perex")
        source_links = _render_source_links(item)
        rows.append(
            f'<tr class="archive-row {css_type}" data-type="{css_type}">'
            f'<td class="date-cell">{escape(date_label)}</td>'
            f'<td class="time-cell"><time datetime="{escape(datetime_value, quote=True)}">'
            f"{escape(time_label)}</time></td>"
            f'<td><span class="type-label">{type_label}</span></td>'
            f'<td class="title-cell">{escape(str(title or "Bez názvu"))}</td>'
            f'<td class="detail-cell">{escape(str(detail or ""))}</td>'
            f'<td class="sources-cell">{source_links}</td>'
            f'<td><span class="status {status_class}">{status_label}</span></td>'
            "</tr>"
        )
    return "".join(rows)


def build_audit_html(events: list[dict]) -> str:
    rows = "".join(_render_event_rows(event) for event in events)
    row_count = rows.count('class="archive-row')
    triage_count = rows.count('data-type="triage"')
    synthesis_count = rows.count('data-type="synthesis"')
    if not rows:
        rows = (
            '<tr class="empty-row"><td colspan="7">Archív je zatiaľ prázdny. '
            "Prvý záznam pribudne po najbližšom výbere.</td></tr>"
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
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;700&family=IBM+Plex+Sans:wght@400;500;600;700&family=Newsreader:opsz,wght@6..72,600;6..72,700&display=swap" rel="stylesheet">
<title>SK News Agent — História výberov</title>
<style>
:root {{
  --canvas:#FAF9F6; --surface:#FFFFFF; --text:#102033; --navy:#0B1F33;
  --muted:#64748B; --blue:#2563EB; --blue-soft:#EAF1FF;
  --red:#D7263D; --red-soft:#FFF1F3; --rule:#DCE2E8; --rule-strong:#C8D0D9;
  --green:#277443; --green-soft:#EDF8F1;
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--canvas); color:var(--text);
  font-family:"IBM Plex Sans",-apple-system,sans-serif; line-height:1.45;
  -webkit-font-smoothing:antialiased; }}
a {{ color:var(--blue); text-decoration:none; }}
a:hover, a:focus-visible {{ text-decoration:underline; }}
button:focus-visible, a:focus-visible {{
  outline:3px solid rgba(37,99,235,.28); outline-offset:3px;
}}
.site-header {{ background:var(--navy); color:#FFFFFF; }}
.header-inner {{
  max-width:1380px; min-height:64px; margin:0 auto; padding:0 30px;
  display:grid; grid-template-columns:auto minmax(0,1fr) auto;
  align-items:center; gap:38px;
}}
.masthead {{
  color:#FFFFFF; font:700 23px "Newsreader",Georgia,serif;
  letter-spacing:-.025em; white-space:nowrap;
}}
.masthead b {{
  color:#9EC1FF; margin-left:8px; padding-left:10px;
  border-left:1px solid rgba(255,255,255,.28);
  font:500 13px "IBM Plex Sans",sans-serif; letter-spacing:.02em;
  text-transform:uppercase;
}}
nav {{ display:flex; gap:6px; }}
nav a {{
  display:inline-flex; align-items:center; min-height:64px; padding:0 13px;
  color:#D7E2EC; font-size:13px; border-bottom:3px solid transparent;
}}
nav a:hover, nav a:focus-visible {{
  color:#FFFFFF; border-bottom-color:#78A7FF; text-decoration:none;
}}
nav a.active {{ color:#FFFFFF; border-bottom-color:#78A7FF; }}
.updated {{ color:#AFC0D2; font:10.5px "IBM Plex Mono",monospace; white-space:nowrap; }}
main {{ max-width:1380px; margin:0 auto; padding:30px 30px 60px; }}
.page-head {{
  display:flex; justify-content:space-between; align-items:flex-end;
  gap:24px; margin-bottom:18px;
}}
.eyebrow {{
  color:var(--blue); font:700 10px "IBM Plex Mono",monospace;
  letter-spacing:.14em; text-transform:uppercase;
}}
h1 {{
  font:700 34px "Newsreader",Georgia,serif; letter-spacing:-.025em;
  margin:2px 0 3px;
}}
.intro {{ color:var(--muted); margin:0; max-width:760px; font-size:13.5px; }}
.archive-count {{ color:var(--muted); font:11px "IBM Plex Mono",monospace; }}
.toolbar {{
  display:flex; justify-content:space-between; align-items:center; gap:16px;
  flex-wrap:wrap; margin-bottom:14px;
}}
.filters {{ display:flex; gap:7px; flex-wrap:wrap; }}
button {{
  cursor:pointer; border:1px solid var(--rule-strong); background:var(--surface);
  color:var(--muted); font:500 12px "IBM Plex Sans",sans-serif;
}}
.filters button {{
  min-height:34px; padding:6px 12px; border-radius:999px;
}}
.filters button span {{ color:#8A98A8; margin-left:4px; font-size:10px; }}
.filters button:hover {{ color:var(--blue); border-color:#AFC6F5; }}
.filters button.active {{ color:#FFFFFF; background:var(--blue); border-color:var(--blue); }}
.filters button.active span {{ color:#DCE8FF; }}
.copy-button {{
  min-height:36px; padding:7px 12px; border-radius:3px; color:var(--blue);
}}
.copy-button:hover {{ background:var(--blue-soft); border-color:#AFC6F5; }}
.copy-button.copied {{ color:var(--green); background:var(--green-soft); border-color:#A9D6B8; }}
.table-hint {{ display:none; color:var(--muted); font-size:11.5px; margin:0 0 7px; }}
.table-wrap {{
  overflow:auto; background:var(--surface); border:1px solid var(--rule-strong);
}}
table {{
  width:100%; min-width:1120px; border-collapse:collapse; table-layout:fixed;
  font-size:12.5px;
}}
col.date {{ width:92px; }} col.time {{ width:78px; }} col.type {{ width:112px; }}
col.title {{ width:25%; }} col.detail {{ width:33%; }} col.sources {{ width:125px; }}
col.status {{ width:108px; }}
thead {{ position:sticky; top:0; z-index:1; }}
th {{
  padding:10px 12px; background:var(--navy); color:#DCE6EF;
  border-right:1px solid #29435A; text-align:left;
  font:600 10.5px "IBM Plex Sans",sans-serif; letter-spacing:.06em;
  text-transform:uppercase;
}}
th:last-child {{ border-right:0; }}
td {{
  padding:10px 12px; border-bottom:1px solid var(--rule);
  vertical-align:top; overflow-wrap:anywhere;
}}
tbody tr:hover {{ background:#F7F9FC; }}
.archive-row[hidden] {{ display:none; }}
.date-cell, .time-cell {{
  color:var(--muted); font:11px "IBM Plex Mono",monospace; white-space:nowrap;
}}
.type-label {{
  color:var(--blue); font-size:11px; font-weight:700; white-space:nowrap;
}}
.triage .type-label {{ color:var(--red); }}
.title-cell {{ color:var(--text); font-weight:600; }}
.detail-cell {{ color:#526274; }}
.sources-cell a {{ font:500 11px "IBM Plex Mono",monospace; white-space:nowrap; }}
.source-separator {{ color:var(--rule-strong); }}
.status {{
  display:inline-block; padding:2px 7px; border-radius:999px;
  font-size:10px; font-weight:600; white-space:nowrap;
}}
.published {{ color:var(--green); background:var(--green-soft); }}
.unpublished {{ color:var(--muted); background:#EEF1F4; }}
.empty-row td {{ padding:30px; color:var(--muted); text-align:center; font-style:italic; }}
.no-results {{ padding:24px; color:var(--muted); text-align:center; font-size:13px; }}
@media (max-width:900px) {{
  .header-inner {{ grid-template-columns:auto 1fr; gap:20px; }}
  .updated {{ display:none; }}
  nav {{ justify-self:end; }}
}}
@media (max-width:680px) {{
  .header-inner {{ min-height:0; padding:13px 17px 0; display:block; }}
  .masthead {{ font-size:20px; }}
  nav {{ margin-top:7px; overflow-x:auto; }}
  nav a {{ min-height:42px; padding:0 8px; font-size:12px; white-space:nowrap; }}
  main {{ padding:22px 14px 40px; }}
  .page-head {{ display:block; }}
  h1 {{ font-size:30px; }}
  .archive-count {{ display:block; margin-top:8px; }}
  .copy-button {{ width:100%; }}
  .table-hint {{ display:block; }}
  .table-wrap {{ margin-left:-14px; margin-right:-14px; border-left:0; border-right:0; }}
}}
</style>
</head>
<body>
<header class="site-header"><div class="header-inner">
  <div class="masthead">SK News Agent <b>Prehľad</b></div>
  <nav aria-label="Hlavná navigácia">
    <a href="index.html#top-temy">Prehľad</a>
    <a href="index.html#media-radar">Media Radar</a>
    <a href="sport.html">Šport</a>
    <a class="active" href="audit.html" aria-current="page">História výberov</a>
  </nav>
  <div class="updated">Aktualizované {generated}</div>
</div></header>
<main>
  <div class="page-head">
    <div>
      <div class="eyebrow">Archív redakčných výberov</div>
      <h1>História výberov</h1>
      <p class="intro">Jednoduchý chronologický zoznam tém vybraných agentom.
      Čas označuje moment, keď systém výber zaznamenal.</p>
    </div>
    <span class="archive-count"><span id="visible-count">{row_count}</span> záznamov</span>
  </div>
  <div class="toolbar">
    <div class="filters" aria-label="Filtrovanie záznamov">
      <button class="active" type="button" data-filter="all" aria-pressed="true">
        Všetko <span>{row_count}</span></button>
      <button type="button" data-filter="triage" aria-pressed="false">
        Mimoriadne <span>{triage_count}</span></button>
      <button type="button" data-filter="synthesis" aria-pressed="false">
        Top témy <span>{synthesis_count}</span></button>
    </div>
    <button class="copy-button" type="button">Kopírovať zobrazené do Excelu</button>
  </div>
  <p class="table-hint">Potiahnutím tabuľky doľava zobrazíte ďalšie stĺpce.</p>
  <div class="table-wrap">
    <table id="archive-table">
      <colgroup>
        <col class="date"><col class="time"><col class="type"><col class="title">
        <col class="detail"><col class="sources"><col class="status">
      </colgroup>
      <thead><tr>
        <th>Dátum</th><th>Čas</th><th>Kategória</th><th>Téma</th>
        <th>Popis / dôvod výberu</th><th>Zdroje</th><th>Stav</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
  <div class="no-results" hidden>V tejto kategórii nie sú žiadne záznamy.</div>
</main>
<script>
(function () {{
  var buttons = Array.prototype.slice.call(document.querySelectorAll('[data-filter]'));
  var rows = Array.prototype.slice.call(document.querySelectorAll('.archive-row'));
  var visibleCount = document.getElementById('visible-count');
  var noResults = document.querySelector('.no-results');
  var copyButton = document.querySelector('.copy-button');

  buttons.forEach(function (button) {{
    button.addEventListener('click', function () {{
      var filter = button.getAttribute('data-filter');
      buttons.forEach(function (item) {{
        var active = item === button;
        item.classList.toggle('active', active);
        item.setAttribute('aria-pressed', active ? 'true' : 'false');
      }});
      var shown = 0;
      rows.forEach(function (row) {{
        row.hidden = filter !== 'all' && row.getAttribute('data-type') !== filter;
        if (!row.hidden) shown += 1;
      }});
      visibleCount.textContent = String(shown);
      noResults.hidden = shown > 0;
    }});
  }});

  function copyText(value) {{
    if (navigator.clipboard && navigator.clipboard.writeText) {{
      return navigator.clipboard.writeText(value);
    }}
    var area = document.createElement('textarea');
    area.value = value;
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    document.execCommand('copy');
    area.remove();
    return Promise.resolve();
  }}

  copyButton.addEventListener('click', function () {{
    var headers = Array.prototype.map.call(
      document.querySelectorAll('#archive-table th'),
      function (cell) {{ return cell.innerText.trim(); }}
    );
    var visibleRows = rows.filter(function (row) {{ return !row.hidden; }});
    var lines = [headers].concat(visibleRows.map(function (row) {{
      return Array.prototype.map.call(row.cells, function (cell) {{
        return cell.innerText.replace(/\\s+/g, ' ').trim();
      }});
    }}));
    var tsv = lines.map(function (line) {{ return line.join('\\t'); }}).join('\\n');
    copyText(tsv).then(function () {{
      copyButton.textContent = 'Skopírované';
      copyButton.classList.add('copied');
      window.setTimeout(function () {{
        copyButton.textContent = 'Kopírovať zobrazené do Excelu';
        copyButton.classList.remove('copied');
      }}, 1800);
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
