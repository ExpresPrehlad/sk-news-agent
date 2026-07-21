"""
Entrypoint sk-news-agent — jeden beh zberu (Vrstva 1).

Režimy:
    python main.py                # ostrý beh: zber → dedup → Discord → uloženie stavu
    python main.py --check-feeds  # health check: overí všetky feedy, nič neposiela
    python main.py --dry-run      # zber + dedup, vypíše nové články, neposiela,
                                  # NEUKLADÁ stav (dá sa opakovať)

Poradie operácií v ostrom behu je zámerné:
stav sa ukladá AŽ PO úspešnom odoslaní na Discord. Ak Discord zlyhá, články
ostanú "nevidené" a pošlú sa v ďalšom behu — radšej duplicita než strata.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

from src.collector.rss import fetch_all
from src.config import SOURCES, STATE_PATH, DiscordConfig
from src.notify.discord import send_error, send_raw_feed
from src.state import State

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("main")


def check_feeds() -> int:
    """Overí všetky feedy a vypíše report. Exit code 1, ak niečo neletí."""
    results = fetch_all(SOURCES)
    all_ok = True
    for r in results:
        if r.ok:
            print(f"  OK   {r.source.id:<10} {len(r.articles):>3} položiek   {r.source.feed_url}")
        else:
            all_ok = False
            print(f"  FAIL {r.source.id:<10} {r.error}   {r.source.feed_url}")
    return 0 if all_ok else 1


def run(dry_run: bool = False) -> int:
    discord = DiscordConfig()
    state = State(STATE_PATH)

    results = fetch_all(SOURCES)

    # Mŕtve feedy hlásime, ale beh pokračuje s tým, čo máme.
    failed = [r for r in results if not r.ok]
    for r in failed:
        log.warning("Zdroj %s nedostupný: %s", r.source.id, r.error)

    new_articles = []
    for r in results:
        for a in r.articles:
            if state.is_new(a.uid):
                new_articles.append(a)

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

    sent_ok = True
    if new_articles:
        sent_ok = send_raw_feed(discord.raw_feed_url, new_articles)

    # Mŕtvy feed hlásime do alertov nanajvýš raz za 6 hodín, nech nespamujeme.
    if failed and time.time() - state.get_meta("last_feed_error_ts") > 6 * 3600:
        detail = "\n".join(f"**{r.source.name}**: {r.error}" for r in failed)
        if send_error(discord.alerts_url, "Nedostupné RSS zdroje", detail):
            state.set_meta("last_feed_error_ts", time.time())

    if sent_ok:
        for a in new_articles:
            state.mark_seen(a.uid)
        state.set_meta("last_run_ts", time.time())
        state.save()
        log.info("Stav uložený (%d videných záznamov).", len(state.seen))
    else:
        # Stav neukladáme — články sa zopakujú v ďalšom behu.
        log.error("Discord zlyhal — stav sa NEUKLADÁ, články sa pošlú nabudúce.")
        return 1

    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="sk-news-agent — Vrstva 1 (zber)")
    parser.add_argument("--check-feeds", action="store_true", help="len over feedy")
    parser.add_argument("--dry-run", action="store_true", help="nič neposielaj ani neukladaj")
    args = parser.parse_args()

    if args.check_feeds:
        sys.exit(check_feeds())
    sys.exit(run(dry_run=args.dry_run))
