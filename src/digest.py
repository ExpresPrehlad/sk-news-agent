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
    signals: dict[str, object]


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

TRIAGE_POLICY_VERSION = "v2-2026-07-29"

_TRIAGE_SYSTEM = """Si skúsený editor slovenskej spravodajskej redakcie. Dostaneš \
čerstvo publikované titulky zo slovenských médií. Vyber iba MIMORIADNE správy, ktoré \
vyžadujú okamžitú pozornosť redakcie.

ZÁKLADNÝ TEST: nestačí, že je udalosť tragická, šokujúca alebo má obeť. Musí mať \
silnú redakčnú relevanciu pre slovenské publikum A ZÁROVEŇ naliehavosť, veľký verejný \
dosah, pokračujúce nebezpečenstvo alebo mimoriadny systémový význam.

GEOGRAFIA A RELEVANCIA:
- Slovensko má nižší prah, ale ani tu nie je každá smrteľná udalosť mimoriadna.
- Zahraničná udalosť musí byť výnimočného rozsahu, mať priamy dosah na Slovensko, \
zásadný európsky/bezpečnostný význam alebo potenciál prerásť do veľkej udalosti.
- Vzdialená súkromná tragédia bez širšieho dopadu nie je MIMORIADNA.

NEHODY — ZARAĎ najmä:
- nehodu na strategickej alebo štátnej stavbe (nemocnica, diaľnica a podobne), ak \
odhaľuje vážne bezpečnostné zlyhanie, má obete alebo ohrozuje verejnosť,
- banské nešťastie; nehodu v chemickom či významnom priemyselnom podniku s rizikom \
výbuchu, požiaru, úniku látok alebo ďalšieho ohrozenia,
- železničnú nehodu, vykoľajenie alebo závažnú nehodu na železničnom priecestí,
- tragickú nehodu autobusu alebo inej hromadnej dopravy,
- hromadnú nehodu, nehodu s veľkým počtom obetí/zranených, evakuáciou, nebezpečným \
nákladom alebo zásadným výpadkom kritickej dopravnej infraštruktúry.

NEHODY — NEZARAĎ automaticky:
- pravidelnú dopravnú nehodu osobných áut menšieho rozsahu, hoci je smrteľná,
- jednotlivú smrteľnú nehodu bez širšieho verejného dosahu alebo ďalšieho ohrozenia,
- pracovnú nehodu v bežnej prevádzke bez strategického významu a sekundárneho rizika,
- menšiu tragickú nehodu v zahraničí. Takáto správa môže patriť do TOP tém, nie však \
do MIMORIADNE.

KRIMI nie je zakázané. Na Slovensku ho zaraď pri aktívnom ohrození, rozsiahlom \
pátraní, viacerých obetiach, útoku na verejnom mieste/inštitúciu, terorizme alebo \
mimoriadnom verejnom dosahu. Zahraničné krimi zaraď iba pri terorizme, masovom \
verejnom útoku, zásadnom bezpečnostnom význame alebo priamej väzbe na Slovensko. \
Uzavretá súkromná či rodinná tragédia a bulvárne/bizarné krimi v zahraničí nie sú \
MIMORIADNE bez ohľadu na emocionálnu silu titulku.

Ďalšie typické MIMORIADNE udalosti: pád vlády alebo demisia, veľká vojenská \
eskalácia, zásadné rozhodnutie ústavného súdu, zatknutie vrcholného politika, \
teroristický útok, prírodná katastrofa, extrémny jav s rozsiahlym ohrozením alebo \
oficiálnym varovaním (obete nie sú podmienkou), krach banky či menová kríza. Úmrtie \
osobnosti zaraď iba pri výnimočnom spoločenskom význame pre slovenské publikum.

MIMORIADNA správa NIE JE: bežná politická výmena názorov, šport, kultúra, bežné \
počasie, ekonomická štatistika ani pokračovanie známej kauzy bez zásadného posunu.

DÔLEŽITÉ — kontrola duplicity: dostaneš aj zoznam TÉM, ktoré médiá už pokrývali za \
posledné hodiny (sekcia "Už pokryté témy" nižšie — je to len kontext na porovnanie, \
NEPOSUDZUJ tieto položky samotné). Ak niektorý z ČERSTVÝCH titulkov opisuje udalosť, \
ktorá je v tomto kontexte zjavne už prítomná (iný zdroj o nej už písal skôr), \
NEOZNAČUJ ju ako mimoriadnu — ide len o oneskorený duplicitný článok, nie o novú \
informáciu pre redakciu. Označ ju len vtedy, ak prináša zásadne NOVÝ vývoj (potvrdenie, \
ďalšia eskalácia, zásadný nový detail), ktorý v už pokrytom kontexte chýba.

Pracuj VÝHRADNE s dodanými titulkami a perexmi. Nič si nedomýšľaj. Ak vstup \
nepotvrdzuje širší dosah alebo riziko, nepredpokladaj ho. Ak si nie si istý, tému \
NEZARAĎ — môže zostať medzi TOP témami.

Odpovedz IBA validným JSON bez akéhokoľvek ďalšieho textu, v tvare:
{"alerts": [{"title": "...", "reason": "jedna veta uvádzajúca konkrétny dosah", \
"links": ["..."], "signals": {"geography": "slovakia|europe|world|unknown", \
"event_type": "crime|accident|public_transport|industrial|disaster|weather|politics|\
security|economy|other", "direct_slovak_relevance": true, "ongoing_danger": false, \
"public_impact": true, "strategic_infrastructure": false, "mass_casualty": false, \
"terrorism": false, "public_transport": false, "hazardous_materials": false}}]}
Ak nič mimoriadne nie je (najčastejší prípad), vráť: {"alerts": []}"""


_TRIAGE_BOOL_SIGNALS = (
    "direct_slovak_relevance",
    "ongoing_danger",
    "public_impact",
    "strategic_infrastructure",
    "mass_casualty",
    "terrorism",
    "public_transport",
    "hazardous_materials",
)


def _signal_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"true", "1", "yes", "áno", "ano"}


def _clean_triage_signals(value: object) -> dict[str, object]:
    raw = value if isinstance(value, dict) else {}
    signals: dict[str, object] = {
        "geography": str(raw.get("geography", "unknown"))[:30].lower(),
        "event_type": str(raw.get("event_type", "other"))[:40].lower(),
    }
    for key in _TRIAGE_BOOL_SIGNALS:
        signals[key] = _signal_bool(raw.get(key, False))
    return signals


def _fmt_context_titles(articles: list[dict]) -> str:
    """Kompaktný formát pre 'už pokryté témy' — len zdroj + titulok, bez
    liniek/perexov, aby kontext zbytočne nenafukoval token rozpočet."""
    return "\n".join(f"- [{a['s']}] {a['t']}" for a in articles)


def triage(
    new_articles: list[dict], known_context: list[dict] | None = None
) -> tuple[list[Alert], str, bool]:
    """
    Vráti (alerty, použitý_model, výstup_bol_validný).
    Môže vyhodiť AllModelsFailed.

    known_context: nedávno pokryté témy (napr. state.recent_window(6)) —
    pomáha modelu rozpoznať oneskorené duplicity a nepovažovať ich za
    mimoriadne len preto, že sú nové z pohľadu nášho dedup systému.
    """
    user = "Čerstvé titulky:\n\n" + _fmt_articles(new_articles)
    if known_context:
        user += "\n\nUž pokryté témy za posledné hodiny (kontext, neposudzuj tieto):\n"
        user += _fmt_context_titles(known_context)
    text, model = router.generate(_TRIAGE_SYSTEM, user, max_tokens=2048)
    try:
        data = _parse_llm_json(text, "alerts")
        alerts = [
            Alert(
                title=str(a.get("title", ""))[:250],
                reason=str(a.get("reason", ""))[:400],
                links=[str(x) for x in (a.get("links") or [])][:3],
                signals=_clean_triage_signals(a.get("signals")),
            )
            for a in data.get("alerts", [])
            if a.get("title")
        ]
    except (ValueError, json.JSONDecodeError, AttributeError, TypeError) as exc:
        log.warning("Triáž: neparsovateľná odpoveď z %s: %s", model, exc)
        return [], model, False  # surový feed kryje nefunkčný výstup
    return alerts[:5], model, True


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

DÔLEŽITÉ — rotácia proti opakovaniu: dostaneš aj zoznam TÉM, ktoré redakcia už \
videla v predchádzajúcich prehľadoch za posledné hodiny (sekcia "Už zobrazené témy" \
nižšie). Ak niektorá z aktuálnych tém v tomto zozname JE ZJAVNE PRÍTOMNÁ a nedodáva \
zásadne nový vývoj (nie je tam potvrdenie, eskalácia, zásadný nový detail oproti \
tomu, čo redakcia už videla), NEZARAĎ ju znova — uvoľni miesto pre inú, doteraz \
neukázanú tému, aj keby bola objektívne menej významná. Výnimka: ak je téma stále \
najvýznamnejšou udalosťou dňa A prináša skutočne nový, zásadný vývoj (nie len ďalší \
článok o tom istom), môže zostať — ale sformuluj nadpis/perex tak, aby jasne \
odrážal TENTO nový vývoj, nie opakovanie predošlého stavu.

Zoraď témy od najdôležitejšej. Buď stručný — každá téma má byť kompaktná, nie \
esej. Odpovedz IBA validným JSON bez ďalšieho textu:
{"topics": [{"headline": "...", "perex": "...", "links": ["..."]}]}"""


def synthesize(
    articles: list[dict], already_featured: list[str] | None = None
) -> tuple[list[Topic], str]:
    """
    Vráti (témy, použitý_model). Môže vyhodiť AllModelsFailed.

    already_featured: nadpisy tém z predchádzajúcich prehľadov (napr.
    state.recent_digest_headlines(4)) — pomáha modelu rozpoznať a nevracať
    tú istú, nevyvíjajúcu sa tému opakovane naprieč cyklami syntézy.
    """
    user = "Články za posledné hodiny:\n\n" + _fmt_articles(articles)
    if already_featured:
        user += "\n\nUž zobrazené témy za posledné hodiny (nevracaj ich znova, "
        user += "ibaže by prinášali zásadne nový vývoj):\n"
        user += "\n".join(f"- {h}" for h in already_featured)
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
