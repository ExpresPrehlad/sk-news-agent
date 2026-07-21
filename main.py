"""
Entrypoint sk-news-agent — jeden beh (Vrstva 1 + Vrstva 2).

Režimy:
    python main.py                # ostrý beh: zber → dedup → Discord → LLM → stav
    python main.py --check-feeds  # health check feedov, nič neposiela
    python main.py --dry-run      # zber + dedup, vypíše nové, neposiela, neukladá
    python main.py --force-synthesis  # vynúti syntézu bez ohľadu na interval

Poradie a filozofia zlyhaní:
1. Surový feed (Vrstva 1) je posvätný — jeho odoslanie podmieňuje uloženie
   stavu ("radšej duplicita než strata").
2. LLM vrstva (triáž, syntéza) je best-effort: jej zlyhanie NIKDY nezhodí
   beh ani nezablokuje stav. Totálny výpadok LLM reťaze sa hlási do #alerty
   (max raz za 6 h), lebo redakcia má vedieť, že alerty dočasne nechodia.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

from src.collector.rss import fetch_all
from src.config import (
    GEMINI_API_KEY,
    OPENROUTER_API_KEY,
    SOURCES,
    STATE_PATH,
    SYNTHESIS_INTERVAL_MINUTES,
    SYNTHESIS_WINDOW_HOURS,
    DiscordConfig,
)
from src.digest import synthesize, triage
from src.llm.router import AllModelsFailed
from src.notify.discord import (
    send_alerts,
    send_digest,
    send_error,
    send_raw_feed,
)
from src.pages import write_page
from src.state import State

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("main")

_LLM_ENABLED = bool(GEMINI_API_KEY or OPENROUTER_API_KEY)


def check_feeds() -> int:
    results = fetch_all(SOURCES)
    all_ok = True
    for r in results:
        if r.ok:
            print(f"  OK   {r.source.id:<10} {len(r.articles):>3} položiek   {r.source.feed_url}")
        else:
            all_ok = False
            print(f"  FAIL {r.source.id:<10} {r.error}   {r.source.feed_url}")
    return 0 if all_ok else 1


def _run_triage(state: State, discord: DiscordConfig, new_articles: list[dict]) -> None:
    """Best-effort triáž nových článkov → #alerty."""
    try:
        alerts, model = triage(new_articles)
    except AllModelsFailed as exc:
        log.error("Triáž: celá LLM reťaz zlyhala: %s", exc)
        _report_llm_outage(state, discord, "triáž", str(exc))
        return
    if alerts:
        log.info("Triáž (%s): %d alert(ov).", model, len(alerts))
        send_alerts(discord.alerts_url, alerts, model)
        state.add_alerts(alerts, model)
    else:
        log.info("Triáž (%s): nič mimoriadne.", model)


def _run_synthesis(state: State, discord: DiscordConfig, force: bool) -> None:
    """Syntéza TOP tém raz za SYNTHESIS_INTERVAL_MINUTES → #prehlad."""
    due = time.time() - state.get_meta("last_synthesis_ts") >= SYNTHESIS_INTERVAL_MINUTES * 60
    if not (due or force):
        return
    window = state.recent_window(SYNTHESIS_WINDOW_HOURS)
    if len(window) < 5:
        log.info("Syntéza: v okne len %d článkov — preskakujem.", len(window))
        return
    try:
        topics, model = synthesize(window)
    except AllModelsFailed as exc:
        log.error("Syntéza: celá LLM reťaz zlyhala: %s", exc)
        _report_llm_outage(state, discord, "syntéza", str(exc))
        return
    if topics and send_digest(discord.digest_url, topics, model):
        state.set_meta("last_synthesis_ts", time.time())
        state.set_last_digest(topics, model)
        log.info("Syntéza (%s): %d tém odoslaných.", model, len(topics))


def _report_llm_outage(state: State, discord: DiscordConfig, what: str, detail: str) -> None:
    """Hlásenie totálneho výpadku LLM — max raz za 6 hodín."""
    if time.time() - state.get_meta("last_llm_error_ts") > 6 * 3600:
        if send_error(
            discord.alerts_url,
            f"LLM reťaz nedostupná ({what})",
            f"Všetky modely zlyhali. Alerty a prehľady dočasne nechodia.\n{detail[:800]}",
        ):
            state.set_meta("last_llm_error_ts", time.time())


def run(dry_run: bool = False, force_synthesis: bool = False) -> int:
    discord = DiscordConfig()
    state = State(STATE_PATH)

    results = fetch_all(SOURCES)
    failed = [r for r in results if not r.ok]
    for r in failed:
        log.warning("Zdroj %s nedostupný: %s", r.source.id, r.error)
    new_articles = []
    for r in results:
        for a in r.articles:
            if state.is_new(a.uid):
                new_articles.append(a)

    # Obohatenie titulkov pre sitemap zdroje (ta3): slug-titulky nahradíme
    # skutočnými z og:title. Len pre NOVÉ články (dedup už prebehol), s limitom
    # fetchov na beh — neúspech necháva slug verziu, nikdy nezhadzuje beh.
    sitemap_source_ids = {s.id for s in SOURCES if s.kind == "sitemap"}
    if any(a.source_id in sitemap_source_ids for a in new_articles):
        from src.collector.sitemap import enrich_titles
        to_enrich = [a for a in new_articles if a.source_id in sitemap_source_ids]
        others = [a for a in new_articles if a.source_id not in sitemap_source_ids]
        new_articles = others + enrich_titles(to_enrich)

    log.info(
        "Zdroje: %d OK / %d FAIL · článkov vo feedoch: %d · nových: %d",
        len(results) - len(failed), len(failed),
        sum(len(r.articles) for r in results), len(new_articles),
    )

    if dry_run:
        for a in sorted(new_articles, key=lambda x: x.source_id):
            print(f"[{a.source_name}] {a.title}\n    {a.link}")
        print(f"\n(dry-run: {len(new_articles)} nových, stav sa neukladá)")
        return 0

    # ---- Vrstva 1: surový feed (podmieňuje uloženie stavu) ----------------
    sent_ok = True
    if new_articles:
        sent_ok = send_raw_feed(discord.raw_feed_url, new_articles)

    state.set_source_status(results)

    if failed and time.time() - state.get_meta("last_feed_error_ts") > 6 * 3600:
        detail = "\n".join(f"**{r.source.name}**: {r.error}" for r in failed)
        if send_error(discord.alerts_url, "Nedostupné RSS zdroje", detail):
            state.set_meta("last_feed_error_ts", time.time())

    if not sent_ok:
        log.error("Discord zlyhal — stav sa NEUKLADÁ, články sa pošlú nabudúce.")
        return 1

    for a in new_articles:
        state.mark_seen(a.uid)
        state.add_recent(
            uid=a.uid, source=a.source_name, title=a.title,
            perex=a.summary, link=a.link,
        )
    state.set_meta("last_run_ts", time.time())

    # ---- Vrstva 2: LLM (best-effort, nesmie zhodiť beh) -------------------
    if _LLM_ENABLED:
        new_dicts = [
            {"s": a.source_name, "t": a.title, "p": a.summary, "l": a.link}
            for a in new_articles
        ]
        try:
            if new_dicts:
                _run_triage(state, discord, new_dicts)
            _run_synthesis(state, discord, force_synthesis)
        except Exception:  # noqa: BLE001 — bezpečnostná sieť pre celú vrstvu
            log.exception("Nečakaná chyba LLM vrstvy — beh pokračuje.")
    else:
        log.info("LLM kľúče nie sú nastavené — Vrstva 2 preskočená.")

    # GitHub Pages: vygeneruje sa pri KAŽDOM behu (nie len pri syntéze), lebo
    # číta z perzistovaného state (last_digest, recent_alerts, source_status),
    # takže stránka je vždy aktuálna k poslednému behu. Zlyhanie nesmie
    # zhodiť beh — write_page interne chytá všetky výnimky.
    write_page(state)

    state.save()
    log.info("Stav uložený (%d videných, %d v recent bufferi).",
             len(state.seen), len(state.recent))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="sk-news-agent")
    parser.add_argument("--check-feeds", action="store_true", help="len over feedy")
    parser.add_argument("--dry-run", action="store_true", help="nič neposielaj ani neukladaj")
    parser.add_argument("--force-synthesis", action="store_true",
                        help="vynúti syntézu bez ohľadu na interval")
    args = parser.parse_args()

    if args.check_feeds:
        sys.exit(check_feeds())
    sys.exit(run(dry_run=args.dry_run, force_synthesis=args.force_synthesis))
