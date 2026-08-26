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
