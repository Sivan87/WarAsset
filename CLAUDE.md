# WarAsset

Inventeringsverktyg för Sivans Warhammer-miniatyrer (40k, Kill Team, Age of
Sigmar). Python/Flask + SQLite, en enda Docker-container, driftsatt på
Unraid, öppet på det interna hemnätverket utan inloggning — samma mönster
som referensprojektet BrickRadar (`C:\BrickRadar\BrickRadar-Web`).

**Status: Fas 1 (grunddatabas + BSData-synk + API) är klar. Fas 2 (UI, se
"Fas 2" nedan) är INTE påbörjad.** Kickoff-dokumentet för Fas 1 ligger kvar
i repot som `fas1-warasset-grunddata-bsdata.md`.

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
- **entries** — en rad per datasheet/enhet. `keywords` och `points_table`
  lagras som JSON-text (avserialiseras till listor av `database.py` innan de
  når API:et). `raw_source_ref` = `"<filnamn>::<bsdata-entry-id>"`, för
  felsökning utan att gissa. `UNIQUE(catalogue_id, bsdata_id)` — samma
  fysiska BSData-unit kan alltså finnas som FLERA rader om den är
  tillgänglig för flera fraktioner (se "Katalog-sammanslagning" nedan) —
  avsiktligt, matchar hur arméer faktiskt byggs i spelet.
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

## Unraid-drift

- Port **5001** (inte 5000, som BrickRadar använder på samma server).
- Volym `warasset_data` → `/app/data` (databas, klonade BSData-repon,
  uppladdade foton — allt under `data/`, gitignorat).
- Deploy-flöde (samma som BrickRadar):
  ```
  git add -A && git commit -m "..." && git push
  ssh unraid "cd /mnt/user/appdata/warasset/app && git pull && docker compose -p warasset up -d --build"
  curl http://192.168.1.142:5001/
  ```
  Använd alltid `-p warasset` explicit vid compose-anrop på servern.
- `Dockerfile` installerar `git` (`apt-get install -y git`) eftersom
  `bsdata_sync.py` klonar BSData-repon vid körning.

## Fas 2 (INTE påbörjad)

UI baserat på `Miniatyrarkiv.dc.html` (design canvas) + Nocturne-
designsystemet, båda i `C:\WarAsset`. Mockupen sparar just nu i
`localStorage` med hårdkodad seed-data och fria textfält för
fraktion/typ/poäng ("army"/"role"/"points" i mockupens state) — de ska
ersättas med sökning mot `GET /api/entries/search` och CRUD mot
`/api/units`.

Notera en terminologiskillnad att lösa i Fas 2: mockupen använder
spelsystem-nycklarna `'40k'` / `'aos'` / **`'kt'`**, medan backend (enligt
kickoff-dokumentets uttryckliga schema) använder **`'kill_team'`**. UI:t
behöver antingen mappa `'kt'` → `'kill_team'` eller (enklare) bytas till att
använda backendens nycklar rakt av.
