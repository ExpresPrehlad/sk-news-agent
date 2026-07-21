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
    feed_url: str      # RSS/Atom feed, news sitemap alebo sitemap index
    enabled: bool = True
    kind: str = "rss"  # "rss" | "news_sitemap" | "sitemap"


SOURCES: list[Source] = [
    # SME je za Cloudflare Bot Management s interaktívnym challenge
    # (JS/TLS fingerprint) — overené priamym testom, User-Agent/Accept
    # hlavičky to neriešia. RSS prejde len občas (nestabilné), sitemap
    # aj API sú za WAF blokom. Vypnuté, kým sa nenájde iný prístup
    # (napr. oficiálna dohoda so SME). Pozri diskusiu v chate z 21.7.2026.
    Source("sme",       "SME",        "https://rss.sme.sk/rss/rss.asp?id=frontpage", enabled=False),
    Source("aktuality", "Aktuality",  "https://www.aktuality.sk/rss/"),
    Source("dennikn",   "Denník N",   "https://dennikn.sk/feed/"),
    Source("pravda",    "Pravda",     "https://spravy.pravda.sk/rss/xml/"),
    Source("hn",        "HN",         "https://hnonline.sk/feed"),
    Source("teraz",     "Teraz.sk",   "https://www.teraz.sk/rss/slovensko.rss"),
    # tnlive.sk (bývalé tvnoviny.sk — rebrand, stará doména presmerúva).
    # Google News sitemap: titulok + link + čas priamo v XML, bez CF bloku.
    Source("tnlive",    "TN Live",    "https://tnlive.sk/api/v2/sitemap-news",
           kind="news_sitemap"),
    # ta3.com: klasický sitemap index s per-článkovým lastmod, bez CF.
    # Titulky nie sú v XML — odvodia sa zo slugu a pre nové články sa
    # obohacujú fetchom stránky (max 12/beh, viď sitemap.enrich_titles).
    Source("ta3",       "TA3",        "https://www.ta3.com/cdn/sitemap/sitemap.xml",
           kind="sitemap"),
    # noviny.sk: prieskum 21.7.2026 nenašiel nič použiteľné — sitemap
    # z robots.txt je prázdny, API vracia "Unknown api endpoint", RSS 404.
    # Kandidát na neskôr, ak sa objaví funkčný endpoint.
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
# LLM (Vrstva 2)
# ---------------------------------------------------------------------------

GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")
OPENROUTER_API_KEY: str = os.environ.get("OPENROUTER_API_KEY", "")

# Eskalačná reťaz: skúša sa zhora nadol, prvý úspech vyhráva.
# Gemini modely majú najvyššie free RPD, preto sú prvé. OpenRouter free
# modely rotujú takmer bez varovania — preto zoznam + auto-router na konci.
GEMINI_MODELS: list[str] = [
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash",
]
OPENROUTER_MODELS: list[str] = [
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "google/gemma-4-31b-it:free",
    "openai/gpt-oss-20b:free",
    # auto-router — posledná záchrana. Pozor: vie vybrať aj nevhodný
    # špecializovaný model (napr. Nemotron 3.5 Content Safety, ktorý
    # vracia len bezpečnostný verdikt, nie voľný JSON) — preto je až
    # na konci, nikdy nie ako prvá voľba.
    "openrouter/free",
]

# Timeout pre LLM volania (sekundy) — syntéza s väčším vstupom potrebuje čas.
LLM_TIMEOUT: float = 60.0

# Syntéza TOP tém: raz za tento interval (minúty). Triáž beží pri každom
# behu s novými článkami, syntéza šetrí volania aj pozornosť čitateľov.
SYNTHESIS_INTERVAL_MINUTES: int = 120

# Okno článkov, ktoré vstupujú do syntézy (hodiny dozadu).
SYNTHESIS_WINDOW_HOURS: int = 6

# Koľko hodín držíme články v rolling bufferi v stave (vstup pre syntézu).
RECENT_BUFFER_HOURS: int = 24
