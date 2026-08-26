# WarAsset

Inventeringsverktyg för Sivans Warhammer-miniatyrer (40k, Kill Team, Age of
Sigmar). Python/Flask + SQLite, en enda Docker-container, driftsatt på
Unraid, öppet på det interna hemnätverket utan inloggning — samma mönster
som referensprojektet BrickRadar (`C:\BrickRadar\BrickRadar-Web`).

**Status: Fas 1 (grunddatabas + BSData-synk + API), Fas 2 (UI), Fas 3
(enhetsdetalj/datasheet-vy), Fas 4 (referensbilder från miniset.net) och
Fas 4b (manuell bildlänk) är ALLA KLARA.** Kickoff-dokumenten ligger kvar
i repot: `fas1-warasset-grunddata-bsdata.md` (backend),
`fas1b-warasset-deploy.md` (GitHub-koppling + deploy), `fas2-warasset-ui.md`
(UI), `fas3-warasset-stats-popover.md` (enhetsdetalj — filnamnet nämner
"popover" men den UI:t landade på är en fullstor dialog, se nedan),
`fas4-warasset-miniset-bilder.md` (referensbilder) och
`fas4b-warasset-manuell-bildlank.md` (manuell bildlänk för de fall den
automatiska matchningen inte kan lösa).

## Produktbeslut

Inget fritextfält för fraktion/poäng/typ i UI:t. Flödet: användaren söker
mot den lokalt synkade BSData-katalogen (`GET /api/entries/search`), väljer
rätt träff, och fraktion/roll/nyckelord/poäng fylls i automatiskt.
Användaren fyller bara i det BSData inte kan veta: antal modeller,
målningsstatus, ev. foto. `entry_id` i `collection_units` är nullable som
en medveten undantagsventil för konverteringar/scratch-builds som inte
finns i BSData — men UI:t ska alltid styra mot sökningen som förstahandsval.

Registreringsnivå: **enheter** (t.ex. "5 st Intercessor Squad"), inte
individuella modeller.

## Databasschema (SQLite, `data/warasset.db`)

- **game_systems** — `id`, `key` (`40k`/`kill_team`/`aos`), `name`,
  `bsdata_repo`, `last_synced_at`. Fylls av `bsdata_sync.GAME_SYSTEMS`.
- **catalogues** — en rad per SPELBAR fraktion (BSData-katalog med
  `library="false"`). `bsdata_id` = katalogens egna `id`-attribut i XML:en
  (inte något separat "catalogueLink id"). `UNIQUE(game_system_id, bsdata_id)`.
- **entries** — en rad per datasheet/enhet. `keywords`, `points_table` och
  `profiles` (Fas 3, se nedan) lagras som JSON-text (avserialiseras till
  listor av `database.py` innan de når API:et). `raw_source_ref` =
  `"<filnamn>::<bsdata-entry-id>"`, för felsökning utan att gissa.
  `UNIQUE(catalogue_id, bsdata_id)` — samma fysiska BSData-unit kan alltså
  finnas som FLERA rader om den är tillgänglig för flera fraktioner (se
  "Katalog-sammanslagning" nedan) — avsiktligt, matchar hur arméer faktiskt
  byggs i spelet.
- **collection_units** — Sivans faktiska samling. `entry_id` pekar på
  `entries` (nullable, se produktbeslutet ovan). `points_override`
  används dels för manuella specialfall, dels automatiskt av
  synken som en skyddsmekanism (se nedan). `status` ∈
  `unbuilt`/`built`/`painted`.

BSData-katalogen är källan till sanning för fraktion/poäng/roll — den egna
tabellen (`collection_units`) lagrar bara ägarskap/status.

### Skydd av användardata vid omsynk

`entries`-raderna skrivs om vid varje synk (UPSERT på `(catalogue_id,
bsdata_id)`, så `entries.id` — och därmed `collection_units.entry_id` — är
STABIL mellan synkar så länge samma BSData-id finns kvar). Om en entry
verkligen försvinner ur BSData (borttagen fraktion/datasheet) kopierar
`database.prune_missing_entries` dess namn/poäng till
`name_override`/`points_override` på ev. `collection_units`-rader INNAN
`entry_id` nollas (`ON DELETE SET NULL`) — så en rad aldrig blir namnlös
eller poänglös bara för att BSData ändrats uppströms.
`collection_units`-tabellen rörs ALDRIG på något annat sätt av synken.

## BSData-synk (`bsdata_sync.py`)

Synkar tre publika repon (kräver ingen token):

| game_system.key | repo | innehåll |
|---|---|---|
| `40k` | `BSData/wh40k-10e` | Warhammer 40,000 |
| `kill_team` | `BSData/wh40k-killteam` | Kill Team |
| `aos` | `BSData/age-of-sigmar-4th` | Age of Sigmar 4:e utgåvan |

**Metod:** `git clone --depth 1` / `git pull --ff-only --depth 1` till
`data/bsdata/<repo-namn>`. Körs vid appstart (bakgrundstråd, blockerar inte
Flask-servern), en gång/dygn (`SYNC_INTERVAL_SECONDS` i `.env`, default
86400), och manuellt via `POST /api/sync` (körs i egen bakgrundstråd, svarar
`202 {"status": "started"}` direkt; `409` om en synk redan pågår).

### Katalog-sammanslagning (viktigt att förstå)

BSData-repona bygger sina fraktioner av flera fysiska `.cat`-filer som
länkar in varandra via `<catalogueLinks><catalogueLink targetId="...">`.
Två varianter av samma mönster hittades och hanteras identiskt
(`bsdata_sync._collect_entries_for_faction`, rekursivt via `targetId`):

1. **AoS**: varje fraktions riktiga units ligger i en separat
   `"<Fraktion> - Library.cat"` (`library="true"`) som huvudfilen
   `"<Fraktion>.cat"` (`library="false"`) länkar in.
2. **40k**: en undergrenskatalog (t.ex. "Blood Angels") länkar in sin
   bas-katalog ("Space Marines", själv spelbar) för att få tillgång till de
   generiska enheterna (Intercessor Squad m.fl.) — dessa dyker alltså upp
   som EGNA rader under både "Blood Angels" och "Space Marines" i
   `entries`, vilket är korrekt (båda arméerna kan faktiskt ta dem).

Endast `.cat`-filer med `library="false"` blir egna rader i `catalogues`.

En registrerbar enhet (datasheet) hittas som ett DIREKT barn av en katalogs
rot, på två sätt (båda verifierade mot riktiga filer, se
`bsdata_sync._direct_unit_entries`):

1. Ett vanligt `<selectionEntry type="unit|model">` MED en egen `<costs>`.
   `type="unit"` är normalformen för trupper (40k/AoS). `type="model"`
   behövs för dels grundläggande enmodells-enheter (fordon, fristående
   karaktärer — t.ex. Space Marines "Rhino"/"Land Raider"), dels är det
   formen Kill Team genomgående använder (varje operatör ÄR enheten, ingen
   trupp-wrapper).
2. Ett `<entryLink type="selectionEntry">` i katalogens EGNA rot-element
   `<entryLinks>` (en SYSKON-tagg till `<selectionEntries>`, inte nästlad i
   den) vars `targetId` pekar på en `type="unit|model"`-post — upptäckt
   genom att Age of Sigmar 4:e utgåvans "Liberators" (Stormcast Eternals)
   annars helt saknade poäng: enhetens regler ligger i
   `"Stormcast Eternals - Library.cat"`, men POÄNGKOSTNADEN (90p) sitter på
   entryLinken i `"Stormcast Eternals.cat"` — filen som faktiskt importerar
   den till arméns lista. Vi använder entryLinkens egna `<costs>`/
   `<modifiers>` när den har några, annars target-elementets — men alltid
   target-elementets `<categoryLinks>`/`<selectionEntryGroups>` för
   roll/nyckelord/modellantal.

Nästlade `type="model"`/`type="upgrade"`-poster INUTI en sådan post (vapen,
enskilda miniatyrer i en trupp) är underval och blir inte egna entries.

Radantal från senaste körningen under utveckling (git pull, inte första
klon): **40k** 36 kataloger / 6671 entries, **Kill Team** 111 kataloger /
1028 entries (efter årgångs-dedup, se nedan — 126 rå kataloger innan),
**AoS** 97 kataloger / 3602 entries.

### Kända begränsningar i poäng-parsingen

Detta var den svåraste delen enligt kickoff-dokumentet, och heuristiken har
verifierats manuellt mot riktiga BSData-filer (`wh40k-10e`:
"Imperium - Space Marines.cat", "Chaos - Death Guard.cat") under
utvecklingen:

- **Grundfallet (vanligast):** en enhets modellantal kan variera inom ett
  tryckt intervall (t.ex. Poxwalkers 10-20, Intercessor Squad 5-10 modeller
  — utläst från `<constraint field="selections" scope="parent">` på
  kompositionsgrupper), men kostar SAMMA poäng oavsett var inom intervallet
  man landar — GW:s nuvarande poängsystem prissätter inte extra lösa
  modeller separat. `points_table` blir här en lista med EN post:
  `[{"count": <lägsta antal>, "points": <baskostnad>}]`.
- **Count-baserade prishöjningar (upptäckt, hanteras):** ett fåtal
  datasheets (bekräftat exempel: Death Guards "Plague Marines") höjer
  priset villkorat på totalt modellantal via
  `<modifier type="set" field="<pts-typeId>"><conditions><condition
  field="selections" type="atLeast" childId="model" value="N">`. Dessa läses
  ut som extra rader i `points_table`
  (`bsdata_sync._count_based_cost_overrides`), t.ex. Plague Marines blir
  `[{5,95},{6,130},{8,190}]`. **Andra sätt att uttrycta samma sak i XML:en
  (annan `condition`-form, villkor på en specifik vapenvariant istället för
  totalt antal, m.m.) täcks INTE** och faller tillbaka till grundfallet ovan.
- **Modellantal (min/max) för ledare utanför grupper:** en obligatorisk
  ensam ledarmodell (t.ex. "Plague Champion") som är en direkt
  `type="model"`-post under enhetens EGNA `<selectionEntries>` (inte
  insvept i en `<selectionEntryGroup>`) räknas med. Om flera sådana
  fristående modeller förekommer OCH saknar egna min/max-constraints kan
  antalet överskattas.
- **Flera alternativ utan grupp-constraint:** när en kompositionsgrupp
  innehåller flera `type="model"`-alternativ (olika vapenlastningar för
  SAMMA slot) och gruppen själv saknar en egen min/max-constraint, summeras
  varje alternativs egna min/max rakt av — kan överskatta maxantalet
  eftersom alternativen egentligen konkurrerar om samma platser istället
  för att läggas till varandra. Påverkar bara `min_count`/`max_count`, inte
  `points_table` i sig.
- Vid uppslagning i API:et (`database._points_for_count`): exakt träff på
  `count` först, annars den post i `points_table` vars `count` ligger
  närmast (inte extrapolerat/interpolerat). `points_override` på
  `collection_units` finns som manuell utväg när uppskattningen är fel.
- **Kill Team, kosmetiskt dataskräp:** ett fåtal entries (t.ex. "Fire Team"-
  grupperingar under "Adeptus Astartes") har `role="New CategoryLink"` och
  `points_table=[{"count":1,"points":0}]` — det är bokstavligen vad
  källfilens `<categoryLink name="New CategoryLink">` respektive
  `<costs><cost value="0">` säger, inte ett tolkningsfel. De är
  formationsreferenser (flera redan prissatta operatörer som grupp), inte
  egna köpbara saker. Inte filtrerat bort — dyker upp i sökresultat men är
  lätta att känna igen (0 poäng, obestämd roll).
- **AoS entryLink-dubbelträff (teoretisk, ovanlig):** om samma enhet nås
  både via ett direkt `entryLink` (med sin egen kostnad) OCH via en
  depth-1-länkad katalogs råa `selectionEntry` (om DEN råkar ha en egen
  giltig kostnad också), vinner den som skrivs sist i loopen (UPSERT).
  Självläkande vid nästa synk om ordningen skulle råka ge fel pris — inte
  observerat i praktiken under utvecklingen, men möjligt i teorin.

**Innan poäng används skarpt (turneringslistor e.dyl.): stickprovskontrollera
alltid mot GW:s officiella poänglista** — den här synken är ett
inventeringsverktyg, inte en listbyggare.

## JSON-API (`/api`, Flask Blueprint i `api.py`)

Inget `X-API-Key`-skydd (produktbeslut — WarAsset har ingen mobilapp och ska
vara helt öppet på hemnätverket). Alla fel som JSON `{"error": "..."}`,
aldrig HTML-felsidor.

| Metod | Path | Beskrivning |
|---|---|---|
| GET | `/api/game-systems` | Lista spelsystem + senaste synktid |
| POST | `/api/sync` | Kör om BSData-synken (bakgrund, `202`/`409`) |
| GET | `/api/entries/search?system=&q=` | Sök i BSData-katalogen |
| GET | `/api/entries/<id>` | Detaljvy för en BSData-post |
| GET | `/api/units?system=&catalogue=&status=` | Lista samlingen |
| POST | `/api/units` | Skapa (`entry_id` ELLER `name_override`, `count`) |
| PUT | `/api/units/<id>` | Redigera |
| DELETE | `/api/units/<id>` | Ta bort |
| POST | `/api/units/<id>/photo` | Ladda upp foto (multipart, fält `photo`) |
| GET | `/api/units/<id>/photo` | Hämta foto |

## GitHub

Repo: `github.com/Sivan87/WarAsset` (kopplat och pushat, se
`fas1b-warasset-deploy.md`). Remoten är satt till HTTPS
(`https://github.com/Sivan87/WarAsset.git`), inte SSH — den här maskinen
saknar en SSH-nyckel registrerad hos GitHub (`ssh -T git@github.com` gav
"Permission denied (publickey)"), medan `gh`s inloggade token + Git
Credential Manager fungerar direkt över HTTPS utan extra steg. Byt inte
till SSH-remoten utan att först lösa nyckelfrågan.

## Unraid-server

- **SSH-alias:** `unraid` (samma som BrickRadar använder, redan
  konfigurerat i SSH-config — pekar mot `192.168.1.142`). Använd ALLTID
  `ssh unraid ...`, aldrig rå IP eller Tailscale/MagicDNS-hostnamnet (går
  inte att slå upp från utvecklingsmiljön).
- **App-sökväg på servern:** `/mnt/user/appdata/warasset/app` (git-klon av
  GitHub-repot, klonad över HTTPS eftersom servern — precis som
  utvecklingsmaskinen — inte har en SSH-nyckel mot GitHub).
- **Compose-projektnamn:** `warasset` (alltid `-p warasset` explicit vid
  `docker compose`-anrop, annars kan Compose falla tillbaka på mappnamnet
  och skapa en dubblettcontainer/portkonflikt).
- **Containernamn:** `warasset-warasset-1`. **Port:** 5001 (inte 5000, som
  BrickRadar använder på samma server).
- **Volym:** `warasset_warasset_data` → `/app/data` (databas, klonade
  BSData-repon, uppladdade foton — allt gitignorat, allt bara på servern).
- **`.env` på servern:** skapad manuellt via `ssh unraid "cat > .../app/.env" <<'EOF' ... EOF`
  (samma innehåll som lokala `.env` — inga hemliga produktionsvärden ännu).
  Detta är den enda filen som INTE följer med `git pull`, eftersom den av
  design inte ligger i git — kom ihåg att uppdatera den manuellt på servern
  om nya nycklar/inställningar läggs till lokalt i framtiden.
- **`git`** är installerat i imagen (`apt-get install -y git` i
  `Dockerfile`) eftersom `bsdata_sync.py` klonar BSData-repon vid körning.

### Deploy-flöde (vid framtida kodändringar)

```
git add -A && git commit -m "..." && git push
ssh unraid "cd /mnt/user/appdata/warasset/app && git pull && docker compose -p warasset up -d --build"
curl http://192.168.1.142:5001/
```

### Verifierat vid första driftsättningen (2026-08-25)

- `docker compose -p warasset up -d --build` byggde och startade rent
  (image `python:3.14-slim`, `git` installerat, `pip install` av Flask/
  python-dotenv, container `warasset-warasset-1` "Up").
- Nås både lokalt på servern (`ssh unraid curl localhost:5001/` → 200) och
  över nätverket (`curl http://192.168.1.142:5001/` från
  utvecklingsmaskinen → 200).
- **OBS, känd Docker/Python-fälla:** `docker logs` visade INTE
  synk-loggraderna (`git clone`/`git pull`/`N kataloger, M entries`) förrän
  processen skrivit tillräckligt mycket annat till stdout — Pythons stdout
  är blockbuffrat (inte radbuffrat) när det inte är kopplat till en TTY,
  vilket Docker-containerns stdout inte är. Loggarna dyker upp med
  fördröjning, inte i realtid. Verifiera synkstatus istället direkt mot
  `GET /api/game-systems` (`last_synced_at`) eller `GET /api/entries/search`
  — inte genom att vänta på `docker logs`. (Skulle kunna fixas med
  `PYTHONUNBUFFERED=1` som miljövariabel i Dockerfilen/compose om
  realtidsloggar blir viktigt senare — inte gjort än.)
- Första BSData-synken på servern gav (via `git pull`, alltså inte första
  klon — se moduldocstring i `bsdata_sync.py`): 40k 36 kataloger/6059
  entries, Kill Team 111/934, AoS 97/3168 — samma storleksordning som den
  lokala verifieringen i Fas 1 (40k 6671, KT 1028, AoS 3602). Skillnaden
  beror på att BSData-repona är levande och fått egna commits mellan de två
  körningarna, inte på ett fel i synken — kontrollerat genom att jämföra
  radantal, inte genom att kräva exakt likhet.
- `collection_units`-data överlever en `docker restart warasset-warasset-1`
  (testat med en tillfällig testenhet, borttagen efteråt): containern kom
  upp igen på några sekunder, raden fanns kvar oförändrad, volymen
  `warasset_warasset_data` fungerar som avsett.
- En full omstart av själva Unraid-datorn har INTE testats (skulle störa
  annan drift på servern, bl.a. BrickRadar) — `restart: unless-stopped` i
  `docker-compose.yml` bör ge samma beteende som BrickRadar redan har där,
  men är inte verifierat specifikt för WarAsset.

## Fas 2 — UI (KLAR)

Bygger på `Miniatyrarkiv.dc.html`-mockupen (design canvas) + Nocturne-
designsystemet (`_ds/nocturne-.../`, båda i `C:\WarAsset`), kopplad mot
Fas 1:s API. Kickoff-dokumentet ligger kvar som `fas2-warasset-ui.md`.

### Filstruktur

- `templates/index.html` — statiskt sidskal (nav, stat-band, toolbar,
  tomma containrar, dialog-markup). Ingen enhetsdata server-renderas —
  allt hämtas och ritas av JS, se nedan.
- `static/css/nocturne.css` — **oförändrad kopia** av designsystemets
  `styles.css` (`_ds/nocturne-.../styles.css`). Rör inte den här filen vid
  ändringar av utseendet — lägg appspecifikt i `app.css` istället, annars
  tappar man spårbarheten mot källdesignsystemet.
- `static/css/app.css` — allt appspecifikt (stat-band, kort/lista-layout,
  combobox-dropdown, grupp-header, animationer), byggt uteslutande på
  Nocturnes `var(--color-*)`/`var(--space-*)`/`var(--radius-*)`-tokens.
  Innehåller en medveten fix: `[hidden] { display: none !important; }` —
  Nocturnes `.dialog-backdrop { display: grid }` slår annars ut webbläsarens
  inbyggda `[hidden]`-standardstil (author-CSS vinner över UA-stilen vid
  lika specificitet), så en "dold" dialog fortsatte annars täcka hela sidan
  och blockera alla klick. Hittades under Playwright-testningen, se nedan.
- `static/js/app.js` — all logik. Ingen frontend-ramverk. Ett `state`-objekt
  + en `render()`/`renderDialog()` för strukturella ändringar (öppna/stänga
  dialogen, byta sök/anpassat-läge, ny sökträff), men RIKTADE DOM-
  uppdateringar (inte full omritning) för tangenttryckningar i textfält
  (namn/antal/poäng) — annars tappar inputen fokus/markörposition på varje
  knapptryck, ett klassiskt vanilla-JS-fallgrop värt att komma ihåg om
  koden byggs ut vidare.

### Sök-först-flödet (produktbeslutet, se fas2-warasset-ui.md)

Add/edit-dialogen har två lägen:
- **Sök-läge (förval):** "Namn"-fältet är en debouncad (250ms) kombobox mot
  `GET /api/entries/search?system=&q=`. Val av en träff låser
  fraktion/roll (skrivskyddade, från `entry.catalogue_name`/`entry.role`)
  och räknar poäng live från `entry.points_table` (samma
  närmaste-träff-uppslagning som `database.py:_points_for_count`,
  återimplementerad i JS som `pointsForCount()` eftersom `GET /api/units`
  inte skickar med rå `points_table` — bara `computed_points`). Byte av
  spelsystem eller ny sökterm nollställer valet.
  - **Vid redigering** av en redan länkad enhet görs ett extra anrop till
    `GET /api/entries/<entry_id>` för att få tag i `points_table` (som
    kickoff-dokumentet förutsåg som en möjlig nödvändighet).
- **Anpassat läge** (litet `← `-växlingslänk längst ner, inte förstahandsval):
  fritt namn + antal + valfria poäng (`points_override`), ingen
  fraktion/roll-inmatning alls — se "Avsiktlig förenkling" nedan för varför.

`POST`/`PUT /api/units` anropas med `entry_id`+`count`+`status`
(sök-läge) eller `name_override`+`count`+`points_override`+`status`
(anpassat läge), matchar API-kontraktet i `api.py`.

### `kt` → `kill_team`

Löst genom att UI:t använder backendens egna nycklar (`40k`/`kill_team`/
`aos`) rakt igenom (`SYSTEM_LABELS` i `app.js`) — mockupens `'kt'` finns
inte kvar någonstans i den riktiga koden.

### "Synka BSData nu"

Ny knapp i navet (fanns inte i mockupen). Anropar `POST /api/sync`, läser
`last_synced_at` för alla tre spelsystem innan och pollar
`GET /api/game-systems` var 3:e sekund (max 2 minuter) tills alla tre
tidsstämplar ändrats, och laddar då om enhetslistan. Visar "En synk körs
redan…" vid `409`.

### Medvetna avvikelser från mockupen

- **Ingen fritextad fraktion/typ för anpassade enheter.** Mockupens
  "Fraktion/armé"- och "Typ"-fält var fria textfält för ALLA enheter.
  `collection_units`-schemat (Fas 1) har dock inget fraktions-/roll-fält
  över huvud taget — bara `name_override`, `points_override`, `count`,
  `status`. Att lägga till ett sådant fält hade varit en schemaändring
  utanför den här fasens uppdrag, så anpassade enheter saknar helt
  fraktion/roll och grupperas gemensamt (se nedan) — en tydlig, avsiktlig
  förenkling, inte ett förbiseende.
- **Gruppering per `catalogue_name`, ingen fast `ARMY_ORDER`-lista.**
  Mockupens grupper kom från en hårdkodad `ARMY_ORDER`/`ARMY_SYSTEM`-lista
  (24 rader seed-data). Med hundratals riktiga fraktioner från BSData-synken
  är en fast lista inte rimlig — grupper sorteras istället alfabetiskt
  (`localeCompare('sv')`), med en samlad "Anpassade enheter"-grupp sist.
- **Rolltyp-filtret är dynamiskt**, inte mockupens fasta `ROLE_ORDER`
  (`['Battleline','Elite','Vehicle','Character']`) — riktig BSData-data
  har många fler och mer varierade rollvärden (t.ex. AoS "HERO"/
  "INFANTRY", eller enstaka dataskräp som "New CategoryLink", se Fas 1:s
  CLAUDE.md-avsnitt om Kill Team). `#role-select` byggs om från de roller
  som faktiskt finns i den inlästa enhetslistan.
- **Inga Phosphor-ikoner** (designsystemets readme.md rekommenderar dem).
  De enda ikonbehoven var gruppens expand/collapse-pil — behölls som
  mockupens enkla text-pil (▶) istället för att dra in ett helt ikon-
  bibliotek för en enda symbol.
- **Fotouppladdning kräver en sparad enhet** (`POST /api/units/<id>/photo`
  behöver ett existerande `id`) — går alltså inte att bifoga foto i
  "Ny enhet"-läget, bara efter att enheten sparats (i "Redigera enhet").
  Filinputen är dessutom webbläsarens omålade standardutseende, inte
  Nocturne-styling — en avgränsad, lågprioriterad kontroll.

### Testat (Playwright, ingen befintlig run-skill för det här repot)

Ingen `.claude/skills/`-run-skill fanns för WarAsset och `chromium-cli`
(körmiljöns normalt föredragna verktyg) var inte tillgängligt i den här
Windows-miljön. Verifierat istället med ett tillfälligt Playwright-projekt
i scratchpad (`npm install playwright && npx playwright install chromium`,
inte en del av repot) mot en lokalt startad `python app.py`. Täckte:
sidladdning med riktig data, galleri/lista-växling, gruppcollapse, sök
"Plague Marines" (system 40k) → korrekt Death Guard-träff, poäng
omräknat live till 130p/190p vid antal 6/8 (samma verifierade testfall som
Fas 1), redigera en befintlig länkad enhet (prefyllnad + omhämtning av
`points_table`), fotouppladdning (verifierat kvarstå efter en full
sidladdning, inte bara i minnet), spelsystem-filter (Kill Team → tom
träfflista visas korrekt), och radering (bekräftat både i UI och direkt
mot `GET /api/units`). Inga konsolfel. En riktig run-skill för WarAsset är
inte skapad — värt att göra via `/run-skill-generator` om UI:t byggs ut
vidare.

## Fas 3 — Enhetsdetalj / datasheet-vy (KLAR)

Klick på ett enhetsnamn (galleri- eller listvy) öppnar en detaljvy med
karaktäristik/vapenprofiler/förmågor för den BSData-post enheten är länkad
till. Kickoff-dokumentet ligger kvar som `fas3-warasset-stats-popover.md`.

**UI:t byggdes om en gång under fasen:** det första utkastet var en liten
positionerad popover (samma allmänna idé som kickoff-dokumentet skissade),
men efter upprepad feedback om att den kändes smal/hoptryckt ersattes den
helt av en fullstor modal-dialog, importerad från designcanvasen
`Miniatyrarkiv.dc.html` (dess "Datasheet view dialog", nådd via
`claude-ai_Design`-MCP:t) — samma `dialog-backdrop`-mönster som redan fanns
för add/edit-dialogen, med karaktäristik-rad, förmågor som kort och vapen
som riktiga tabeller (en rad per vapen, inte ett kort per vapen) istället
för ett flödande chip-grid. Se "UI" nedan för den aktuella
implementationen — datamodellen/synken/API:et nedan är OFÖRÄNDRADE av
ombygget.

### `entries.profiles` — struktur

Ny kolumn på `entries`, JSON-text (avserialiseras till en lista av
`database.py`, precis som `keywords`/`points_table`). Varje post:

```json
{"name": "Plague Marine", "type": "Unit", "characteristics": {"M": "5\"", "T": "6", "SV": "3+", "W": "2", "LD": "6+", "OC": "2"}}
```

`name`/`type` kommer rakt av från BSData:s egna `<profile name=...
typeName=...>`-attribut — `typeName` är redan uppslaget klartext i XML:en
(inget behov av att slå upp den mot `.gst`-filens `<profileTypes>`).
`characteristics` är ett `namn → strängvärde`-objekt i samma ordning som
XML:en (t.ex. M/T/SV/W/LD/OC för en 40k-enhet), byggt av
`bsdata_sync._parse_profile_element`. Strukturen är MEDVETET generisk
(inga hårdkodade kolumner à la `M`/`T`) eftersom karaktäristik-seten skiljer
sig mellan spelsystemen — verifierat mot riktiga filer:

| Spelsystem | `type`-värden som förekommer |
|---|---|
| 40k | `Unit`, `Ranged Weapons`, `Melee Weapons`, `Abilities` |
| Kill Team | `Model`/`Operative`, `Weapon`/`Weapons`, `Ability`/`Abilities`, `Equipment`, `Unique Actions`, `Battle Honours`, `Battle Scars`, `Psychic Power` |
| AoS | `Unit`, `Melee Weapon`, `Ranged Weapon`, `Ability (Activated)`, m.fl. |

UI:t (se nedan) delar upp profilerna i separata vapentabeller genom att
regex-matcha `type` mot `/ranged/i`/`/melee/i`/`/weapon/i` — täcker alla
varianterna ovan utan att behöva en hårdkodad lista.

### Insamling av profiler (`bsdata_sync._collect_profiles`)

En enhets fullständiga profillista byggs REKURSIVT från dess `structure_el`
(samma element som redan användes för roll/nyckelord/modellantal), eftersom
BSData:s vapenval i praktiken ligger flera `<selectionEntryGroups>`/
`<entryLinks>`-nivåer under själva unit-entryn snarare än direkt på den
(verifierat mot Death Guards "Plague Marines": Champion-modell →
Wargear-grupp → "Plague knives options"-grupp → `entryLink` → vapnets egna
`<profiles>`, fyra nivåer ner). Insamlingen täcker:

1. Enhetens/nodens EGNA `<profiles><profile>`-element.
2. Delade profiler nådda via `<infoLinks><infoLink type="profile"
   targetId="...">` — samma indirektionsmönster som redan löstes för
   AoS-poäng på `entryLink` i Fas 1, men för profiler som definieras en gång
   i ett rot-nivå `<sharedProfiles>`-block och återanvänds av flera
   selectionEntries (t.ex. en ledarmodells namngivna aura/specialregel).
   Slås upp via `bsdata_sync._build_profile_index`, en global
   `profile-id -> element`-uppslagning byggd med `root.iter("profile")`
   (täcker både nästlade och rot-nivå-profiler i en enda pass).
3. Rekursivt: samma insamling för varje nästlad `<selectionEntry>` (direkt
   eller via `<entryLinks>`, uppslaget via den redan existerande
   `entry_index` från Fas 1) och `<selectionEntryGroup>` under noden, med
   ett djuptak (`_MAX_PROFILE_DEPTH = 10`, säkerhetsspärr — inte ett
   förväntat gränsfall) och dedupe på profil-id
   (`seen_profile_ids`)/nod-id (`visited_entries`) mot cirkulära/
   dubbeldefinierade referenser.

**Medveten konsekvens av det här (inte ett förbiseende):** detaljvyn visar
ALLA tillgängliga vapenprofiler/laddningsalternativ för en enhet (t.ex.
Plague Marines: boltgevär, bultpistol, plasmagevär standard/överladdat,
kraftnäve, pestknivar, ...), inte bara den utrustning som råkar vara vald.
`collection_units` (se produktbeslutet högst upp i den här filen)
registrerar bara ANTAL modeller per enhet, inte enskilda vapenval — samma
registreringsnivå som resten av verktyget. Verifierat manuellt: Death
Guards "Plague Marines" ger 17 profiler (1 statblock + 2 förmågor + 14
vapenalternativ) som alla matchar källfilen
(`data/bsdata/wh40k-10e/Chaos - Death Guard.cat`) vid stickprovskontroll.

### Migrering av befintlig databas

`database._migrate_add_entries_profiles` körs vid varje `init_db()`
(appstart): `PRAGMA table_info(entries)`, och om `profiles`-kolumnen saknas
körs `ALTER TABLE entries ADD COLUMN profiles TEXT NOT NULL DEFAULT '[]'`.
Rör bara `entries` (som ändå skrivs om av nästa synk) — `collection_units`
är, precis som alltid, orörd. Verifierat mot en handbyggd databas med
Fas 1/2:s gamla schema (utan `profiles`-kolumnen) och en riktig
`collection_units`-rad: kolumnen läggs till och raden överlever oförändrad.
Efter migreringen krävs en full omsynk (`POST /api/sync` eller
appstartens automatiska synk) för att fylla `profiles` på befintliga
`entries`-rader — precis som kickoff-dokumentet förutsåg.

### API

Ingen ny endpoint. `GET /api/entries/<id>` returnerade redan hela
entry-raden (`database.get_entry` → `_entry_row_to_dict`), så `profiles`
följer med automatiskt sedan `_entry_row_to_dict` uppdaterades att
`json.loads` den nya kolumnen — samma mönster som `keywords`/`points_table`.
`GET /api/units/<id>` utökades INTE med nästlad entry-data (skulle
duplicera data i varje `/api/units`-svar för inget syfte) — UI:t gör
istället ett andra anrop mot `/api/entries/<entry_id>` när detaljvyn öppnas,
samma mönster som redan fanns i Fas 2:s redigera-enhet-flöde
(`openEditDialog` i `app.js`).

### UI (`static/js/app.js`, `static/css/app.css`, `templates/index.html`)

Importerad från designcanvasen `Miniatyrarkiv.dc.html` (claude.ai/design,
projekt "Warhammer inventeringsverktyg", läst via `claude-ai_Design`-MCP:t)
— dess "Datasheet view dialog". Mockupens layout var hårdkodad för 40k
(manuellt författad SEED-data med fasta `M`/`T`/`SV`/`W`/`LD`/`OC`- och
`Range`/`A`/`BS`/`S`/`AP`/`D`/`Keywords`-kolumner) — här byggs allt istället
DYNAMISKT från `entry.profiles` (se `bsdata_sync._collect_profiles`
ovan), eftersom riktig data spänner tre spelsystem med olika
karaktäristik-set.

- Enhetsnamnet i både galleri- (`.unit-card-name`) och listvy
  (tabellcellen) är en `<button data-action="show-stats"
  data-unit-id="...">` med klassen `.name-link` (bakgrund/kant borttagen,
  ärver text, `:hover`/`:focus-visible` byter till `var(--color-accent)` +
  understrykning — Nocturnes länkfärg, inte en knapp-look).
- `#view-dialog-backdrop` (sist i `<body>` i `index.html`) är samma
  `dialog-backdrop`/`.dialog`-mönster som add/edit-dialogen redan använde i
  Fas 2 (centrerad modal, inte en positionerad popover) — bara en bredare
  modifierarklass `.view-dialog` (`width: min(760px, 100%); max-height:
  88vh; overflow-y: auto`, matchar mockupens mått exakt).
- Stängs vid: klick på backdropen utanför dialogrutan
  (`initViewDialog` i `app.js`, samma `if (e.target === backdrop)`-mönster
  som redan fanns för add/edit-dialogen), klick på "Stäng"-knappen,
  `Escape`-tangenten, och vid VARJE `render()`-anrop (samma säkerhetsnät
  som tidigare — en öppen detaljvy hör ihop med ETT klickat namn).
- **`viewDialogBodyHtml`** delar `entry.profiles` i fyra hinkar:
  - **header** — profilen vars `type` matchar `/^(unit|operative|model)$/i`
    (annars profiles[0] som fallback), renderad som `.view-stat-line`: en
    rad boxade "pills" (`.view-stat-box`, label+värde), en per
    karaktäristik — `grid-template-columns: repeat(auto-fit,
    minmax(64px,1fr))` istället för mockupens hårdkodade `repeat(6,1fr)`,
    så det fungerar för Kill Team-operatörer med 10 karaktäristiker precis
    lika bra som 40k:s 6.
  - **ranged** (`/ranged/i`), **melee** (`/melee/i`) och en tredje,
    generisk **"Vapen"**-hink (`/weapon/i` men varken ranged eller melee —
    fångar Kill Team/äldre AoS-mönster vars vapenprofiler bara heter
    "Weapon(s)" utan räckvidds-distinktion) — var och en sin egen
    `.view-weapons-table`. Kolumnerna byggs som UNIONEN av alla
    karaktäristik-nycklar som förekommer i den hinkens profiler (inte
    mockupens hårdkodade `Range/A/BS/S/AP/D/Keywords`), så en tabell
    fungerar oavsett vilka nycklar spelsystemet råkar använda.
  - **abilities** — allt annat (`Abilities`/`Ability (Activated)`/
    `Equipment`/`Unique Actions`/`Battle Honours`/`Battle Scars`/
    `Psychic Power` m.fl.), renderat som `.view-ability`-kort. En profil med
    EN karaktäristik (det vanliga fallet — `Description`/`Ability`/`Effect`
    beroende på system) visas som ett textstycke, precis som mockupens
    `ab.desc`; en profil med FLERA karaktäristiker (ovanligt) faller
    tillbaka på ett kompakt chip-grid (`.stats-characteristics`/`.stat-chip`,
    kvar från popover-utkastet) istället för att krascha.
- **`CHAR_ORDER_PRIORITY`/`sortedCharKeys`** (i `app.js`): BSData:s XML
  listar en profils `<characteristic>`-element ALFABETISKT (verifierat: en
  40k-vapenprofil kommer ur synken som `A/AP/D/Keywords/Range/S/WS`, inte
  spelets naturliga läsordning) — den ordningen ärvs rakt av i
  `entries.profiles`. En prioritetslista över vanliga förkortningar
  (`M,T,SV,W,LD,OC,...,Range,A,WS,BS,S,AP,D,...,Keywords,...`) sorterar om
  VISNINGSORDNINGEN (inte den insamlade datan) så en datasheet läser som en
  riktig sådan — verifierat att både 40k:s stat-rad (M/T/SV/W/LD/OC) och
  vapenkolumnerna (Range/A/BS/S/AP/D/Keywords för ranged,
  Range/A/WS/S/AP/D/Keywords för melee) nu matchar mockupens ordning exakt.
  Nycklar som inte finns i listan hamnar sist, alfabetiskt.
- Anpassade enheter (`entry_id == null`): namnet ÄR klickbart (enhetlig
  styling/kod, ingen extra villkorsgren i mallarna) men dialogen visar
  "Ingen BSData-koppling — anpassad enhet." istället för att göra ett
  API-anrop — se `openViewDialog` i `app.js`.
- **Fas 2:s `[hidden]`-bugg** (se ovan) gäller fortfarande — dialogen
  återanvänder den redan existerande `.dialog-backdrop`-klassen (samma
  `[hidden] { display: none !important; }`-fix som redan skyddar add/edit-
  dialogen), så ingen ny CSS-specificitetsrisk introducerades. Verifierat
  explicit med Playwright: `page.locator('#view-dialog-backdrop').
  boundingBox()` returnerar `null` i stängt läge.

### Testat (Playwright, samma improviserade uppsättning som Fas 2)

Mot en lokalt startad `python app.py` (venv-python, `.venv/Scripts/
python.exe` — global `python` saknar `flask`/`python-dotenv`). Täckte:
klick på "Plague Marines" (40k) → dialog med korrekt statblock
(M5"/T6/SV3+/W2/LD6+/OC2), 2 förmågekort, en "Ranged Weapons"- och en
"Melee Weapons"-tabell med samtliga 14 vapenalternativ i rätt
kolumnordning, stickprovskontrollerat mot källfilen; klick på "Dire
Avenger" (Kill Team) → samma dialog med KT:s helt andra
karaktäristik-set (M/T/SV/W/LD/Max/A/WS/BS/S) och vapentabellen korrekt
under den generiska "Vapen"-rubriken (KT:s vapenprofiler har ingen
ranged/melee-distinktion i `type`); "Stäng"-knapp, backdrop-klick och
`Escape` stänger alla dialogen; `boundingBox()` är `null` i stängt läge;
en anpassad enhet (utan `entry_id`) visar "Ingen BSData-koppling"-
meddelandet utan krasch; fungerar identiskt från listvyn. Inga
konsolfel. `POST /api/sync` kört om efter migreringen (både direkt via
`bsdata_sync.run_full_sync()` och via det riktiga API:et mot en körande
server) — `collection_units` bekräftat orört i båda fallen,
`entries.profiles` ifyllt för stickprov (Plague Marines 40k, Liberators
AoS, Dire Avenger Kill Team, alla manuellt kontrollerade mot sina
källfiler ovan).

## Fas 4 — Referensbilder från miniset.net (KLAR)

Enheter utan eget uppladdat foto kan visa en produktbild från
[miniset.net](https://miniset.net/) som fallback, matchad on-demand mot
Sivans faktiska samling (inte hela BSData-katalogen). Kickoff-dokumentet
ligger kvar som `fas4-warasset-miniset-bilder.md`. All matchningslogik bor i
en ny modul, `miniset_client.py` — databasschemat, synken och
BSData-API:et är oförändrade av den här fasen.

### Juridiskt/etiskt — hur det faktiskt implementerades

Bilderna är GW:s produktfoton, bara VISADE av miniset.net (icke-kommersiell
"collectors guide"). Ingen bildfil laddas någonsin ner eller lagras —
`collection_units.image_url` pekar rakt på miniset.nets egen filserver
(hotlink) och webbläsaren hämtar bilden direkt därifrån när sidan visas,
precis som kickoff-dokumentet krävde. Bara URL:en cachas (i databasen),
aldrig bildinnehållet.

### URL-struktur (verifierad live under utvecklingen, gissa inte)

- **Spellinje:** `/sets/games-workshop/<spellinje-slug>`, bekräftat:
  `warhammer-40k` (40k), `kill-team` (Kill Team), `warhammer-age-of-sigmar`
  (AoS) — `GAME_LINE_SLUGS` i `miniset_client.py`.
- **Fraktion:** `/sets/games-workshop/<spellinje-slug>/<fraktion-slug>`
  listar alla produkter för fraktionen (osorterad relevans-/nyhetsordning,
  INTE alfabetisk — viktigt för pagineringsbeslutet nedan), med
  pagineringslänkar `.../<fraktion-slug>/page-2`, `page-3`, osv.
- **Underkategori (bara vissa 40k-fraktioner):**
  `/sets/games-workshop/warhammer-40k/<fraktion-slug>/<kategori-slug>/`
  (obs avslutande snedstreck) — en mycket mindre, riktad produktlista.
  Verifierat: Death Guards `infantry`-underkategori gav 2 produkter (varav
  "Plague Marines"), mot 151 på huvudfraktionssidan. Kategorierna är GW:s
  ÄLDRE force-org-liknande indelning (`troops`/`elites`/`hq`/`vehicles`/
  `fast-attack`/`heavy-support`/`dedicated-transport`/`characters`/
  `monstrous-creatures`/...), verifierad mot en Space Marines-fraktionssida.
  **Kill Team och AoS saknar den här indelningen** (verifierat: både en
  Kill Team- och en AoS-fraktionssida gav bara `/none/` som underkategori)
  — se matchningsalgoritmen nedan för hur det hanteras.
- **Produktsida:** `/sets/<produkt-id>` (t.ex. `/sets/gw-99120102128`).
  **Användes till slut INTE** — se nästa punkt.
- **Bild hämtas direkt från listningssidan, inte produktsidan.** Varje
  produkt på en fraktions-/kategorisida ligger i en
  `<div class="set-<nod-id>">` med produktnamn+länk i ett nästlat
  `div.gallery_title a` och en länk till ORIGINALBILDEN (samma fil som
  produktsidans huvudbild) i en nästlad `a.colorbox` (`href` till
  `https://miniset.net/files/set/<produkt-id>-0.<ext>`). Att läsa ut bilden
  direkt härifrån HALVERAR antalet requests per matchning jämfört med att
  också besöka produktsidan — viktigt givet 10-sekunders-kravet nedan.
  DOM-strukturen parsas med BeautifulSoup i
  `miniset_client._parse_category_page`.
- **Ingen fungerande textsökning hittades.** Ett `keys`-formulärfält i
  sidhuvudet filtrerar INTE fraktionslistan i praktiken (testat: identisk
  träfflista med och utan `keys`-parametern). En live-autocomplete-endpoint
  (`/search_api_live_results/search_api_page_1`) testades också men gav
  uppenbart ofiltrerade/orelaterade resultat oavsett query — troligen
  beroende av Drupal-sessionstillstånd (`form_build_id`) som inte går att
  återskapa med ett enkelt GET. Matchningen bygger därför uteslutande på
  fraktions-/kategorilistning + lokal fuzzy-matchning, inte serverside-sök.

### Matchningsalgoritm (`miniset_client.match_unit`)

1. **Fraktionsslug från `catalogue_name`** (`miniset_client._faction_slug`)
   — INTE en rak slugifiering, `catalogues.name` har olika form per
   spelsystem (verifierat mot den riktiga databasen):
   - 40k: alltid `"<Grand Alliance> - [<kapitel/underfraktion> - ]<Fraktion>"`
     (t.ex. `"Chaos - Death Guard"`, `"Imperium - Adeptus Astartes - Space
     Marines"`) → **sista** segmentet efter `" - "`.
   - AoS: `"<Fraktion>[ - <underlista/warband>]"` (t.ex. `"Cities of Sigmar
     - The Iron March"`) → **första** segmentet, omvänt mot 40k.
     `"[LEGENDS]"`-bracket-taggar strippas innan uppdelningen.
   - Kill Team: `catalogues.name` ÄR redan bara fraktionsnamnet.
   - `_FACTION_SLUG_ALIASES`: en liten, INTE uttömmande alias-tabell för
     kända namnskillnader gentemot miniset.net (hittills bara ett fall,
     `asuryani` → `aeldari`, se "Kända begränsningar" i TODO.md).
2. **Kategorigissning från roll, bara för 40k**
   (`_category_candidates_for_role` + `_ROLE_CATEGORY_HINTS`): matchar
   BSData:s roll-sträng (`entries.role`, t.ex. `"Battleline"`) mot
   nyckelord och föreslår 1-2 kandidat-kategorislugs (t.ex.
   `battleline|troop` → `troops`/`infantry`). Kill Team/AoS får ingen
   gissning (ingen känd underkategori-taxonomi där, se ovan).
3. **Anropsbudget** (`_MAX_REQUESTS_PER_MATCH = 3`): rollgissningarna
   (0-2 för 40k) körs FÖRST (högst träffsäkerhet per request), och
   återstående budget läggs på att PAGINERA den råa fraktionslistan
   (sida 1, 2, ...) — bättre täckning än att bara titta på sida 1, särskilt
   för Kill Team/AoS som saknar kategorigissning och därför får hela
   budgeten till paginering. Stoppar tidigt om en näst-perfekt träff
   (score ≥ 97) redan hittats, för att inte slösa requests i onödan.
4. **Fuzzy-matchning:** `rapidfuzz.fuzz.WRatio(entry_name, produktnamn)`
   för varje kandidat över alla hämtade sidor, bästa poäng vinner.
   **Träffsäkerhetströskel: 75** (`MATCH_THRESHOLD`) — valt genom stickprov
   under utvecklingen: en äkta näraträff ("Intercessor Squad" mot
   miniset:s "Intercessors") hamnar strax under 76, medan obesläktade
   produkter (t.ex. "Plague Marines" mot "Death Guard Battleforce: Vile
   Vectorium") hamnar under 40 — 75 skiljer de två robust.

### Rate-limit-implementationen

`miniset_client._rate_limited_get`: ETT globalt `threading.Lock()` +
en modulnivå-tidsstämpel (`_last_request_finished_at`, `time.monotonic()`).
Varje anrop väntar tills minst `MIN_REQUEST_INTERVAL_SECONDS` (10) har
passerat sedan FÖRRA anropets SVAR kom in (inte sedan det skickades) —
en strängare tolkning som håller kravet även om ett enskilt anrop mot
miniset.net skulle vara ovanligt långsamt. Samma lås delas av ALLA
matchningar oavsett trigger (auto-vid-spara eller den manuella
"Hämta bild"-knappen) — en enkel kö, inga parallella anrop mot sajten,
precis som kickoff-dokumentet krävde. Mätt under utvecklingen: enstaka
`match_unit()`-anrop tog 10.3-10.6 sekunder (dominerat av den påtvingade
väntan, inte nätverkslatensen) när fler än ett anrop mot miniset.net
gjordes.

### Databasschema

Tre nya nullable kolumner på `collection_units` (INTE på `entries` — se
skälet i kickoff-dokumentet om att begränsa omfattningen till Sivans
faktiska samling): `image_url`, `image_source_url`, `image_checked_at`.
`database._migrate_add_collection_units_image_fields` lägger till dem för
en databas skapad före Fas 4 (samma `PRAGMA table_info`-mönster som Fas
3:s `_migrate_add_entries_profiles`), verifierat mot den riktiga,
redan existerande dev-databasen.

`image_checked_at` cachar BÅDE positiva och negativa resultat (en negativ
matchning sätter bara `image_checked_at`, `image_url` förblir `NULL`) —
så en enhet utan träff inte matchas om vid varje sidladdning eller
`PUT`. `database.clear_unit_image` (används av `DELETE
/api/units/<id>/image`) nollställer alla tre fälten till "aldrig
kontrollerad", inte bara "kontrollerad, ingen träff" — så en framtida
sparning av enheten kan trigga auto-matchningen på nytt.

### API

- `POST /api/units/<id>/fetch-image` — kör matchningen SYNKRONT (till
  skillnad från auto-triggern, se nedan) eftersom anropet självt är den
  explicita "Hämta bild"-handlingen i UI:t; svarar när matchningen är klar
  (upp till ~30 sekunder, `_MAX_REQUESTS_PER_MATCH` × 10 sekunder).
  Ignorerar `image_checked_at`-cachen medvetet — en manuell begäran ska
  alltid försöka igen. Returnerar `{"matched": false, "reason": "Ingen
  BSData-koppling"}` OMEDELBART (inget nätverksanrop) för enheter utan
  `entry_id` (anpassade enheter) — det finns ingen fraktion att bygga en
  miniset.net-URL mot.
- `DELETE /api/units/<id>/image` — rensar en felaktig automatisk matchning
  via `database.clear_unit_image`. Rör aldrig `photo_path` (eget
  uppladdat foto) — separata fält.
- `GET /api/units`/`GET /api/units/<id>` behövde INGEN kodändring —
  `collection_units.*` i `_UNIT_SELECT` tar redan med de nya kolumnerna
  automatiskt.
- **Auto-trigger vid spara** (`api._trigger_auto_image_fetch`, anropad från
  både `POST /api/units` och `PUT /api/units/<id>`): startar matchningen i
  en daemon-bakgrundstråd (samma mönster som `POST /api/sync`) om enheten
  har `entry_id` men varken `image_url` eller `image_checked_at` än. Körs
  ALDRIG synkront — kickoff-dokumentet krävde uttryckligen att detta inte
  får blockera spara-anropet. Fel i bakgrundstråden loggas men kraschar
  aldrig och syns aldrig för användaren (best-effort-förbättring, inte en
  kritisk del av att spara enheten).
- `app.py`: `app.run(..., threaded=True)` lades till (fanns inte innan) —
  utan den skulle Flasks inbyggda dev-server blockera ALLA andra requests
  medan `POST /api/units/<id>/fetch-image` väntar in rate-limitet.

### UI (`static/js/app.js`, `static/css/app.css`)

- **Prioritetsordning för enhetsbild** (`unitPhotoHtml` i `app.js`, ny
  funktion): (1) eget uppladdat foto (`photo_path`), (2) miniset.net-bild
  (`image_url`, i samma `.lighten`-wrapper som ett riktigt foto skulle
  använda + en diskret "Bild: miniset.net"-källänk längst ner i bilden,
  länkad till `image_source_url`), (3) den ursprungliga "FOTO: {namn}"-
  platshållaren. Separata fält — ett eget foto döljer alltid en ev.
  miniset.net-bild i UI:t men rör aldrig `image_url` i databasen.
  Källänken har `mix-blend-mode: normal` explicit (`.unit-image-credit` i
  `app.css`) eftersom `.lighten` (`mix-blend-mode: lighten`) annars gör den
  mörka textbakgrunds-gradienten osynlig mot Nocturnes mörka tema.
- **"Hämta bild"/"Matcha om bild"-knapp** (`imageActionsHtml` i `app.js`):
  en liten knapp PER ENHETSKORT (både galleri- och listvy), inte i
  redigeringsdialogen — valt design (kickoff-dokumentet gav fritt val
  mellan de två) eftersom det ger direkt åtkomst utan att öppna en dialog.
  Bara synlig för enheter med `entry_id` (ingen fraktion att söka mot för
  anpassade enheter). Text växlar till "Hämtar bild… (kan ta en stund)"
  och knappen inaktiveras under anropet — tydligt att det bara är
  långsamt med flit, inte trasigt (kickoff-dokumentets krav).
  "Ta bort bild"-knappen visas bara när `image_url` redan är satt.
- **Ingen bulk-knapp** (medvetet, se kickoff-dokumentet) — bara en knapp
  per enhet, aldrig "hämta för alla".

### Testat (Playwright + manuella `curl`-anrop)

Mot en lokalt startad `python app.py` (samma venv-uppsättning som Fas 2/3).
Manuella `curl`-anrop täckte: `POST /api/units` med en riktig Death Guard
"Plague Marines"-`entry_id` → auto-triggern hämtade och sparade en korrekt
`image_url`/`image_source_url` inom ~10 sekunder (bekräftat via en
efterföljande `GET /api/units/<id>`); `DELETE .../image` → båda fälten
och `image_checked_at` nollställda; `POST .../fetch-image` (manuell) →
samma träff hämtad om, tidtagen till ~10.3 sekunder (`time curl`); en
anpassad enhet (utan `entry_id`) → `fetch-image` svarade omedelbart
(~0.05s) med `{"matched": false, "reason": "Ingen BSData-koppling"}`,
inget nätverksanrop gjort. Playwright (samma improviserade uppsättning som
Fas 2/3, ny `npm install playwright` + `npx playwright install chromium`
i scratchpad) täckte hela UI-flödet i en riktig webbläsare: lägga till en
Death Guard "Plague Marines" via sök-dialogen, vänta in auto-triggern,
bekräfta att "Bild: miniset.net"-källänken syns på kortet, klicka
"Ta bort bild" (källänken försvinner), klicka "Hämta bild" på nytt (växlar
till laddningstext, sedan tillbaka med bilden återställd), och en anpassad
enhet (visar platshållaren, ingen bild-knapp alls). Inga konsolfel.
Skärmdump tagen och granskad visuellt (korrekt bildvisning, läsbar
källänk, knapparna radbryter snyggt när båda visas). Alla testenheter
raderade efteråt (`DELETE /api/units/<id>`) — databasen lämnad i samma
skick som innan testningen.

## Fas 4b — Manuell bildlänk från miniset.net (KLAR)

Fas 4:s automatiska matchning löser majoriteten av fallen, men två typer av
tvetydiga edge-cases går inte att lösa algoritmiskt — bara Sivan vet vilken
bild som är "rätt":

1. **Flera "sculpts"/utgåvor av samma enhet** (t.ex. Plague Marines finns i
   flera produktversioner på miniset.net — den automatiska matchningen tar
   den första/bästa fuzzy-träffen, inte nödvändigtvis den nyaste utgåvan).
2. **Hjältar sålda i multi-hjälte-set** — verifierat konkret exempel:
   `Malignant Plaguecaster` (BSData, Death Guard) säljs inte som egen box,
   utan som en av tre hjältar i setet "Chosen of Mortarion"
   (`gw-99120102114`). Automatisk NAMNmatchning hittar aldrig det sambandet
   eftersom BSData ser tre separata enheter medan miniset.net bara har EN
   produktsida för hela setet.

Lösningen: ett textfält i redigera-enhet-dialogen där Sivan själv klistrar
in länken till rätt produktsida, istället för att förlita sig på
namnmatchning. Kickoff-dokumentet ligger kvar som
`fas4b-warasset-manuell-bildlank.md`.

### Datamodell — `image_source`

Ny nullable kolumn på `collection_units`: `image_source` (`'auto'` /
`'manual'` / `NULL`). Styr om en bild är SKYDDAD från att skrivas över av
en framtida automatisk om-matchning:

- `'auto'` — satt av `miniset_client.match_unit()` (Fas 4:s vanliga flöde,
  både auto-triggern vid spara och den manuella "Hämta/matcha om
  bild"-knappen). Får skrivas över fritt av en ny automatisk matchning.
- `'manual'` — satt av `POST /api/units/<id>/image-from-url` (Fas 4b).
  Skyddad: `POST .../fetch-image` vägrar skriva över den utan en explicit
  `?force=true`, och UI:t frågar användaren INNAN det anropet ens görs
  (se "API"/"UI" nedan) — båda skyddsnivåerna implementerade samtidigt,
  inte bara en av de två alternativ kickoff-dokumentet gav fritt val
  mellan.
- `NULL` — ingen bild alls, eller en bild som nollställts via
  `DELETE /api/units/<id>/image` (`database.clear_unit_image` nollställer
  `image_source` tillsammans med `image_url`/`image_source_url`/
  `image_checked_at` — "aldrig kontrollerad" igen, inte "kontrollerad,
  ingen träff").

`database._migrate_add_collection_units_image_fields` (samma funktion som
Fas 4, inte en ny) kontrollerar nu VARJE bildkolumn oberoende av de andra
(inte bara "saknas `image_url`") — annars hade en databas som redan körde
Fas 4 (som har `image_url`/`image_source_url`/`image_checked_at` men inte
`image_source`) aldrig fått den nya kolumnen tillagd, eftersom den gamla
kollen bara testade `image_url`. Verifierat mot både en helt ny databas
och den riktiga, redan Fas 4-migrerade utvecklings-/produktions-databasen.

### Bildextraktion från en enskild produktsida — vad som återanvändes och vad som INTE gick

Kickoff-dokumentet bad om att återanvända Fas 4:s bildextraktionslogik
istället för att skriva en ny parser. Verifierat live att en PRODUKTSIDA
(`/sets/<id>`) har en ANNAN DOM-struktur än en LISTNINGSSIDA
(`/sets/games-workshop/<spellinje>/<fraktion>`, som Fas 4:s
`_parse_category_page` redan visste hur man tolkade): en produktsida har
INGEN `div.set-<id>`/`div.gallery_title`-wrapper (den wrappern finns bara
när flera produkter listas sida vid sida i ett galleri) — bara en rå
samling `<a class="colorbox">`-länkar för produktens egna bilder, där den
FÖRSTA (`-0.<ext>`-filen) är huvudbilden, samma konvention som
listningssidans "-0"-bild. Lösningen: bryt ut den gemensamma, ÅTERANVÄNDA
primitiven (`miniset_client._colorbox_image_url(scope)` — "hitta
originalbilden i ett `a.colorbox`-element") ur `_parse_category_page`, och
använd samma primitiv i den nya `fetch_product_image()` — bara den
OMKRINGLIGGANDE sidparsningen är ny (och den är trivial: hela produktsidan
är `scope`, ingen loop över flera block behövs), inte
bildextraktionslogiken i sig.

### Direkt bildfils-länk, inte bara produktsida (tillägg efter Fas 4b)

Sivan efterfrågade att även kunna klistra in en länk direkt till EN
SPECIFIK bild i en produkts galleri (t.ex.
`https://miniset.net/files/set/gw-99120102114-3.jpg` — bild nummer 3 i
"Chosen of Mortarion"-galleriet, inte bara `-0`-huvudbilden en
produktside-länk ger). `fetch_product_image` känner nu igen BÅDA formerna:

- `/sets/<id>` (produktsida) — oförändrat beteende, hämtar sidan och
  bryter ut huvudbilden via `_colorbox_image_url`.
- `/files/set/<id>-<n>.<ext>` (direkt bildfil, `_miniset_file_product_id`)
  — redan den slutgiltiga bild-URL:en, så INGET nätverksanrop görs alls
  (varken rate-limitat eller annat) — bara en formkontroll på URL:en.
  `image_source_url` (krediten på kortet) HÄRLEDS från filnamnets
  produkt-id (`https://miniset.net/sets/<id>`) så attributionslänken ändå
  pekar på en riktig, läsbar produktsida istället för en rå bildfil.

Samma domänvalidering (`urlparse().netloc` exakt mot `miniset.net`/
`www.miniset.net`) gäller för båda formerna — ingen substrängsmatchning.
UI:t (`imageLinkRowHtml` i `app.js`) uppdaterades att nämna båda
alternativen i placeholder-text och en `field-hint`.

### API

- `POST /api/units/<id>/image-from-url` (`api_set_unit_image_from_url`) —
  body `{"source_url": "https://miniset.net/sets/..."}`.
  - **URL-validering** (`miniset_client.is_miniset_product_url`): kräver
    `http(s)://miniset.net/sets/<id>` eller `www.miniset.net`, exakt
    domänjämförelse via `urlparse().netloc` (INTE en substrängs-koll —
    verifierat att `https://miniset.net.evil.com/sets/x` och
    `https://evil.com/miniset.net/sets/x` båda korrekt avvisas). Avvisar
    också giltiga miniset.net-URL:er av fel TYP (en listningssida, en rå
    bildfils-URL under `/files/...`) — bara `/sets/<id>` accepteras.
  - Går igenom SAMMA globala rate-limit-lås som `match_unit()`
    (`_rate_limited_get`, delad funktion — ingen egen låslogik i den nya
    koden).
  - Sparar `image_url` (från `fetch_product_image`), `image_source_url`
    (= den inklistrade länken rakt av) och `image_source = 'manual'` via
    `database.set_unit_image(..., source="manual")`.
  - Fel (ogiltig URL, nätverksfel, 404, ingen bild hittad på sidan) →
    tydligt `{"error": "..."}` med `400`, ALDRIG en tyst no-op — verifierat
    för en icke-miniset.net-URL och en tom `source_url`.
- `POST /api/units/<id>/fetch-image` (Fas 4, oförändrad signatur) — utökad
  med ett skydd: om enheten har `image_source == "manual"` och anropet
  saknar `?force=true`, svarar den `409` med ett tydligt felmeddelande
  istället för att matcha om. UI:t (se nedan) frågar redan användaren
  INNAN det här anropet görs, så 409:an är ett skyddsnät i botten, inte
  den primära kommunikationsvägen.
  - **Verifierat beteende värt att notera:** om `?force=true` skickas men
    den automatiska matchningen INTE hittar något (`mark_unit_image_checked`
    körs, som bara sätter `image_checked_at` — rör aldrig `image_url`/
    `image_source_url`/`image_source`), överlever den manuella bilden
    OFÖRÄNDRAD. Den skrivs bara över om en NY automatisk matchning
    faktiskt hittas. Inte explicit designat så från början, men ett
    naturligt (och önskvärt) resultat av att `mark_unit_image_checked`
    redan bara rörde `image_checked_at` i Fas 4.
- `GET /api/units`/`GET /api/units/<id>` — ingen kodändring, `image_source`
  följer med automatiskt via `collection_units.*`.

### UI (`static/js/app.js`, `static/css/app.css`)

- **Redigera-enhet-dialogen:** ett nytt fält "Länk till rätt bild
  (miniset.net)" + en "Hämta"-knapp (`imageLinkRowHtml`/`fetchManualImage`
  i `app.js`), synligt i BÅDA lägena (sök OCH anpassad — till skillnad
  från fotouppladdning som bara är kopplad till redigeringsläget generellt
  gäller det här också för anpassade enheter, eftersom en manuell länk
  inte behöver fraktion/roll för att fungera). Kräver ett existerande
  unit-id precis som fotouppladdning. Sparar OMEDELBART (samma mönster som
  `uploadPhoto`) — oberoende av dialogens egen "Spara"-knapp, med en
  förhandsvisning av den hämtade bilden direkt i dialogen (`.image-link-
  preview`) plus en badge ("📌 Manuellt vald" / "Auto-matchad") som visar
  `image_source`.
- **Enhetskortet:** `unitPhotoHtml` lägger till en 📌-prefix på
  "Bild: miniset.net"-krediten samt en förklarande `title`-tooltip när
  `image_source === 'manual'` — samma kredit-länk och plats som Fas 4,
  bara en tydligare markering.
- **"Matcha om bild"-knappen** (samma knapp som Fas 4, ingen ny knapp)
  frågar nu `window.confirm(...)` INNAN anropet görs om enheten har en
  manuell bild, och skickar i så fall `?force=true` bara om användaren
  bekräftar — kickoff-dokumentet gav fritt val mellan att vägra på
  serversidan ELLER kommunicera tydligt i UI:t; båda implementerades.
  "Ta bort bild"-knappen visas nu för ALLA enheter med `image_url` (inte
  bara BSData-länkade) eftersom en anpassad enhet kan ha en manuellt länkad
  bild men aldrig en `fetch-image`-knapp (ingen fraktion att auto-matcha
  mot).

### Testat (Playwright + curl, samma improviserade uppsättning som Fas 2-4)

Curl mot en lokalt körande `python app.py`: `POST .../image-from-url` med
den riktiga "Chosen of Mortarion"-länken (`gw-99120102114`, hittad via
webbsökning eftersom miniset.nets egen sökfunktion inte fungerar, se Fas 4)
för `Malignant Plaguecaster` → `image_source: "manual"` sparat korrekt,
trots att den automatiska matchningen precis innan (samma testenhet)
korrekt hade misslyckats (`mark_unit_image_checked`, ingen falsk träff
tvingad fram); `POST .../fetch-image` UTAN `force` på samma enhet → `409`
med tydligt felmeddelande; `POST .../fetch-image?force=true` → `200`,
`matched: false`, men den manuella bilden overifierat oförändrad
efteråt (se ovan); ogiltig URL (`https://example.com/...`) och tom
`source_url` → båda `400` med tydliga felmeddelanden, ingen krasch.
Playwright (ny `npm install playwright` + `npx playwright install
chromium`-körning i scratchpad, samma improviserade uppsättning som
tidigare faser) körd i en riktig webbläsare mot samma server: 📌-markering
och tooltip synliga på ett manuellt länkat enhetskort; redigera-dialogen
visar rätt badge ("📌 Manuellt vald") och förhandsvisning; klick på
"Matcha om bild" på en manuell bild triggar ett `confirm()`-dialogruta
(fångad och bekräftad i testet) INNAN något nätverksanrop görs; bilden
finns kvar efter en bekräftad men resultatlös tvingad om-matchning;
klistra in en ny, giltig miniset.net-länk i dialogens textfält → korrekt
förhandsvisning och badge uppdaterade; klistra in en ogiltig länk → tydligt
felmeddelande visat i dialogen, ingen krasch. Skärmdump tagen och granskad
visuellt: båda testenheterna (Plague Marines, Malignant Plaguecaster) visar
korrekta, olika produktbilder med 📌-markeringen synlig och läsbar. Inga
JS-runtime-fel (en enda loggad post var webbläsarens egen nätverks-
statusloggning av det AVSIKTLIGT ogiltiga anropet, inte en kodkrasch).
Alla testenheter raderade efteråt.
