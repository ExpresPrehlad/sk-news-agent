"""
Digest logika Vrstvy 2: triáž (alerty) a syntéza (prehľad TOP tém).

Zásady:
- Prompty sú v slovenčine a žiadajú STRIKTNE JSON výstup — parsovanie je
  defenzívne (code fences, šum okolo JSON), lebo slabšie fallback modely
  nie vždy dodržia formát.
- Model NIKDY nedostáva pokyn vymýšľať fakty — pracuje výhradne s dodanými
  titulkami/perexami. Ak si nie je istý, má tému vynechať.
- Triáž má vysoký prah: radšej žiadny alert než falošný poplach —
  na úplnosť slúži surový feed, alerty sú výnimočná udalosť.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from .llm import router
from .llm.router import AllModelsFailed

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dátové typy
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Alert:
    title: str
    reason: str
    links: list[str]


@dataclass(frozen=True)
class Topic:
    headline: str      # chytľavý nadpis
    perex: str         # 2-3 vety, žurnalistický štýl
    links: list[str]


# ---------------------------------------------------------------------------
# JSON parsovanie — defenzívne
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> dict:
    """Vytiahne prvý JSON objekt z textu; toleruje ```json ploty a šum."""
    cleaned = re.sub(r"```(?:json)?", "", text).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"V odpovedi nie je JSON objekt: {text[:200]!r}")
    return json.loads(cleaned[start : end + 1])


def _fmt_articles(articles: list[dict]) -> str:
    """Formát vstupu pre model: [zdroj] titulok | perex | link"""
    lines = []
    for a in articles:
        perex = (a.get("p") or "")[:200]
        lines.append(f"[{a['s']}] {a['t']}" + (f" | {perex}" if perex else "") + f" | {a['l']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Triáž — breaking alerty
# ---------------------------------------------------------------------------

_TRIAGE_SYSTEM = """Si skúsený editor slovenskej spravodajskej redakcie. Dostaneš zoznam \
čerstvo publikovaných titulkov zo slovenských médií. Tvoja jediná úloha: identifikovať, \
či medzi nimi je MIMORIADNA správa vyžadujúca okamžitú pozornosť redakcie.

Mimoriadna správa znamená: úmrtie významnej osobnosti, pád vlády / demisia, veľká \
nehoda alebo katastrofa s obeťami, teroristický útok, vyhlásenie vojny alebo veľká \
vojenská eskalácia, zásadné rozhodnutie ústavného súdu, zatknutie vrcholného politika, \
prírodná katastrofa na Slovensku, výrazný ekonomický šok (krach banky, menová kríza).

Mimoriadna správa NIE JE: bežná politická výmena názorov, šport, počasie (okrem \
extrémov s obeťami), kultúra, ekonomické štatistiky, pokračovanie známej kauzy bez \
zásadného posunu.

Pracuj VÝHRADNE s dodanými titulkami. Nič si nedomýšľaj. Ak si nie si istý, tému \
NEZARAĎ — falošný poplach je horší než ticho (redakcia vidí všetky titulky aj tak).

Odpovedz IBA validným JSON bez akéhokoľvek ďalšieho textu, v tvare:
{"alerts": [{"title": "...", "reason": "jedna veta prečo je to mimoriadne", "links": ["..."]}]}
Ak nič mimoriadne nie je (najčastejší prípad), vráť: {"alerts": []}"""


def triage(new_articles: list[dict]) -> tuple[list[Alert], str]:
    """Vráti (alerty, použitý_model). Môže vyhodiť AllModelsFailed."""
    user = "Čerstvé titulky:\n\n" + _fmt_articles(new_articles)
    text, model = router.generate(_TRIAGE_SYSTEM, user, max_tokens=1024)
    try:
        data = _extract_json(text)
        alerts = [
            Alert(
                title=str(a.get("title", ""))[:250],
                reason=str(a.get("reason", ""))[:400],
                links=[str(x) for x in (a.get("links") or [])][:3],
            )
            for a in data.get("alerts", [])
            if a.get("title")
        ]
    except (ValueError, json.JSONDecodeError, AttributeError, TypeError) as exc:
        log.warning("Triáž: neparsovateľná odpoveď z %s: %s", model, exc)
        return [], model  # nefunkčný výstup = žiadne alerty, surový feed kryje
    return alerts[:5], model


# ---------------------------------------------------------------------------
# Syntéza — TOP témy dňa
# ---------------------------------------------------------------------------

_SYNTHESIS_SYSTEM = """Si skúsený editor slovenskej spravodajskej redakcie. Dostaneš \
titulky a perexy článkov zo slovenských médií za posledné hodiny. Tvoja úloha:

1. Identifikuj 5 až 10 NAJDÔLEŽITEJŠÍCH spravodajských TÉM, ktorými aktuálne žijú \
médiá. Téma = zhluk súvisiacich článkov (aj z rôznych zdrojov), nie jeden titulok. \
Uprednostni témy pokryté viacerými zdrojmi.

2. Ku každej téme napíš:
   - "headline": chytľavý, vecný nadpis (max 90 znakov, bez clickbaitu a otáznikov \
navyše, v slovenčine)
   - "perex": 2-3 vety v žurnalistickom štýle zhŕňajúce podstatu témy. Používaj \
VÝHRADNE informácie z dodaných titulkov a perexov. Žiadne domýšľanie faktov, čísel \
ani mien. Ak titulky protirečia, drž sa opatrnejšej formulácie.
   - "links": 1-3 najreprezentatívnejšie linky k téme z dodaného zoznamu

Zoraď témy od najdôležitejšej. Odpovedz IBA validným JSON bez ďalšieho textu:
{"topics": [{"headline": "...", "perex": "...", "links": ["..."]}]}"""


def synthesize(articles: list[dict]) -> tuple[list[Topic], str]:
    """Vráti (témy, použitý_model). Môže vyhodiť AllModelsFailed."""
    user = "Články za posledné hodiny:\n\n" + _fmt_articles(articles)
    text, model = router.generate(_SYNTHESIS_SYSTEM, user, max_tokens=3072)
    try:
        data = _extract_json(text)
        topics = [
            Topic(
                headline=str(t.get("headline", ""))[:120],
                perex=str(t.get("perex", ""))[:600],
                links=[str(x) for x in (t.get("links") or [])][:3],
            )
            for t in data.get("topics", [])
            if t.get("headline") and t.get("perex")
        ]
    except (ValueError, json.JSONDecodeError, AttributeError, TypeError) as exc:
        log.warning("Syntéza: neparsovateľná odpoveď z %s: %s", model, exc)
        raise AllModelsFailed([f"{model}: neparsovateľný JSON výstup"]) from exc
    return topics[:10], model
