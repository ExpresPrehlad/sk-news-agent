"""
Centrálna konfigurácia projektu sk-news-agent.

Všetky tajomstvá (API kľúče, webhook URL) sa čítajú z environment premenných —
nikdy ich nehardcoduj do repa. Lokálne ich načítaš z .env, na GitHub Actions
zo Secrets.
"""

import os
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# RSS zdroje
# ---------------------------------------------------------------------------
# POZOR: URL feedov si pred nasadením over spustením `python main.py --check-feeds`.
# Portály občas menia štruktúru RSS; collector je na to pripravený (mŕtvy feed
# nezhodí beh, len sa zaloguje), ale presné URL si drž aktuálne tu.

@dataclass(frozen=True)
class Source:
    id: str            # krátky identifikátor (používa sa v stave a logoch)
    name: str          # zobrazované meno pre Discord
    feed_url: str      # RSS/Atom feed
    enabled: bool = True


SOURCES: list[Source] = [
    Source("sme",       "SME",        "https://rss.sme.sk/rss/rss.asp?id=frontpage"),
    Source("aktuality", "Aktuality",  "https://www.aktuality.sk/rss/"),
    Source("dennikn",   "Denník N",   "https://dennikn.sk/feed/"),
    Source("pravda",    "Pravda",     "https://spravy.pravda.sk/rss/xml/"),
    Source("hn",        "HN",         "https://hnonline.sk/feed"),
    Source("teraz",     "Teraz.sk",   "https://www.teraz.sk/rss/slovensko.rss"),
]


# ---------------------------------------------------------------------------
# Správanie collectora a stavu
# ---------------------------------------------------------------------------

# Ako dlho si pamätáme videné články. Musí byť výrazne dlhšie než najhorší
# možný výpadok GitHub Actions, aby sa po výpadku nič neposlalo duplicitne
# ani nestratilo.
SEEN_WINDOW_HOURS: int = 48

# Timeout pre HTTP požiadavky na feedy (sekundy).
HTTP_TIMEOUT: float = 15.0

# User-Agent — niektoré portály (napr. sme.sk, hnonline.sk) majú WAF, ktorý
# blokuje očividné boty (403 Forbidden). Vlastný identifikátor typu
# "sk-news-agent/1.0" je ľahko rozpoznateľný a blokovaný, preto sa
# vydávame za bežný prehliadač — legitímna a bežná obrana, keďže RSS feed
# je verejne určený na strojové čítanie.
USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Cesta k stavovému súboru (commituje sa späť do repa vo workflow).
STATE_PATH: str = os.environ.get("STATE_PATH", "data/state.json")

# Poistka proti zaplaveniu Discordu pri prvom behu alebo po dlhom výpadku:
# ak je nových článkov viac, pošle sa len súhrnná hlavička + prvých N.
MAX_RAW_ITEMS_PER_RUN: int = 40


# ---------------------------------------------------------------------------
# Discord webhooky (tri kanály)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DiscordConfig:
    raw_feed_url: str = field(default_factory=lambda: os.environ.get("DISCORD_WEBHOOK_RAW", ""))
    alerts_url: str = field(default_factory=lambda: os.environ.get("DISCORD_WEBHOOK_ALERTS", ""))
    digest_url: str = field(default_factory=lambda: os.environ.get("DISCORD_WEBHOOK_DIGEST", ""))


# ---------------------------------------------------------------------------
# LLM (Vrstva 2 — zatiaľ len placeholder pre kľúče, router príde neskôr)
# ---------------------------------------------------------------------------

GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")
OPENROUTER_API_KEY: str = os.environ.get("OPENROUTER_API_KEY", "")
