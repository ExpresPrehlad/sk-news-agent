"""
Centrálna konfigurácia projektu sk-news-agent.

Všetky tajomstvá (API kľúče, webhook URL) sa čítajú z environment premenných —
nikdy ich nehardcoduj do repa. Lokálne ich načítaš z .env, na GitHub Actions
zo Secrets.
"""

import os
from dataclasses import dataclass, field
from datetime import time as _time


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
    feed_url: str      # RSS/Atom feed, news sitemap, sitemap index alebo homepage
    enabled: bool = True
    kind: str = "rss"  # "rss" | "news_sitemap" | "sitemap" | "homepage"
    # optional=True: očakávane nespoľahlivý zdroj (napr. SME za Cloudflare,
    # ktoré /rss občas prepustí a občas nie) — jeho zlyhania sa NEhlásia do
    # #alerty, len sa logujú a zobrazia na stavovej stránke.
    optional: bool = False


SOURCES: list[Source] = [
    # SME: za Cloudflare Bot Management. /rss na www.sme.sk občas prejde,
    # občas vráti challenge — preto optional (oportunistický zber: keď
    # prejde, články sa zoberú; keď nie, ticho sa preskočí). Sitemapy
    # z robots.txt sú za WAF blokom trvalo. Validáciu obsahu (challenge
    # s HTTP 200) rieši hardening v rss.py. Konzultácia 21.7.2026.
    Source("sme",       "SME",        "https://www.sme.sk/rss",
           optional=True),
    # SME doplnkovo cez verejný Google News RSS — nie je úplný a máva
    # oneskorenie, ale zachytí hlavné SME témy aj keď /rss neprejde.
    # Linky sú Google redirecty (klik funguje, len nie je "pekný").
    Source("sme_gnews", "SME (GNews)",
           "https://news.google.com/rss/search?q=site:sme.sk&hl=sk&gl=SK&ceid=SK:sk",
           optional=True),
    Source("aktuality", "Aktuality",  "https://www.aktuality.sk/rss/"),
    Source("dennikn",   "Denník N",   "https://dennikn.sk/feed/"),
    Source("pravda",    "Pravda",     "https://spravy.pravda.sk/rss/xml/"),
    # HN: /feed je IP-blokovaný z GitHub Actions (Cloudflare reputácia
    # cloudových rozsahov), ale robots.txt uvádza .xml.gz sitemap index,
    # ktorý má inú WAF politiku — testujeme túto cestu. Titulky nie sú
    # v sitemape, doplní ich enrichment. Konzultácia 21.7.2026.
    Source("hn",        "HN",
           "https://hnonline.sk/sitemap-index-hnonline-sk.xml.gz",
           kind="sitemap"),
    Source("teraz",     "Teraz.sk",   "https://www.teraz.sk/rss/slovensko.rss"),
    # tnlive.sk (bývalé tvnoviny.sk — rebrand, stará doména presmerúva).
    # Google News sitemap: titulok + link + čas priamo v XML, bez CF bloku.
    Source("tnlive",    "TN Live",    "https://tnlive.sk/api/v2/sitemap-news",
           kind="news_sitemap"),
    # ta3.com: klasický sitemap index s per-článkovým lastmod, bez CF.
    # Titulky nie sú v XML — odvodia sa zo slugu a pre nové články sa
    # obohacujú fetchom stránky (viď sitemap.enrich_titles).
    Source("ta3",       "TA3",        "https://www.ta3.com/cdn/sitemap/sitemap.xml",
           kind="sitemap"),
    # noviny.sk: sitemap z robots.txt je trvalo prázdny (mŕtvy generátor),
    # RSS neexistuje — zber cez serverovo renderovanú homepage (článkové
    # URL vzoru /<rubrika>/<id>-<slug>), titulky cez enrichment.
    # Konzultácia 21.7.2026.
    Source("noviny",    "Noviny.sk",  "https://www.noviny.sk/",
           kind="homepage"),
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

# Syntéza TOP tém: interval sa berie z aktuálneho SCHEDULE_BANDS pásma
# (rôzny cez deň/víkend) — pozri nižšie. Triáž beží pri každom reálnom
# zbere s novými článkami, nemá vlastný interval.

# Okno článkov, ktoré vstupujú do syntézy (hodiny dozadu).
SYNTHESIS_WINDOW_HOURS: int = 6

# Koľko hodín držíme články v rolling bufferi v stave (vstup pre syntézu).
RECENT_BUFFER_HOURS: int = 24

# ---------------------------------------------------------------------------
# Rozvrh behu — pozri src/schedule.py pre logiku vyhodnocovania
# ---------------------------------------------------------------------------
# Mimo všetkých pásiem sa AUTOMATICKÝ (cron) beh preskočí úplne — žiadny
# fetch, LLM, Discord. V rámci pásma cron tikne často (viď workflow), ale
# skript zbiera/syntetizuje len po uplynutí intervalu daného pásma.
#
# POZOR na kompromis: mimoriadna udalosť mimo aktívnych pásiem (najmä cez
# noc) sa zachytí až pri najbližšom aktívnom behu.

@dataclass(frozen=True)
class ScheduleBand:
    weekdays: frozenset       # 0=pondelok ... 6=nedeľa (datetime.weekday())
    start: _time
    end: _time
    collect_minutes: int
    synthesis_minutes: int


_WEEKDAYS = frozenset({0, 1, 2, 3, 4})  # pondelok-piatok
_WEEKEND = frozenset({5, 6})            # sobota-nedeľa

# Kontrolované v poradí; prvé pásmo, do ktorého (deň, čas) zapadá, sa použije.
SCHEDULE_BANDS: list[ScheduleBand] = [
    # Pracovné dni — ranná špička
    ScheduleBand(_WEEKDAYS, _time(5, 30), _time(8, 30),
                 collect_minutes=20, synthesis_minutes=30),
    # Pracovné dni — hlavný denný cyklus (najhustejší)
    ScheduleBand(_WEEKDAYS, _time(8, 30), _time(18, 0),
                 collect_minutes=10, synthesis_minutes=15),
    # Pracovné dni — večer
    ScheduleBand(_WEEKDAYS, _time(18, 0), _time(23, 50),
                 collect_minutes=20, synthesis_minutes=30),
    # Víkend — jednotné pásmo
    ScheduleBand(_WEEKEND, _time(5, 30), _time(22, 0),
                 collect_minutes=20, synthesis_minutes=30),
]

# Fallback interval syntézy pre okrajový prípad: manuálny beh mimo všetkých
# pásiem (band=None) bez --force-synthesis.
DEFAULT_SYNTHESIS_INTERVAL_MINUTES: int = 30

ACTIVE_HOURS_TZ: str = "Europe/Bratislava"
