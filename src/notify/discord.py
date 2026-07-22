"""
Discord notifikácie cez webhooky.

Limity Discordu, s ktorými pracujeme:
- max 10 embeds na jednu správu,
- max ~6000 znakov na správu (súčet embed obsahu),
- rate limit webhooku (~5 správ / 2 s) — riešime krátkym sleepom medzi chunkami.

Zásady:
- Zlyhanie notifikácie NIKDY nevyhodí výnimku vyššie — beh musí dokončiť
  uloženie stavu. Vraciame bool a logujeme.
- Poistka proti flood-u: pri prvom behu / po výpadku sa surový feed zreže na
  MAX_RAW_ITEMS_PER_RUN s viditeľnou poznámkou, koľko položiek sa vynechalo.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import requests

from ..collector.rss import Article
from ..config import HTTP_TIMEOUT, MAX_RAW_ITEMS_PER_RUN

log = logging.getLogger(__name__)

_EMBED_COLOR_RAW = 0x95A5A6     # sivá — nenápadný surový feed
_EMBED_COLOR_ERROR = 0xE74C3C   # červená — chybové hlásenia
_MAX_EMBEDS_PER_MSG = 10
_MAX_DESC_LEN = 2048
# Discord limit: súčet všetkých znakov (title+description+...) naprieč
# VŠETKÝMI embedmi v jednej správe nesmie prekročiť 6000 — inak 400 Bad
# Request na celý payload. Rezerva 5500 pod limitom pre istotu.
_MAX_TOTAL_CHARS_PER_MSG = 5500


def _chunk_embeds(embeds: list[dict]) -> list[list[dict]]:
    """
    Rozdelí embedy do správ tak, aby žiadna neprekročila ani počet 10, ani
    súčet 6000 znakov. Osamotený embed nad limitom sa pošle sám (najlepšie
    možné pri jeho vlastnej veľkosti — vyššie sme ho už orezali na 2048).
    """
    chunks: list[list[dict]] = []
    current: list[dict] = []
    current_chars = 0
    for e in embeds:
        e_chars = len(e.get("title", "")) + len(e.get("description", ""))
        if current and (
            len(current) >= _MAX_EMBEDS_PER_MSG
            or current_chars + e_chars > _MAX_TOTAL_CHARS_PER_MSG
        ):
            chunks.append(current)
            current, current_chars = [], 0
        current.append(e)
        current_chars += e_chars
    if current:
        chunks.append(current)
    return chunks


def _post(webhook_url: str, payload: dict) -> bool:
    if not webhook_url:
        log.warning("Webhook URL nie je nastavená — správa sa neposiela.")
        return False
    try:
        resp = requests.post(webhook_url, json=payload, timeout=HTTP_TIMEOUT)
        if resp.status_code == 429:
            # Discord rate limit — jedno zdvorilé počkanie a druhý pokus.
            retry_after = float(resp.headers.get("Retry-After", "2"))
            time.sleep(min(retry_after, 10.0))
            resp = requests.post(webhook_url, json=payload, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()
        return True
    except requests.RequestException as exc:
        log.error("Discord webhook zlyhal: %s", exc)
        return False


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def send_raw_feed(webhook_url: str, articles: list[Article]) -> bool:
    """
    Pošle nové články do #surovy-feed, zoskupené podľa zdroja.
    Jeden zdroj = jeden embed; titulky ako klikateľné linky.
    """
    if not articles:
        return True

    skipped = 0
    if len(articles) > MAX_RAW_ITEMS_PER_RUN:
        # Najnovšie majú prednosť (published_ts None padá na koniec).
        articles = sorted(
            articles, key=lambda a: a.published_ts or 0, reverse=True
        )
        skipped = len(articles) - MAX_RAW_ITEMS_PER_RUN
        articles = articles[:MAX_RAW_ITEMS_PER_RUN]

    by_source: dict[str, list[Article]] = {}
    for a in articles:
        by_source.setdefault(a.source_name, []).append(a)

    embeds = []
    for source_name, items in sorted(by_source.items()):
        lines = [f"• [{_truncate(a.title, 200)}]({a.link})" for a in items]
        desc = ""
        for line in lines:
            if len(desc) + len(line) + 1 > _MAX_DESC_LEN:
                desc += "\n*(… ďalšie skrátené)*"
                break
            desc += ("\n" if desc else "") + line
        embeds.append(
            {
                "title": f"{source_name} ({len(items)})",
                "description": desc,
                "color": _EMBED_COLOR_RAW,
            }
        )

    now = datetime.now(timezone.utc).astimezone().strftime("%H:%M")
    header = f"🗞️ Nové články · {now}"
    if skipped:
        header += f" · ⚠️ {skipped} položiek vynechaných (prvý beh / dobiehanie)"

    chunks = _chunk_embeds(embeds)
    ok = True
    for i, chunk in enumerate(chunks):
        payload = {"content": header if i == 0 else "", "embeds": chunk}
        ok = _post(webhook_url, payload) and ok
        if i < len(chunks) - 1:
            time.sleep(1.0)  # ohľaduplnosť k webhook rate limitu
    return ok


def send_error(webhook_url: str, title: str, detail: str) -> bool:
    """Chybové hlásenie (napr. mŕtvy feed, výpadok LLM reťaze)."""
    payload = {
        "embeds": [
            {
                "title": f"⚠️ {title}",
                "description": _truncate(detail, _MAX_DESC_LEN),
                "color": _EMBED_COLOR_ERROR,
            }
        ]
    }
    return _post(webhook_url, payload)


_EMBED_COLOR_ALERT = 0xE67E22    # oranžová — mimoriadne správy
_EMBED_COLOR_DIGEST = 0x3498DB   # modrá — prehľad tém


def send_alerts(webhook_url: str, alerts, model: str) -> bool:
    """Mimoriadne správy do #alerty — výrazné, ale bez @everyone spamu."""
    if not alerts:
        return True
    embeds = []
    for a in alerts:
        desc = a.reason
        if a.links:
            desc += "\n" + "\n".join(f"🔗 {link}" for link in a.links)
        embeds.append(
            {
                "title": f"🚨 {_truncate(a.title, 250)}",
                "description": _truncate(desc, _MAX_DESC_LEN),
                "color": _EMBED_COLOR_ALERT,
            }
        )
    payload = {
        "content": "**Mimoriadna správa** — vyžaduje pozornosť redakcie",
        "embeds": embeds[:_MAX_EMBEDS_PER_MSG],
    }
    if not _post(webhook_url, payload):
        return False
    # nenápadný indikátor modelu (dôležité pri fallback modeloch)
    return _post(webhook_url, {"content": f"-# triáž: {model}"})


def send_digest(webhook_url: str, topics, model: str) -> bool:
    """Prehľad TOP tém do #prehlad — jeden embed na tému."""
    if not topics:
        return True
    now = datetime.now(timezone.utc).astimezone().strftime("%H:%M")
    embeds = []
    for i, t in enumerate(topics, start=1):
        desc = t.perex
        if t.links:
            desc += "\n" + "\n".join(f"🔗 {source}: {url}" for source, url in t.links)
        embeds.append(
            {
                "title": f"{i}. {_truncate(t.headline, 250)}",
                "description": _truncate(desc, _MAX_DESC_LEN),
                "color": _EMBED_COLOR_DIGEST,
            }
        )

    chunks = _chunk_embeds(embeds)
    ok = True
    for i, chunk in enumerate(chunks):
        payload = {
            "content": f"📰 **Prehľad hlavných tém** · {now}" if i == 0 else "",
            "embeds": chunk,
        }
        ok = _post(webhook_url, payload) and ok
        if i < len(chunks) - 1:
            time.sleep(1.0)
    if ok:
        _post(webhook_url, {"content": f"-# syntéza: {model}"})
    return ok
