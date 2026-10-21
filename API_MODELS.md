# Bezpečná aktualizácia API modelov — 5. 10. 2026

## Diagnostika a overenie fallbacku — 21. 10. 2026

Redakčné pravidlá, poradie modelov, časové filtre a nulové cenové stropy sa nemenia.
Pri zlyhaní Gemini sa už používa reťaz OpenRouter; nové meranie tento prechod
výslovne potvrdzuje a rozlišuje ho od skutočne odoslaných HTTP požiadaviek.

- V logu hľadať `provider_transition=gemini->openrouter` a výsledný riadok
  `openrouter_http_requests=N`. Vstup do vetvy ešte neznamená HTTP dopyt:
  chýbajúci kľúč, cooldown alebo vyčerpaný čas ho môžu zastaviť.
- GitHub Actions Summary obsahuje sekciu **Diagnostika LLM / OpenRouter fallback**:
  prítomnosť kľúčov (iba áno/nie), výsledok úlohy, prijatý model a tabuľku pokusov
  s HTTP stavom, trvaním a bezpečným kódom chyby.
- Artefakt `llm-diagnostics-<run_id>-<run_attempt>` obsahuje `llm-diagnostics.json`,
  dostupný 7 dní. Má aj počty tokenov, finish reason, dĺžku odpovede a index/typ
  chybného poľa, ak ich odpoveď umožňuje zistiť. Index položky sa počíta od nuly.
- Príklady dôvodov: `unknown_source_link`, `missing_selection_field`,
  `empty_topics`, `invalid_json`, `daily_quota`, `http_error`, `incomplete_output`.
  Všeobecná výnimka validátora bez známeho typu zostáva `validation_error`.
- Report neobsahuje API kľúče, prompty, články, zdrojové URL, surové odpovede
  ani text uvažovania. HTTP 200 nie je automaticky platný redakčný výber.
- Neúspešná syntéza sa zapisuje aj do existujúceho mesačného auditného JSONL
  ako `decision_valid=false`, `published=false`, bez vybraných tém. Nevytvára
  falošné riadky v Excel exporte; posledný platný digest sa zachová.
- Súbor diagnostiky je iba v dočasnom adresári runnera, necommituje sa do
  `data/` ani `docs/`. Zlyhanie uloženia alebo uploadu diagnostiky nesmie
  blokovať zber alebo commit stavu. Report vznikne aj pri preskočenom behu,
  vtedy obsahuje nula LLM úloh; nevytvárajú sa dodatočné testovacie dopyty.

Po pushi overiť najbližší reálny zber v Actions. Keď Gemini uspeje, OpenRouter
sa správne vôbec nevolá. Pri zlyhaní Gemini overiť prechod, nenulový počet
HTTP požiadaviek a výsledok každého OpenRouter modelu. Prítomnosť secretu
ani samotné prepnutie negarantujú dostupnú kvótu alebo platnú odpoveď.

Offline pokrytie zahŕňa skutočnú klientsku cestu s mockovanou HTTP vrstvou:
503 na Gemini → prijatie OpenRouter odpovede; úspech Gemini bez fallbacku;
zlyhanie všetkých modelov; chýbajúce kľúče; cooldown; vyčerpanie rozpočtu;
neplatné odkazy/JSON; useknutý výstup s reasoning počtami; ochranu tajomstiev
a vytvorenie reportu pri preskočenom CLI behu.

---

Aktualizácia nemení redakčné prompty, pravidlá Mimoriadne, časové filtre,
RSS zdroje, športovú prioritizáciu ani spôsob publikovania.

## Modely a bezplatná prevádzka

- Mimoriadne: Gemini 3.5 Flash-Lite → 3.1 Flash-Lite → 3.5 Flash.
- Top témy: Gemini 3.8 Flash → 3.5 Flash → 3.5 Flash-Lite → 3.1 Flash-Lite.
- Spoločná záloha: Nemotron 3 Super `:free` → Gemma 4 31B `:free` →
  Nemotron 3 Ultra `:free`.
- Pôvodné Gemini modely zostávajú dostupné pri chybe/nedostupnosti nových.
- Nedostupný GPT-OSS 20B free a náhodný `openrouter/free` sa nepoužívajú.
- OpenRouter povoľuje iba tieto explicitné varianty a v každom dopyte má
  nulový cenový strop na vstup, výstup aj požiadavku. Bez platených pluginov,
  platených modelových záloh či nákupu kreditov.
- **Gemini API kľúč musí patriť projektu v režime Free v AI Studio.** Rovnaké
  názvy modelov sú dostupné aj v platenom projekte; kód nevie z názvu kľúča
  overiť fakturačný režim. Aktualizácia billing nemení ani neaktivuje.
- Dostupnosť modelu vo verejnom cenníku negarantuje kvótu konkrétneho účtu.
  Kvóty Gemini overiť v AI Studio; OpenRouter cez `GET /api/v1/key` bez
  zverejnenia kľúča. Bezplatné modely OpenRouter zdieľajú denný limit.

## Ochrana odpovedí a dostupnosti

- Prvý HTTP úspech už nestačí. JSON, povinné údaje a odkazy sa kontrolujú
  pred prijatím modelu; chybný výsledok posúva dopyt na ďalšiu zálohu.
- `{"alerts": []}` je platný výsledok, bez ďalšieho dopytu. Prázdne Top témy
  alebo bezpečnostný verdikt nie sú použiteľný výber.
- Model nesmie vrátiť odkaz mimo aktuálneho vstupného zoznamu článkov.
  Odstránené sledovacie parametre (`utm_*` a podobne) sa bezpečne priradia
  späť k pôvodnému vstupnému odkazu; host, cesta a funkčné parametre sa nemenia.
- Gemini žiada JSON podľa schémy a nízke uvažovanie. Nemotron Super používa
  JSON schému; Gemma JSON režim; Ultra má lokálnu kontrolu bez nepodporovaných
  parametrov. Všetky varianty prechádzajú rovnakou lokálnou validáciou.
- Useknuté/blokované odpovede sa neprijímajú ako kompletné rozhodnutia.
  Myšlienkové časti odpovede sa nevkladajú do JSON výberu.
- Tokenový limit má rezervu pre uvažovanie, nie ďalšie pravidelné volanie API.
- Jedna úloha má časový rozpočet 180 s; Gemini necháva rezervu pre OpenRouter.
  Ide o rozpočet pokusov, nie záruku presného času sieťového prenosu.
- Cooldown po limitoch platí len v rámci jedného procesu/behu. Nie je nová
  databáza kvót a pri ďalšom GitHub behu sa dostupnosť znova overuje dopytom.
  Pri rozpoznanom spoločnom OpenRouter limite sa ďalšie free varianty v tom
  istom behu zbytočne neskúšajú.
- Pri úplnom zlyhaní platí pôvodný režim: zber zostáva, nevymýšľa sa náhradný
  výber a posledný platný prehľad sa neprepisuje chybnou odpoveďou.
- GitHub Actions log obsahuje model, úlohu, trvanie, dostupné počty tokenov
  a dôvody fallbacku. Formát výberovej histórie zostáva nezmenený.

## Overenie a nasadenie

Offline testy s Python 3.12 a existujúcimi závislosťami:

```text
python -m unittest discover -s tests -p "test_*.py" -v
```

Na Windows môže testovacie prostredie navyše potrebovať balík `tzdata`;
GitHub runner Ubuntu už má databázu časových pásiem. Testy používajú
simulované odpovede a nevolajú API ani nepublikujú obsah.

Pred nasadením overiť režim Free a aktívne kvóty projektu. Modelové
redakčné kvality sa nedajú dokázať offline testami; po nasadení skontrolovať
prvé platné rozhodnutia a logy. Testovacie vynútené behy míňajú reálne kvóty.

Commitovať zdrojové súbory, testy a tento dokument, nie lokálne generované
`docs/` alebo `data/`. Po pushi sa API zmena prejaví pri ďalšom úspešnom behu.
Pri potrebe návratu stačí v `src/config.py` nastaviť obe Gemini reťaze na
pôvodné poradie `gemini-3.1-flash-lite`, `gemini-3.5-flash`; ochrany odpovedí
a bezplatných OpenRouter variantov môžu zostať.

Overené zdroje:

- https://ai.google.dev/gemini-api/docs/pricing
- https://ai.google.dev/gemini-api/docs/rate-limits
- https://ai.google.dev/api/generate-content
- https://openrouter.ai/api/v1/models
- https://openrouter.ai/docs/api_reference/limits
- https://openrouter.ai/docs/guides/features/structured-outputs
- https://openrouter.ai/docs/guides/routing/provider-selection
