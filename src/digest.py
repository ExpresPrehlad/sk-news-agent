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
    links: list[tuple[str, str]]  # (názov zdroja, url)


# Fallback mapovanie domény → zobrazované meno, pre prípad, že model vráti
# link, ktorý sa presne nezhoduje so vstupným zoznamom (napr. drobná úprava
# URL) — primárna cesta je vždy priame priradenie k vstupným článkom.
_DOMAIN_LABELS: dict[str, str] = {
    "aktuality.sk": "Aktuality",
    "dennikn.sk": "Denník N",
    "pravda.sk": "Pravda",
    "hnonline.sk": "HN",
    "teraz.sk": "Teraz.sk",
    "tnlive.sk": "TN Live",
    "ta3.com": "TA3",
    "noviny.sk": "Noviny.sk",
    "sme.sk": "SME",
    "news.google.com": "Google News",
}


def _domain_label(url: str) -> str:
    from urllib.parse import urlparse
    host = urlparse(url).netloc.lower().removeprefix("www.")
    for domain, label in _DOMAIN_LABELS.items():
        if host == domain or host.endswith("." + domain):
            return label
    return "zdroj"


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


def _repair_truncated_json(text: str, array_key: str) -> dict:
    """
    Záchrana čiastočne useknutého JSON-u (typicky pri dosiahnutí max_tokens
    uprostred generovania). Nájde pole `array_key` a vezme len prvky, ktoré
    sú štrukturálne kompletné (počíta zložené zátvorky mimo reťazcov) —
    posledný, rozostavaný prvok sa zahodí, ale všetko predtým sa zachráni.
    """
    cleaned = re.sub(r"```(?:json)?", "", text).strip()
    m = re.search(rf'"{array_key}"\s*:\s*\[', cleaned)
    if not m:
        raise ValueError(f"Pole '{array_key}' sa v odpovedi nenašlo")

    depth, in_string, escape = 0, False, False
    last_complete_end = None
    for i in range(m.end(), len(cleaned)):
        ch = cleaned[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                last_complete_end = i + 1

    if last_complete_end is None:
        raise ValueError(f"V poli '{array_key}' nie je ani jeden kompletný prvok")

    repaired = cleaned[: m.end()] + cleaned[m.end() : last_complete_end] + "]}"
    return json.loads(repaired)


def _parse_llm_json(text: str, array_key: str) -> dict:
    """_extract_json s automatickým pokusom o opravu useknutého výstupu."""
    try:
        return _extract_json(text)
    except (ValueError, json.JSONDecodeError):
        return _repair_truncated_json(text, array_key)


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

DÔLEŽITÉ — kontrola duplicity: dostaneš aj zoznam TÉM, ktoré médiá už pokrývali za \
posledné hodiny (sekcia "Už pokryté témy" nižšie — je to len kontext na porovnanie, \
NEPOSUDZUJ tieto položky samotné). Ak niektorý z ČERSTVÝCH titulkov opisuje udalosť, \
ktorá je v tomto kontexte zjavne už prítomná (iný zdroj o nej už písal skôr), \
NEOZNAČUJ ju ako mimoriadnu — ide len o oneskorený duplicitný článok, nie o novú \
informáciu pre redakciu. Označ ju len vtedy, ak prináša zásadne NOVÝ vývoj (potvrdenie, \
ďalšia eskalácia, zásadný nový detail), ktorý v už pokrytom kontexte chýba.

Pracuj VÝHRADNE s dodanými titulkami. Nič si nedomýšľaj. Ak si nie si istý, tému \
NEZARAĎ — falošný poplach je horší než ticho (redakcia vidí všetky titulky aj tak).

Odpovedz IBA validným JSON bez akéhokoľvek ďalšieho textu, v tvare:
{"alerts": [{"title": "...", "reason": "jedna veta prečo je to mimoriadne", "links": ["..."]}]}
Ak nič mimoriadne nie je (najčastejší prípad), vráť: {"alerts": []}"""


def _fmt_context_titles(articles: list[dict]) -> str:
    """Kompaktný formát pre 'už pokryté témy' — len zdroj + titulok, bez
    liniek/perexov, aby kontext zbytočne nenafukoval token rozpočet."""
    return "\n".join(f"- [{a['s']}] {a['t']}" for a in articles)


def triage(
    new_articles: list[dict], known_context: list[dict] | None = None
) -> tuple[list[Alert], str]:
    """
    Vráti (alerty, použitý_model). Môže vyhodiť AllModelsFailed.

    known_context: nedávno pokryté témy (napr. state.recent_window(6)) —
    pomáha modelu rozpoznať oneskorené duplicity a nepovažovať ich za
    mimoriadne len preto, že sú nové z pohľadu nášho dedup systému.
    """
    user = "Čerstvé titulky:\n\n" + _fmt_articles(new_articles)
    if known_context:
        user += "\n\nUž pokryté témy za posledné hodiny (kontext, neposudzuj tieto):\n"
        user += _fmt_context_titles(known_context)
    text, model = router.generate(_TRIAGE_SYSTEM, user, max_tokens=1024)
    try:
        data = _parse_llm_json(text, "alerts")
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

1. Identifikuj 5 až 8 NAJDÔLEŽITEJŠÍCH spravodajských TÉM, ktorými aktuálne žijú \
médiá. Téma = zhluk súvisiacich článkov (aj z rôznych zdrojov), nie jeden titulok. \
Uprednostni témy pokryté viacerými zdrojmi.

2. Ku každej téme napíš:
   - "headline": chytľavý, vecný nadpis (max 90 znakov, bez clickbaitu a otáznikov \
navyše, v slovenčine)
   - "perex": PRESNE 2 vety (nie viac), stručne, v žurnalistickom štýle. Používaj \
VÝHRADNE informácie z dodaných titulkov a perexov. Žiadne domýšľanie faktov, čísel \
ani mien. Ak titulky protirečia, drž sa opatrnejšej formulácie.
   - "links": 1-2 najreprezentatívnejšie linky k téme z dodaného zoznamu

Zoraď témy od najdôležitejšej. Buď stručný — každá téma má byť kompaktná, nie \
esej. Odpovedz IBA validným JSON bez ďalšieho textu:
{"topics": [{"headline": "...", "perex": "...", "links": ["..."]}]}"""


def synthesize(articles: list[dict]) -> tuple[list[Topic], str]:
    """Vráti (témy, použitý_model). Môže vyhodiť AllModelsFailed."""
    user = "Články za posledné hodiny:\n\n" + _fmt_articles(articles)
    text, model = router.generate(_SYNTHESIS_SYSTEM, user, max_tokens=4096)
    # Spätné priradenie link → názov zdroja z pôvodných vstupných článkov —
    # spoľahlivejšie než nechať model vracať/hádať mená zdrojov.
    link_to_source = {a["l"]: a["s"] for a in articles}
    try:
        data = _parse_llm_json(text, "topics")
        topics = []
        for t in data.get("topics", []):
            if not (t.get("headline") and t.get("perex")):
                continue
            raw_links = [str(x) for x in (t.get("links") or [])][:3]
            links = [
                (link_to_source.get(link) or _domain_label(link), link)
                for link in raw_links
            ]
            topics.append(
                Topic(
                    headline=str(t["headline"])[:120],
                    perex=str(t["perex"])[:600],
                    links=links,
                )
            )
    except (ValueError, json.JSONDecodeError, AttributeError, TypeError) as exc:
        log.warning("Syntéza: neparsovateľná odpoveď z %s: %s", model, exc)
        raise AllModelsFailed([f"{model}: neparsovateľný JSON výstup"]) from exc
    return topics[:10], model
