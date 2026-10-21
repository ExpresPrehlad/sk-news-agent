# SK News Agent — diagnostika výpadku redakčného výberu

Dátum: 21. október 2026. Všetky časy v texte sú Europe/Bratislava (UTC+2), pokiaľ nie je uvedené inak.

Rozsah: analýza produkčných GitHub Actions logov, verejného stavu a auditného archívu, zdrojového kódu, verejných katalógov poskytovateľov a offline regresných testov. Žiadne nové generovanie cez API, zmeny produkčného kódu, spúšťanie workflow, odosielanie na Discord ani zmeny nastavení služieb neboli vykonané v rámci diagnostiky.

## 1. Hlavný záver

Nešlo o jeden problém ani o úplné zastavenie agenta. Prekryli sa dva incidenty:

1. Expiroval GitHub token uložený v cron-job.org. Externé spúšťanie vracalo 401 a úloha bola následne neaktívna. Expiráciu potvrdil používateľ v nastavení GitHubu. Po výmene tokenu test vrátil 204 a vznikli nové záložné behy.
2. Tvorba Top tém opakovane vyčerpala celý reťazec modelov. Silnejšie Gemini modely vracali kvóty, 503 alebo timeouty, odpovede 3.5 Flash-Lite odmietala lokálna kontrola a zálohy OpenRouter výber nezachránili. Agent preto ponechal predchádzajúci platný digest, hoci ďalej zbieral a publikoval správy.

Počas diagnostiky nastalo obnovenie: 21. 10. o **10:20:49** vznikol nový platný digest so **6 témami cez Gemini 3.5 Flash-Lite**. Prvé dva Gemini modely aj v tomto behu vrátili 503. Ide o potvrdené obnovenie tvorby výberu, nie o dôkaz, že všetky príčiny a záložné modely sú už opravené.

Nasadenie [GitHub Pages 39568576922](https://github.com/ExpresPrehlad/sk-news-agent/actions/runs/39568576922) úspešne skončilo o **10:22:19**. Následná kontrola verejného webu potvrdila hlavičku 10:20:49, nový vedúci titulok „Trumpov vyslanec Steve Witkoff pricestoval do Ruska“ a `version.json` s hodnotou `1792570849169`. Starý vedúci titulok o bani v Kolumbii už na stránke nebol. Web z uložených tém zobrazuje prvých päť, čo je súčasný dizajn, nie strata šiestej témy.

Posledný výber pred incidentom bol z 20. 10. o 08:55:53. Odstup medzi úspešnými výbermi bol približne **25 hodín 25 minút**.

## 2. Časová os a dôkazy

| Čas | Pozorovanie | Význam |
| --- | --- | --- |
| 20. 10. 08:55:53 | 7 tém úspešne vytvoril Gemini 3.1 Flash-Lite | Posledný platný výber pred výpadkom |
| 20. 10. 09:10 | Zber a triáž prešli; syntéza ešte nebola splatná | Bežný beh, nie chyba |
| 20. 10. 09:20 | Záložný trigger prišiel, zber sa podľa intervalu preskočil | Posledný doložený backup trigger pred prestávkou |
| 20. 10. 12:20 a 21:23 | Zber a triáž fungovali, všetky modely syntézy zlyhali | Potvrdený samostatný problém LLM vrstvy |
| 21. 10. 07:53–07:56 | 9 zdrojov OK, 95 nových správ, triáž platná; syntéza zlyhala | API neprestalo úplne fungovať |
| 21. 10. 10:08–10:10 | Po obnovení tokenu 9 zdrojov OK, 63 nových správ; syntéza opäť zlyhala | Oprava tokenu sama nestačila na Top témy |
| 21. 10. 10:10:32 a 10:10:51 | Dva ďalšie behy sa preskočili bez zberu a API volaní | Od posledného zberu ešte neuplynulo 10 minút |
| 21. 10. 10:20:49 | 6 platných tém cez 3.5 Flash-Lite, uloženie stavu úspešné | Spracovanie sa obnovilo bez zmeny kódu |

Hlavné kontrolované behy:

- [Posledný úspech pred incidentom — 39383220734](https://github.com/ExpresPrehlad/sk-news-agent/actions/runs/39383220734)
- [Zlyhanie 20. 10. na obed — 39407144982](https://github.com/ExpresPrehlad/sk-news-agent/actions/runs/39407144982)
- [Zlyhanie 20. 10. večer — 39482947272](https://github.com/ExpresPrehlad/sk-news-agent/actions/runs/39482947272)
- [Zlyhanie 21. 10. ráno — 39552080853](https://github.com/ExpresPrehlad/sk-news-agent/actions/runs/39552080853)
- [Prvý test po výmene tokenu — 39566982686](https://github.com/ExpresPrehlad/sk-news-agent/actions/runs/39566982686)
- [Nový úspešný výber — 39568507791](https://github.com/ExpresPrehlad/sk-news-agent/actions/runs/39568507791)

## 3. Spúšťanie a rozvrh

### Potvrdené

- Natívny GitHub cron je stále nastavený na `*/10 * * * *`.
- Denné pracovné pásmo 08:30–18:00 povoľuje zber po 10 minútach a syntézu po 15 minútach od posledného úspechu. Ide o intervaly vyhodnocované pri príchode triggera, nie o garanciu presnej minúty publikovania.
- Externý plánovač volá `workflow_dispatch` s `backup_trigger=true`; automatický rozvrh sa preto zachováva.
- Natívne `schedule` behy počas incidentu prichádzali s niekoľkohodinovými medzerami. Po zlyhaní externého triggera neposkytli primeranú náhradu.
- Test po výmene tokenu reálne založil workflow o 10:08:02. Ďalší backup beh prišiel o 10:20:21.

### Čo nemožno potvrdiť iba z GitHubu

GitHub log s `backup_trigger=true` sám nerozlíši manuálny test cron-job.org od pravidelného spustenia. Dlhodobú aktiváciu úlohy treba potvrdiť stavom Enabled, uvedeným najbližším termínom a ďalšími pravidelnými záznamami v cron-job.org.

Odporúčanie: povoliť oznámenie pri zlyhaní a automatickom vypnutí úlohy a nastaviť pripomienku pred expiráciou tokenu. Nie je potrebné rozširovať jeho oprávnenia nad vybraný repozitár a Actions write.

Podklad: [cron-job.org FAQ — automatické vypnutie pri opakovaných zlyhaniach](https://cron-job.org/en/faq/), [GitHub — autentifikácia a 401](https://docs.github.com/en/rest/authentication/authenticating-to-the-rest-api), [GitHub — obmedzenia plánovaných behov](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

## 4. Zber, čerstvosť a vstup pre výber

### Zber je funkčný

V podrobne kontrolovaných reálnych behoch hlavný zber hlásil 9 OK / 0 FAIL. V stave z nového úspešného behu sú OK aj všetky štyri športové zdroje. TN Live sa zbiera cez Google News RSS, nie cez predtým blokovanú sitemapu.

Zelený stav zdroja potvrdzuje úspešné získanie a spracovanie feedu, nie úplné pokrytie vydavateľa. Google News má oneskorenie a neúplnosť; dlhšie výpadky zberu mohli znamenať nezachytenie článkov, ktoré medzičasom z feedu vypadli. Takúto stratu sme individuálne nepreukazovali.

### Rekonštrukcia vstupu z 21. 10. približne 10:08

Verejný snapshot `fe6910f3039190c0bd9b547edc119c2f5081cb15` obsahoval:

- 490 článkov v hlavnom rolling bufferi;
- 158 článkov zachytených za posledných 6 hodín;
- 23 vyradených pre publikovanie staršie než 24 hodín;
- **135 kandidátov** po časovom filtri;
- z toho 12 bez známeho času publikovania, ktoré existujúca politika povoľuje;
- 0 predchádzajúcich nadpisov za posledné 4 hodiny;
- približne 51 699 znakov samotného formátovaného zoznamu článkov bez systémového promptu;
- najdlhší zdrojový odkaz 373 znakov.

Model 3.5 Flash-Lite v tomto pokuse uviedol **22 257 vstupných a 1 622 výstupných tokenov**. Kandidátov bolo dostatok; výber sa nepreskočil pre prázdny vstup. Zároveň to nie je dôkaz prekročenia kontextového limitu.

V poslednom úspechu pred incidentom bolo 77 kandidátov a 21 predtým zobrazených nadpisov. Model 3.1 Flash-Lite uviedol 14 360 vstupných, 1 961 výstupných a 3 315 thinking tokenov. Nový úspech o 10:20 použil 23 021 vstupných a 1 360 výstupných tokenov. Väčší vstup teda sám osebe nevysvetľuje zlyhanie.

### Časové poistky zostali zachované

- Mimoriadne: známy čas publikovania maximálne 12 hodín.
- Top témy: kandidáti z posledných 6 hodín zachytenia a známy čas publikovania maximálne 24 hodín.
- Čas zachytenia nie je to isté ako čas publikovania.
- Pri neznámom čase zostáva článok povolený; je to vedomá vlastnosť, nie dôsledok aktuálneho incidentu.
- Filter kandidátov nevyprší už uložený digest. Po zlyhaní môže web naďalej zobrazovať staré Top témy s ich pôvodným časom.

## 5. Výsledky jednotlivých modelov

Tabuľka zachytáva reálny pokus začatý 21. 10. o 10:08. Nie je to nové testovanie modelov počas diagnostiky.

| Model v konfigurácii | Výsledok | Trvanie pokusu |
| --- | --- | --- |
| Gemini 3.8 Flash | HTTP 503 | 0,80 s |
| Gemini 3.5 Flash | HTTP 503 | 0,42 s |
| Gemini 3.5 Flash-Lite | Odpoveď prišla, lokálna validácia ju odmietla: ValueError | 5,08 s |
| Gemini 3.1 Flash-Lite | HTTP 503 | 0,97 s |
| OpenRouter Nemotron 3 Super 120B free | HTTP 404 | 0,19 s |
| OpenRouter Gemma 4 31B free | HTTP 429, klient klasifikoval provider limit/unavailable | 0,28 s |
| OpenRouter Nemotron 3 Ultra 550B free | Nedokončený výstup, finish_reason=length | 89,49 s |

### Gemini: oddeliť kvótu, kapacitu a chybný výsledok

V poslednom úspešnom behu 20. 10. prvé dva modely vrátili explicitnú dennú kvótu 429. Neskoršie pokusy vracali najmä 503 a timeouty. Google opisuje 503 ako dočasnú nedostupnosť alebo nedostatok kapacity; nie je to samo osebe potvrdenie odobratia free tieru. [Referenčné chyby Gemini API](https://ai.google.dev/gemini-api/docs/generate-content/api-errors)

Nový úspech 21. 10. o 10:20:

1. 3.8 Flash: 503 za 0,48 s.
2. 3.5 Flash: 503 za 0,39 s.
3. 3.5 Flash-Lite: platný výber 6 tém za 4,13 s.

Kľúč Gemini teda funguje aspoň pre 3.5 Flash-Lite a jeho odpoveď vie prejsť súčasnou schémou aj validátorom. Nie je dôvod vypnúť bezpečnostnú kontrolu či tvrdiť, že celá schéma je s Gemini nekompatibilná.

### OpenRouter: model v katalógu nemusí znamenať použiteľnú zálohu

Verejný katalóg pri kontrole stále obsahoval všetky tri nastavené `:free` ID s nulovou cenou vstupu a výstupu. Nemotron Super nebol z katalógu odstránený. Jeho jediný uvedený endpoint však pri kontrole hlásil `status=-5`, `uptime_last_30m=0` a chýbajúcu latenciu. To podporuje vysvetlenie nedostupného smerovania; presný význam -5 a úplnú príčinu historickej 404 tým nedokazujeme.

Gemma a Ultra mali v tom istom verejnom prehľade `status=0` a `uptime_last_30m=100`. Ide o verejnú metriku, nie záruku kvóty alebo úspechu nášho účtu.

Naše požiadavky majú `require_parameters=true` a nulové cenové stropy. To je správna ochrana bezplatnej prevádzky, ale zužuje množinu vhodných endpointov. Z logu samotnej 404 nevieme určiť, či jej jedinou príčinou bol stav poskytovateľa alebo aj obmedzenia smerovania.

Pri 429 sa aktuálne neuchováva bezpečný detail chyby poskytovateľa. Stav účtu a spoločné denné počítadlo OpenRouter preto zostávajú neoverené. Nemáme dôkaz, že túto konkrétnu chybu vyrieši nový API kľúč alebo reset kvóty.

Ultra používa limit 6 144 výstupných tokenov vrátane prípadného reasoning rozpočtu. `reasoning.exclude=true` skryje reasoning z odpovede, ale sám osebe ho nevypína. Opakované `length` je potvrdené; aký podiel rozpočtu spotrebovalo uvažovanie, v neúspešných odpovediach momentálne nelogujeme. Bez merania by bolo predčasné iba zvýšiť limit.

Podklady: [verejný katalóg](https://openrouter.ai/api/v1/models), [Super endpointy](https://openrouter.ai/api/v1/models/nvidia/nemotron-3-super-120b-a12b:free/endpoints), [smerovanie a podporované parametre](https://openrouter.ai/docs/guides/routing/provider-selection), [reasoning a tokenový rozpočet](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens), [kvóty účtu](https://openrouter.ai/docs/api_reference/limits).

## 6. Prečo zatiaľ nepoznáme presný dôvod odmietnutia Flash-Lite

`src/llm/contracts.py` kontroluje koreň JSON, polia, počet položiek a prítomnosť každého odkazu v dodanom vstupnom zozname. Tracking parametre môže bezpečne normalizovať, ale nesmie vymyslieť inú článkovú URL.

`src/llm/router.py:65–71` zachytí pôvodnú výnimku a navonok uchová iba jej typ. Viac rozdielnych príčin tak skončí rovnakým textom:

| Skutočný dôvod | Dnešný log |
| --- | --- |
| Prázdne topics | invalid synthesis output (ValueError) |
| Chýbajúci perex | invalid synthesis output (ValueError) |
| Odkaz mimo vstupného zoznamu | invalid synthesis output (ValueError) |

Toto maskovanie bolo reprodukované offline na troch simulovaných odpovediach. Syntakticky chybný JSON v kontrolnom príklade naopak vyvolal `JSONDecodeError`, čo by router zaznamenal s týmto presnejším typom. Existujúci ValueError preto automaticky neznamená pokazenú syntax JSON. Možná je aj odpoveď bez JSON objektu.

Produkčný odmietnutý text sa neukladá. Nevieme spätne dokázať, ktorá z podmienok v konkrétnom pokuse zlyhala. Nový úspech bez zmeny kódu dokazuje, že problém nie je deterministické odmietanie všetkých odpovedí tohto modelu; príčinu starších odmietnutí však neurčuje.

Bezpečný ďalší krok: zaznamenávať strojový kód chyby (napr. `unknown_source_link`, `missing_perex`, `empty_topics`, `invalid_json`), index položky, dĺžku výstupu a počty položiek. Nelogovať tajomstvá, celý prompt, surové odpovede ani reťazec uvažovania. Pri zdrojových odkazoch možno použiť index alebo hash, nie ľubovoľný text poskytovateľa.

Ochranu pred vymyslenými odkazmi zachovať. Nenasadzovať nekontrolované fuzzy priraďovanie ani prijímanie rozpracovaného výstupu. Ak meranie potvrdí chyby kopírovania URL, možno samostatne otestovať vracanie krátkych ID článkov s deterministickým mapovaním na pôvodné URL; nemení to redakčné kritériá, ale vyžaduje vlastné testy.

## 7. Slabé miesta riadenia a dohľadu

### Zelený workflow nie je dôkaz nových Top tém

`main.py` zámerne izoluje zlyhanie LLM od zberu. `_run_synthesis` pri `AllModelsFailed` vráti text chyby a pôvodný digest ponechá. Hlavný `run()` potom uloží stav a vráti 0. Výsledkom je zelený GitHub beh, hoci výber ostal starý. V Job Summary je chyba syntézy uvedená, ale celkové označenie úspechu ju zakrýva.

Odporúčanie: zachovať zber aj pri výpadku modelov, ale osobitne publikovať zdravie LLM vrstvy, čas posledného úspechu a posledný pokus. Ak sa použije nenulový návratový kód, najprv upraviť workflow tak, aby commit a publikovanie zozbieraných dát prebehli aj pri degradácii. Nestačí pridať jednoduché `return 1`, ktoré by preskočilo dnešný commit krok.

### Neúspešná syntéza chýba v dlhodobom audite

Triáž zaznamenáva úplné zlyhanie ako neplatné rozhodnutie. Syntéza pri úplnom zlyhaní skončí ešte pred `record_synthesis`, takže sa do auditného archívu nezapíše. Z histórie výberov potom nemožno rozlíšiť nevykonanú syntézu od opakovane neúspešnej.

Odporúčanie: samostatný technický záznam pokusu s výsledkom, dôvodom a modelmi. Nezamieňať ho s publikovanou témou a nerozbiť existujúci export histórie do Excelu.

### Časový rozpočet nepomáha všetkým zálohám rovnako

Konfigurácia povoľuje približne 180 s na úlohu a najviac 60 s na požiadavku. Gemini má 120 s, ďalších 60 s sa rezervuje pre OpenRouter. Ráno 21. 10. prvé dva Gemini pokusy spotrebovali asi 115,7 s, Flash-Lite ďalších 3,7 s a poslednej Gemini zálohe ostalo približne 0,6 s. Preto ranný timeout 3.1 Flash-Lite sám osebe nepreukazuje dlhodobú nedostupnosť modelu.

Neskoršie pokusy 3.1 však vrátili priamo HTTP 503, takže iba navýšenie timeoutu nevyrieši celý incident.

`requests timeout` navyše nie je striktný wall-clock limit celej požiadavky. Reálny Ultra pokus trval 89,49 s, inokedy približne 100 s. Ranná syntéza prekročila plánovaných 180 s. [Vysvetlenie Requests](https://requests.readthedocs.io/en/latest/user/quickstart/#timeouts)

Odporúčanie: navrhnúť samostatné connect/read limity, minimálny použiteľný čas pre pokus a vhodné poradie modelov. Neskúšať zálohu so zvyšnými zlomkami sekundy. Výstupný rozpočet a latenciu merať podľa úlohy, nie iba zvyšovať všetky limity.

### Cooldown sa medzi behmi nezachová

Po 429 je cooldown uložený iba v pamäti daného procesu. Ďalší GitHub runner skúsi model znova, aj keď predchádzajúci beh rozpoznal dennú kvótu. Pri zlyhaní sa zároveň neposúva `last_synthesis_ts`, takže každý ďalší splatný zber môže spustiť celú reťaz.

Odporúčanie: rozlíšiť dennú kvótu, dočasnú kapacitu a chybný výstup; použiť obmedzený backoff a samostatný čas pokusu. Trvalejší cooldown musí rešpektovať rozdielne modely a poskytovateľov a nesmie zastaviť triáž alebo zber.

### Čas v hlavičke nevyjadruje zdravie výberu

Hlavička aj `version.json` označujú nové vygenerovanie stránky. Top témy majú vlastný starší čas. Preto sa dá správne zobraziť čerstvá hlavička spolu so starým výberom.

Web už kontroluje novú verziu a má aj 10-minútovú poistku refreshu. Keď backend nemá nový digest, refresh ho nevytvorí. Pri dlhom výpadku navyše samotný relatívny čas Top tém nie je výrazným upozornením.

Odporúčanie: pri prekročení rozumného veku v aktívnom pásme jasne uviesť, že ide o posledný úspešný výber, a zobrazovať oddelene čas zberu a čas výberu. Nočné či víkendové plánované prestávky neoznačovať automaticky za incident.

### Skrytá závislosť od Discordu

Nie je príčinou tohto incidentu: logy ukazujú úplné zlyhanie modelov ešte pred odosielaním digestu. Kód však aktualizuje `last_digest` len pri `topics and published`, pričom `published` je úspech `send_digest` na Discord. Pri chýbajúcom/nefunkčnom digest webhooku teda môže platný AI výber nepokročiť ani na webe.

Podobne zlyhanie odoslania nového surového feedu blokuje uloženie celého stavu. Ide o historickú architektúru, ktorú treba zohľadniť pri budúcom vypínaní Discordu, nie o dôvod teraz meniť webhooky.

## 8. Free tier, Argon a modelové zmeny

Aktuálny cenník naďalej uvádza free vstup/výstup pre Gemini 3.8 Flash, 3.5 Flash-Lite a 3.1 Flash-Lite. Argon free tier nemá. Dostupnosť v cenníku nie je garancia kapacity alebo kvóty konkrétneho projektu. [Cenník](https://ai.google.dev/gemini-api/docs/pricing), [limity projektu](https://ai.google.dev/gemini-api/docs/rate-limits).

Google od 8. 10. presmerúva staré ID `gemini-3.5-flash` na `gemini-3.6-flash`. Naše logy uvádzajú požadované ID, nie overené skutočne obsluhujúce ID. Aktualizácia na explicitný nový názov by vyžadovala zmenu konfigurácie, klientského allowlistu a testov. Staré ID však nie je vypnuté, takže samotný prepis názvu negarantuje odstránenie 503. [Changelog](https://ai.google.dev/gemini-api/docs/changelog).

OpenRouter zostáva obmedzený na konkrétne free varianty a nulový cenový strop. Diagnostika neaktivovala billing, platený model ani nové kľúče. Fakturačný režim Google projektu a aktuálne kvóty účtov nie sú overiteľné iba z verejného repozitára.

## 9. Overenie kódu a testy

- Lokálny zdrojový stav: `2717db2b4ad2c5974cbfe520bb34f2f6f46497f3` z 12. 10. 2026. Verejný GitHub potvrdil rovnaký posledný commit pre `src/`; počas incidentu sa zdrojový kód v tejto zložke nemenil.
- Aktuálny stav nového úspešného výberu: `01eda6b0e98f16e79ba1d20a38744dafc92a89df`.
- Existujúca sada: **81 offline testov, všetky prešli** v izolovanom dočasnom prostredí Python 3.12.
- Testy pokrývajú časové filtre, stabilitu UID, TN Live RSS, validáciu obsahu a zdrojových odkazov, odmietnutie useknutých odpovedí, fallback, cenové ochrany, zachovanie starého digestu pri chybe, web a oddelenie športu.
- Samostatne bola simulovaná strata presného dôvodu pri troch rôznych ValueError.
- Testy neoverujú dostupnosť reálnych modelov, účtovú kvótu ani redakčnú kvalitu nových odpovedí. Ich úspech nie je potvrdením zdravia produkčných API.
- Prvý pokus o testy v základnom runtime nemal balíky requests/feedparser. Po vytvorení dočasného prostredia a inštalácii deklarovaných závislostí prešlo všetkých 81 testov. Nešlo o chybu produkčného runnera.

Relevantné miesta pre prípadnú následnú opravu:

- `src/llm/contracts.py:72` — validácia výstupu.
- `src/llm/router.py:38` — časový rozpočet a poradie pokusov.
- `src/llm/router.py:65` — maskovanie konkrétnej validačnej chyby.
- `src/llm/gemini.py:70` — Gemini payload a spracovanie odpovede.
- `src/llm/openrouter.py:54` — OpenRouter požiadavka, tokeny a ochrany.
- `main.py:145` — spracovanie syntézy, audit a podmienka uloženia digestu.
- `main.py:197` — spoločná notifikácia výpadku najviac raz za 6 hodín.
- `src/pages.py:89` — zobrazenie posledného digestu (prvých päť tém).
- `.github/workflows/collect.yml` — rozvrh, concurrency a commit stavu.

## 10. Odporúčaný postup nápravy — ešte nenasadený

### Priorita 1: odstrániť slepé miesta bez zmeny redakčných pravidiel

1. Doplniť bezpečné kódy validačných chýb a samostatný výsledok každého pokusu. Najprv potrebujeme presne vidieť, čo Flash-Lite odmieta.
2. Rozlíšiť stav zberu, triáže, syntézy a publikovania; zaznamenávať aj neúspešné syntézy.
3. Na webe zreteľne označiť starý výber pri zlyhaní a zachovať jeho skutočný čas.
4. Potvrdiť Enabled a ďalšie pravidelné behy cron-job.org; nastaviť oznámenia a pripomienku expirácie tokenu.

Tieto kroky nemusia pridávať žiadne pravidelné AI volania. Zachovajú prísne časové filtre aj kontrolu zdrojov.

### Priorita 2: stabilizovať modelový reťazec na free tier

1. Aktualizovať a otestovať explicitné Gemini ID a podporované parametre; nezamieňať dostupnosť s kvalitou.
2. Vybrať poradie pre syntézu podľa reálnej úspešnosti a rozpočtu. Presunutie Flash-Lite dopredu môže skrátiť výpadky silnejších modelov, ale mení štandardný výber modelu a vyžaduje kontrolu redakčnej kvality.
3. Nahradiť alebo dočasne obísť preukázateľne nepoužiteľnú OpenRouter zálohu až po kontrole kandidáta a jeho free podmienok.
4. Pri Ultra overiť príčinu `length`, reasoning rozpočet a vhodnosť pre časové limity. Neprijímať nekompletný výstup.
5. Zaviesť rozumný backoff po dennej kvóte alebo kapacitnom výpadku, aby zlyhania zbytočne nespotrebúvali free rozpočet.

### Priorita 3: bezpečné overenie a prevencia konfliktov

Opravy robiť len v zdrojových súboroch a testoch, proti čerstvej produkčnej revízii. Necommitovať lokálne prepočítané `data/state.json`, auditné JSONL ani generované `docs/*.html`; tie nech vytvorí produkčný beh. Žiadny force push ani prepis histórie. Po úspešných offline testoch nasadiť úzky balík a vyhodnotiť samostatne:

- prijatie triggera;
- skutočný zber alebo oprávnené preskočenie;
- platný nový digest s povolenými zdrojmi;
- posun času `last_synthesis_ts`;
- auditný záznam;
- úspešný commit a následné Pages nasadenie;
- zhodu verejného webu s novým digestom;
- viacero ďalších splatných cyklov, nie iba jeden zelený beh.

Bez ďalšieho zadania sa nemení prompt, redakčné kritériá, oddelenie športu, časové filtre, billing ani Discord.

## 11. Čo zostáva otvorené

Presný obsah a dôvod odmietnutia historických odpovedí 3.5 Flash-Lite, úplná príčina každej 503, účtový detail OpenRouter 429 a presná miera nezachytenia článkov počas výpadku nie sú z dostupných podkladov spätne dokázateľné. Dočasné obnovenie bez zmeny kódu tieto otázky nezatvára. Najbližší bezpečný technický zásah má byť zlepšenie pozorovateľnosti, nie oslabenie kontrol.
