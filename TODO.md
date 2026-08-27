# TODO – WarAsset

## Fas 1 (grunddatabas + BSData-synk + API + deploy) — HELT klar

Se CLAUDE.md för fullständig dokumentation av schema, synklogik och API.

### Öppna punkter / kända begränsningar

- **Poäng-parsing, edge-cases** (se CLAUDE.md, "Kända begränsningar i
  poäng-parsingen" för full förklaring):
  - Count-baserade prishöjningar (`<modifier type="set">` villkorat på
    modellantal) hanteras bara för mönstret som hittades i Death Guards
    "Plague Marines" (`condition type="atLeast" childId="model"`). Andra
    sätt att uttrycka samma sak i XML:en täcks inte.
  - Kompositionsgrupper med flera alternativa `type="model"`-poster UTAN en
    egen grupp-constraint kan ge ett överskattat `max_count` (grupperna
    borde egentligen vara "välj ett alternativ", inte "lägg till varje
    alternativ").
  - Rekommendation: gör ett bredare stickprov (20-30 enheter över alla tre
    spelsystem, inte bara de 4-5 som verifierades under utvecklingen) mot
    GW:s officiella poänglistor innan poäng från WarAsset används skarpt
    (turneringslistor e.dyl.) — verktyget är byggt för inventering, inte
    som listbyggare.
- **AoS "Regiments of Renown"-hub:** catalogueLink-djupet begränsades
  medvetet till 1 (se `bsdata_sync._MAX_LINK_DEPTH`) efter att en
  obegränsad rekursion drog in >100 000 entries totalt (varje AoS-fraktion
  fick av misstag ~1000+ entries från i praktiken hela spelsystemet, via
  transitiva catalogueLinks genom delade hub-kataloger). Med djup=1
  inkluderas Regiments of Renown-katalogens EGNA formationer under
  fraktioner som länkar dit, men inte de fraktionsbibliotek den i sin tur
  länkar vidare till. Om fler liknande hub-kataloger upptäcks i framtiden
  (nya AoS-utgåvor, andra spelsystem) kan djup=1 behöva ses över igen.
- **Kill Team, dubbla regelutgåvor:** repot håller kvar både
  "2021 - X.cat" och "2024 - X.cat" för flera fraktioner.
  `bsdata_sync._dedupe_versioned_catalogues` behåller bara den nyaste
  årgången per fraktionsnamn (litar på filnamnets "YYYY - "-prefix). Om
  BSData ändrar namngivningskonventionen upphör dedupen att fungera tyst
  (fraktionen dyker då upp två gånger i sök-API:t igen) — värt att
  stickprovskolla efter framtida omsynkar av just Kill Team-repot.
- **`catalogues.bsdata_id`:** kickoff-dokumentet nämnde "catalogueLink id
  från BSData-XML" som källa — vi använder istället katalogens EGNA
  `id`-attribut på `<catalogue>`-rot-elementet (det finns inget separat
  meningsfullt "catalogueLink id" för en katalog i sig, bara för hur ANDRA
  kataloger refererar till den). Se CLAUDE.md, avsnittet om databasschemat.
- **Kill Team, kosmetiskt dataskräp:** ett fåtal "Fire Team"-poster har
  `role="New CategoryLink"` och 0 poäng (bokstavligen vad källfilen säger,
  se CLAUDE.md). INTE filtrerat bort i Fas 2:s UI (skulle synas i sök-
  dropdownen om man sökte efter en sådan post) — värt att städa upp i
  `bsdata_sync.py` om det visar sig störa i praktiken.

### Verifierat under utvecklingen (riktig data, inte antaganden)

- `Intercessor Squad` (40k, Space Marines): 5-10 modeller, 80p grundpris.
- `Assault Intercessor Squad` (40k, Space Marines): 5-10 modeller, 75p.
- `Plague Marines` (40k, Death Guard): 5-10 modeller, 95/130/190p vid
  5/6/8 modeller (count-baserad modifier, se ovan).
- `Poxwalkers` (40k, Death Guard): 10-20 modeller, 65p grundpris.
- `Liberators` (AoS, Stormcast Eternals): 90p — hittades bara efter
  entryLink-fixen (se CLAUDE.md, "Katalog-sammanslagning").
- Full synk + API-flöde kört end-to-end mot skarpa BSData-repon (git clone,
  parsing, `POST /api/units` med riktig `entry_id`, `PUT` med nytt `count`
  som ger rätt `computed_points`, `POST /api/sync` som kör om utan att
  röra den skapade `collection_units`-raden). Slutgiltiga radantal: 40k
  6671 entries/36 kataloger, Kill Team 1028/111, AoS 3602/97 — se
  CLAUDE.md för detaljer.

## Fas 2 (UI) — KLAR (2026-08-26)

Se CLAUDE.md, avsnittet "Fas 2 — UI (KLAR)", för filstruktur, sök-först-
flödet, `kt`→`kill_team`-fixen, sync-knappen och alla medvetna avvikelser
från mockupen. Verifierat med ett tillfälligt Playwright-uppsättning i
scratchpad (ingen befintlig run-skill för repot, `chromium-cli` inte
tillgängligt i den här Windows-miljön) — se samma CLAUDE.md-avsnitt för
vad som täcktes.

### Öppna punkter / kända begränsningar (Fas 2)

- **Ingen run-skill genererad** för WarAsset trots att UI-verifieringen
  krävde ett improviserat Playwright-uppsättning — värt att köra
  `/run-skill-generator` om UI:t byggs ut vidare, så nästa Claude Code-
  session slipper återupptäcka samma sak (npm install playwright, install
  chromium, starta `python app.py`, etc).
- **Fotouppladdning bara vid redigering**, inte vid "Ny enhet" (se
  CLAUDE.md — API:t kräver ett existerande unit-`id`). Skulle kunna lösas
  genom att spara enheten tyst först och sedan öppna om den i redigerings-
  läge, men bedömdes som onödig komplexitet för en engångs-limitation.
- **Filinputen för foto är webbläsarens standardutseende**, inte Nocturne-
  styled (svårt att omstyla `<input type=file>` utan extra JS/knapp-hack).
- **Anpassade enheter saknar helt fraktion/roll** (schemabegränsning, se
  CLAUDE.md) — om Sivan vill kunna filtrera/gruppera anpassade enheter per
  egen fraktion i framtiden krävs en schemaändring i `collection_units`
  (nytt fält, t.ex. `custom_faction`), utanför Fas 1/Fas 2:s scope.
- **`[hidden]`/CSS-specificitetsbugg** hittad och fixad under testningen
  (se CLAUDE.md, `app.css`) — värt att komma ihåg om fler `hidden`-styrda
  element läggs till senare med en klass som sätter `display`.

## Deploy — KLART (Fas 1b, 2026-08-25 — Fas 2:s UI ännu inte deployad, se nedan)

- [x] GitHub-repo `warasset` (Sivan87/WarAsset) kopplat och pushat. Remoten
  är HTTPS, inte SSH (ingen SSH-nyckel mot GitHub konfigurerad på den här
  maskinen eller på servern — se CLAUDE.md, "GitHub").
- [x] Klonat till `/mnt/user/appdata/warasset/app` på Unraid, `.env` skapad
  manuellt på servern, `docker compose -p warasset up -d --build` byggd
  och startad (`warasset-warasset-1`, port 5001).
- [x] Verifierad nåbar både `localhost:5001` på servern och
  `192.168.1.142:5001` över nätverket.
- [x] BSData-synk kör på servern (40k/Kill Team/AoS, radantal i samma
  storleksordning som den lokala Fas 1-verifieringen — se CLAUDE.md för
  exakta siffror och varför de inte är identiska).
- [x] `collection_units`-data verifierad att överleva `docker restart`.
- [ ] Full omstart av själva Unraid-datorn INTE testad (skulle störa annan
  drift, bl.a. BrickRadar på samma server) — `restart: unless-stopped` bör
  räcka men är inte specifikt verifierat för WarAsset.

**Fas 1 (backend + BSData-synk + API + deploy) och Fas 2 (UI) är nu båda
klara OCH driftsatta på Unraid** (2026-08-26, samma deploy-flöde som
Fas 1b). Verifierat live: `http://192.168.1.142:5001/` svarar 200 med
titeln "WarAsset", alla tre statiska filer (`static/css/nocturne.css`,
`static/css/app.css`, `static/js/app.js`) serveras korrekt, containern
`warasset-warasset-1` kör. WarAsset är alltså komplett end-to-end: BSData-
synk, sök-API, CRUD-API och nu ett riktigt UI, allt live.

## Fas 3 (enhetsdetalj/datasheet-vy) — KLAR (2026-08-26)

Se CLAUDE.md, avsnittet "Fas 3 — Enhetsdetalj / datasheet-vy (KLAR)", för
fullständig dokumentation: `entries.profiles`-strukturen per spelsystem,
den rekursiva profil-insamlingen i `bsdata_sync._collect_profiles`,
databasmigreringen (`database._migrate_add_entries_profiles`) och
UI-implementationen. Verifierat med samma improviserade Playwright-
uppsättning som Fas 2.

**UI-historik:** det första utkastet var en liten positionerad popover.
Efter upprepad feedback om att den kändes smal/hoptryckt (trots flera
breddökningar och ett omgjort chip-grid) ersattes den helt av en fullstor
modal-dialog importerad från designcanvasen `Miniatyrarkiv.dc.html`
("Datasheet view dialog", nådd via `claude-ai_Design`-MCP:t) — samma
`dialog-backdrop`-mönster som add/edit-dialogen, med vapenprofiler som
riktiga tabellrader istället för kort. Datamodellen/synken/API:et är
oförändrade sedan innan ombygget.

### Öppna punkter / kända begränsningar (Fas 3)

- **Dialogen visar ALLA tillgängliga vapenprofiler/laddningsalternativ**,
  inte bara den utrustning en spelare råkar ha valt — en medveten
  konsekvens av att `collection_units` bara registrerar antal modeller, inte
  enskilda vapenval (samma registreringsnivå som resten av verktyget). Kan
  uppfattas som "för mycket information" för enheter med många alternativ
  (Plague Marines: 17 profiler, ger 14 tabellrader) — mildrat men inte helt
  åtgärdat av tabellayouten (mycket kompaktare än det tidigare
  kort-per-profil-utkastet), se CLAUDE.md.
- **`_MAX_PROFILE_DEPTH = 10`** i `bsdata_sync.py` är en säkerhetsspärr mot
  orimligt djup/cirkulär nästling, inte grundligt stresstestad mot alla
  ~11 000 entries i de tre repona (bara stickprovskontrollerad: Plague
  Marines 40k, Liberators AoS, Dire Avenger Kill Team). Om framtida
  BSData-ändringar nästlar vapenval djupare än så tappas de tysta
  (returnerar bara tomt för den grenen, kraschar inte synken).
- **`CHAR_ORDER_PRIORITY` i `app.js`** är en manuellt författad
  prioritetslista över vanliga karaktäristik-förkortningar (för att motverka
  att BSData:s alfabetiska XML-ordning läcker in i UI:t, se CLAUDE.md) —
  bara verifierad mot 40k och Kill Team. Ovanliga/framtida
  karaktäristik-namn som inte finns i listan hamnar sist (alfabetiskt),
  inte trasigt, men kan se lite fel ordnade ut tills listan utökas.
- **Ingen ny run-skill** genererad trots samma improviserade Playwright-
  uppsättning som Fas 2 — samma öppna punkt som redan noterades där.

## Fas 4 (referensbilder från miniset.net) — KLAR (2026-08-26)

Se CLAUDE.md, avsnittet "Fas 4 — Referensbilder från miniset.net (KLAR)",
för fullständig dokumentation: URL-strukturen som verifierades live,
matchningsalgoritmen (`miniset_client.py`), rate-limit-implementationen,
databasmigreringen och UI:t. Verifierat med samma improviserade Playwright-
uppsättning som Fas 2/3, samt manuella `curl`-anrop mot ett riktigt körande
`python app.py` (BSData redan synkad lokalt).

### Verifierat under utvecklingen (riktig data, inte antaganden)

- **40k, Death Guard "Plague Marines"** (`catalogue_name` = "Chaos - Death
  Guard", role "Battleline"): rollgissningen ("troops") gav en 2-produkters
  underkategori på FÖRSTA anropet, 100% träff mot `gw-99810102007`
  ("Plague Marines"). Total tid ~10-11 sekunder (ett enda rate-limitat
  anrop). Verifierat både via `miniset_client.match_unit()` direkt, via
  `POST /api/units` (auto-trigger i bakgrunden) och via `POST
  /api/units/<id>/fetch-image` (manuell, synkron).
- **40k, Space Marines "Intercessor Squad"** (bas-fraktionsraden, INTE en
  kapitel-specifik rad som Salamanders/Blood Angels): 100% träff mot
  `gw-99120101309`.
- **AoS, Stormcast Eternals "Liberators"**: fanns INTE på fraktionens
  osorterade första sida (410 produkter totalt, sorterade efter
  relevans/nyhet, inte alfabetiskt) — hittades på sida 2 efter att
  paginerings-fallbacket lades till. 100% träff.
- **Rate-limit mätt**: `_rate_limited_get` garanterar >= 10 sekunder mellan
  att förra anropets svar kom in och att nästa skickas — bekräftat i
  `time`-mätningar runt `match_unit()`-anrop (enstaka anrop ~10.3-10.6s,
  dominerat av den påtvingade väntan, inte nätverkslatensen).
- **Databasmigrering** (`_migrate_add_collection_units_image_fields`) körd
  mot den riktiga, redan existerande utvecklings-databasen (`data/
  warasset.db`, skapad under Fas 1-3) — kolumnerna las till, befintliga
  `collection_units`-rader opåverkade.

### Kända begränsningar i matchningen (flaggat enligt kickoff-dokumentets
### avslutningskrav — INTE en garanterad bildkälla för hela samlingen)

- **Kill Team har strukturellt låg träffsäkerhet.** Verifierat: miniset.net
  katalogiserar Kill Team som LAGBOXAR ("Kill Team: Blades of Khaine",
  "Kill Team: Nachmund", ...), inte enskilda operatörsnamn. En BSData-
  operatör som "Dire Avenger" har därför sällan en direkt motsvarighet att
  fuzzy-matcha mot, oavsett hur bra slug-/kategorigissningen är. Det här är
  en begränsning i DATAKÄLLAN, inte i matchningslogiken — ingen känd fix
  inom ramen för miniset.net.
- **40k-fraktionsrader som bara existerar för att låna in generiska enheter**
  (se CLAUDE.md Fas 1, "Katalog-sammanslagning" — t.ex. en `collection_unit`
  registrerad under "Imperium - Adeptus Astartes - Salamanders" för
  "Assault Intercessor Squad") missar ofta, eftersom miniset.net bara säljer
  den generiska produkten under bas-fraktionen ("Space Marines"), inte under
  varje enskilt kapitel. Verifierat: samma enhet, samma roll, 0% träff under
  "Salamanders" men 100% träff under "Space Marines". Ingen kod-fix planerad
  (skulle kräva att känna igen VILKA fraktioner som är "lånade" kataloger,
  vilket i sin tur skulle kräva att spara den kopplingen från
  `bsdata_sync.py` — utanför Fas 4:s scope).
- **Namnskillnader mellan BSData:s katalognamn och miniset.nets slugs.**
  Bara ETT konkret fall hittat och alias-fixat under utvecklingen
  (`_FACTION_SLUG_ALIASES` i `miniset_client.py`: Kill Teams BSData-katalog
  heter "Asuryani", miniset.net använder "aeldari"). Fler liknande
  mismatchar upptäcks sannolikt i takt med att fler fraktioner faktiskt
  registreras i samlingen — lägg till fler alias-poster i takt med att de
  hittas, snarare än att bygga en uttömmande tabell i förväg.
- **Kill Team/AoS saknar rollbaserade underkategorier på miniset.net**
  (verifierat: både en Kill Team- och en AoS-fraktionssida gav bara "/none/"
  som underkategori, till skillnad från 40k:s troops/elites/hq/vehicles/...).
  Där paginerar matchningen istället igenom den råa fraktionslistans
  FÖRSTA `_MAX_REQUESTS_PER_MATCH` (3) sidor — täcker fler produkter än en
  enda sida, men en stor fraktion (t.ex. AoS Stormcast Eternals: 410
  produkter, ~20/sida) kan fortfarande ha sin produkt på sida 4+, utanför
  taket. En höjning av `_MAX_REQUESTS_PER_MATCH` skulle förbättra täckningen
  linjärt men på bekostnad av längre väntetid per bildhämtning (10 sek/sida).
- **40k:s rollgissning (`_ROLE_CATEGORY_HINTS`) är en approximation.**
  BSData:s 10e-roller (Battleline/Character/Elite/...) mappas mot miniset:s
  ÄLDRE, force-org-liknande kategorier (troops/hq/elites/...) — bara
  stickprovskontrollerad mot ett fåtal roller (Battleline). Roller som
  "Dedicated Transport"/"Fortification"/"Aircraft" har grova eller obefintliga
  gissningar och faller tillbaka på den råa fraktionslistan.
- **Ingen bulk-hämtning** (medvetet, se kickoff-dokumentet) — varje enhet
  måste matchas individuellt, antingen automatiskt vid spara eller via
  "Hämta/matcha om bild"-knappen.
- **Ingen ny run-skill** genererad — samma öppna punkt som Fas 2/3.

## Fas 4b (manuell bildlänk från miniset.net) — KLAR (2026-08-26)

Se CLAUDE.md, avsnittet "Fas 4b — Manuell bildlänk från miniset.net
(KLAR)", för fullständig dokumentation: `image_source`-fältet,
bildextraktionens återanvändning mellan listnings- och produktsidor,
URL-valideringen och skyddet mot att en automatisk om-matchning skriver
över en manuell bild. Verifierat med curl + samma improviserade Playwright-
uppsättning som Fas 2-4.

### Verifierat under utvecklingen (riktig data, inte antaganden)

- **"Chosen of Mortarion"** (`gw-99120102114`) hittades via webbsökning
  (miniset.nets egen sökfunktion fungerar inte, se Fas 4) och länkades
  manuellt mot `Malignant Plaguecaster` (BSData, Death Guard) — bekräftar
  kickoff-dokumentets konkreta multi-hjälte-set-exempel.
- Databasmigreringen kördes mot en databas som redan hade Fas 4:s tre
  bildkolumner (inte bara en helt ny databas) — bekräftar att den
  kolumn-för-kolumn-oberoende kollen faktiskt behövdes (den gamla
  "allt-eller-inget"-varianten hade tyst missat att lägga till
  `image_source`).
- En tvingad om-matchning (`?force=true`) som INTE hittar något skriver
  inte över en befintlig manuell bild — verifierat explicit, se CLAUDE.md.

### Öppna punkter / kända begränsningar (Fas 4b)

- **Ingen validering av att den manuella länken faktiskt är en Games
  Workshop-produkt** eller att bilden är rimlig/relevant — precis som
  fritextsökning i Fas 1:s produktbeslut littar verktyget på att Sivan
  klistrar in rätt länk. `is_miniset_product_url` validerar bara att URL:en
  har RÄTT FORM (miniset.net, `/sets/<id>`), inte att INNEHÅLLET är korrekt.
- **Ingen "ångra"-historik** — om en manuell länk visar sig peka på fel
  produkt finns bara "Ta bort bild" (nollställer helt) eller att klistra in
  en ny länk (skriver över direkt), ingen mellanliggande bekräftelse eller
  historik över tidigare länkade bilder.
- **Ingen ny run-skill** genererad — samma öppna punkt som Fas 2-4.

## Fas 4c (incident: miniset.net-blockering + circuit breaker) — KLAR (2026-08-26)

Se CLAUDE.md, avsnittet "Fas 4c — Incident: miniset.net rate-limit block
(KLAR)", för fullständig dokumentation: root cause-utredningen (varför den
tekniska 10-sekunders-spärren visade sig vara korrekt implementerad redan
innan, och varför bevisen för det exakta orsaksförloppet redan var borta
när incidenten utreddes), circuit breaker-implementationen
(`MinisetBlockedError`, `database.miniset_block`,
`database.miniset_requests`) och den nya observability-tabellen. Verifierat
UTESLUTANDE offline (monkeypatchad `requests.get` + en riktig men
throwaway-DB-instans av `app.py`) — INGEN riktig request skickades till
miniset.net under hela incident-utredningen, per kickoff-dokumentets krav.

### Öppna punkter / kända begränsningar (Fas 4c)

- **Root cause är en välgrundad slutsats, inte ett bevisat faktum.** De
  faktiska request-loggarna från själva incidenttillfället gick förlorade
  (containern återskapades av samma dags Fas 5-redeploy innan utredningen
  började) — se CLAUDE.md för resonemanget kring varför kumulativ
  request-VOLYM under Fas 4/4b:s utvecklings- och testcykel är den mest
  sannolika förklaringen, inte en spärr-bugg (som kodgranskningen
  uteslöt). Om en ny blockering inträffar nu finns äntligen en riktig
  logg (`database.miniset_requests`) att utgå från istället för att
  gissa efteråt.
- **Blockeringsdetekteringen bygger på textmatchning, inte statuskod** —
  den faktiska statuskoden miniset.net svarade med bekräftades aldrig
  (ingen livetrafik gjordes under utredningen). Om miniset.net någon gång
  ändrar den exakta ordalydelsen i sin spärrsida kommer detekteringen att
  missa den tyst (fallet blir bara "inget hittades", inte en krasch) —
  värt att uppdatera `_BLOCK_TEXT_MARKERS` i `miniset_client.py` om det
  upptäcks.
- **`MINISET_BLOCK_COOLDOWN_HOURS`** (default 48h) är inte tillagd i den
  lokala/produktionens `.env` — miljövariabeln är valfri
  (`os.environ.get(...)`-fallback), men om Sivan vill justera
  cooldown-längden krävs ett manuellt tillägg till `.env` på servern
  (kom ihåg detta rör sig INTE med automatiskt med `git pull`, se
  CLAUDE.md-avsnittet om Unraid-servern).
- **Ingen UI-indikator INNAN man klickar** (t.ex. en banner "bildhämtning
  pausad till X") — cooldown-läget syns först när Sivan faktiskt försöker
  en bild-åtgärd och får 503-felmeddelandet. Bedömt tillräckligt för en
  ovanlig, tillfällig incident-lägen — en dedikerad statusindikator vore
  onödig komplexitet för ett läge som (förhoppningsvis) sällan uppstår.

## Fas 6 (automatisk bildmatchning borttagen, manuell länk cachar lokalt) — KLAR (2026-08-27)

Se CLAUDE.md, avsnittet "Fas 6 — Automatisk bildmatchning borttagen,
manuell länk cachar lokalt (KLAR)", för fullständig dokumentation: vad som
togs bort ur `miniset_client.py`/`api.py`/`app.js`, `download_image_bytes`-
nedladdningen, lokal cache under `data/uploads/miniset/`, beslutet att
lämna `image_source='auto'`-rader och gamla hotlinkade bilder OFÖRÄNDRADE
(ingen backfill/migrering), och den nya `GET /uploads/<path:filename>`-
routen som fixar ett latent hål från Fas 2 (fotouppladdningens `photo_path`
saknade en route som faktiskt serverade `/uploads/...` som en rå sökväg).

### Verifierat under utvecklingen

Uteslutande offline (samma stop-the-line-krav som Fas 4c — cooldownen från
Fas 4c-rollouten var fortfarande aktiv till 2026-08-28 under hela den här
fasen): monkeypatchad `requests.get` mot en riktig men throwaway-DB-
instans av hela Flask-appen (`app.test_client()`), 34/34 kontroller gröna
(nedladdning + lokal cache, borttagning av gamla cachade filer vid om-
länkning, `DELETE`-städning, hotlinkade legacy-rader lämnas orörda,
cirkelbrytaren trippar och gör noll ytterligare anrop på ett andra
försök, `/fetch-image` bekräftat borta med `404`). Playwright mot en
lokalt körande server (riktig BSData-synkad databas, ingen riktig
miniset.net-trafik) bekräftade UI:t: ingen auto-matchningsknapp,
uppdaterad fälthint, en ogiltig länk ger bara det egna API:ets `400` utan
att någon request lämnar sidan mot miniset.net.

### Öppna punkter / kända begränsningar (Fas 6)

- **Ingen live-verifiering mot riktiga miniset.net-servrar ännu**
  (kickoff-dokumentets uppgift 5) — måste vänta till cooldownen
  (2026-08-28) har passerat. Måste göras innan deploy till Unraid: länka
  en riktig produktsida, bekräfta att bilden laddas ner och fortsätter
  visas med utgående trafik mot miniset.net blockerad, deploya, verifiera
  live.
- **Befintliga hotlinkade bilder migreras INTE** (medvetet, se CLAUDE.md)
  — de fortsätter fungera som hotlinks tills Sivan manuellt länkar om
  varje enhet. Om Sivan vill ha ALLA bilder lokalt cachade måste hen
  länka om dem en och en (eller be om en engångsmigrering senare, inte
  gjord här för att undvika en burst av nya requests mot miniset.net som
  sidoeffekt av den här fasen).
- **`GET /uploads/<path:filename>`-fixen** är bara indirekt verifierad
  (Flask `test_client()`, inte en riktig webbläsare mot en riktigt
  uppladdad bild) — värt att dubbelkolla vid nästa live-verifiering.
- **Ingen ny run-skill** genererad — samma öppna punkt som alla tidigare
  faser.
