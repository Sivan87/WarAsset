# Kickoff: WarAsset – Fas 1: Grunddatabas + BSData-synk

## Bakgrund

WarAsset är ett inventeringsverktyg för Sivans Warhammer-miniatyrer (40k, Kill Team, Age of Sigmar). Det ska byggas och driftas enligt samma mönster som referensprojektet BrickRadar (`C:\BrickRadar\BrickRadar-Web`): Python/Flask + SQLite, en enda Docker-container, driftsatt på Unraid, öppet på det interna hemnätverket utan inloggning.

En UI-mockup finns redan i `C:\WarAsset\Miniatyrarkiv.dc.html` (design canvas, Nocturne-designsystemet i samma mapp). Den mockupen sparar just nu i `localStorage` med hårdkodad seed-data och fria textfält för fraktion/typ/poäng — det är exakt de delarna som ska ersättas i den här fasen (backend) och nästa (Fas 2, UI).

**Viktig produktbeslut (bekräftat med Sivan 2026-08-25):** Inget fritextfält för fraktion/poäng/typ. Flödet ska vara: användaren söker (t.ex. "Plague Marines") mot den lokalt synkade BSData-katalogen, väljer rätt träff, och verktyget fyller automatiskt i fraktion, roll, nyckelord och poäng. Användaren fyller bara i det BSData inte kan veta: antal modeller, målningsstatus, ev. foto. Den här fasen (Fas 1) bygger grunden för det: datamodell + synktjänst + sök-API. UI:t som faktiskt använder sök-API:t är Fas 2.

Registreringsnivå: **enheter** (t.ex. "5 st Intercessor Squad"), inte individuella modeller — samma nivå som mockupen redan har.

## Uppgifter

### 1. Projektstruktur

Skapa ett nytt repo/projekt `warasset` med samma grundlayout som BrickRadar-Web:
- `app.py` — Flask-app, HTML-routes (byggs ut i Fas 2)
- `api.py` — Flask Blueprint under `/api` för JSON-endpoints
- `database.py` — SQLite-anslutning, schema, CRUD-funktioner (spegla BrickRadar-mönstret: en enkel process-global write-lock för SQLite-skrivningar, se `database.py`s `_write_lock` i BrickRadar som referens)
- `bsdata_sync.py` — synktjänst mot BSData (se uppgift 3)
- `requirements.txt`, `Dockerfile`, `docker-compose.yml`, `.env` (gitignored), `data/` (persistent volym: databas + ev. bildcache)
- `CLAUDE.md` och `TODO.md` i repo-roten, initiera dem tomma/med grundstruktur — de fylls på under arbetets gång precis som i BrickRadar

**Manuellt steg för Sivan (INTE via Claude Code):** skapa själva GitHub-repot `warasset` (privat eller publikt — inga hemliga data lagras i det här projektet förutom ev. framtida secrets i `.env`, så publikt är ett rimligt val, men Sivan avgör).

### 2. Datamodell (SQLite)

Föreslaget schema — justera vid behov men håll principen "BSData-katalogen är källan till sanning för fraktion/poäng/roll, den egna tabellen lagrar bara ägarskap/status":

- **game_systems**: `id`, `key` (`40k` / `kill_team` / `aos`), `name`, `bsdata_repo` (t.ex. `BSData/wh40k-10e`), `last_synced_at`
- **catalogues**: `id`, `game_system_id`, `bsdata_id` (catalogueLink id från BSData-XML), `name` (fraktionsnamn, t.ex. "Death Guard"), `revision`
- **entries** (datasheets/enheter i BSData): `id`, `catalogue_id`, `bsdata_id`, `name`, `role` (Battleline/Elite/Vehicle/Character/…), `keywords` (JSON-array), `points_table` (JSON-array av `{count, points}` — se uppgift 3 om hur detta parsas), `raw_source_ref` (för felsökning: vilken fil/version den kom från)
- **collection_units** (Sivans faktiska samling): `id`, `entry_id` (FK mot `entries`, **nullable** — se nedan), `name_override` (om `entry_id` är null, eller om man vill döpa om, t.ex. "Min konverterade Typhus"), `count`, `points_override` (nullable — annars beräknas från `entry.points_table` + `count`), `status` (`unbuilt`/`built`/`painted`), `photo_path` (nullable), `created_at`, `updated_at`

`entry_id` är nullable som en medveten undantagsventil (t.ex. konverteringar/scratch-builds som inte finns i BSData) — men UI:t i Fas 2 ska styra mot sökningen som förstahandsval, inte uppmuntra fritext.

### 3. BSData-synktjänst (`bsdata_sync.py`)

Källor att synka (publika repos, kräver ingen token till skillnad från BrickRadars privata app-repo):
- `https://github.com/BSData/wh40k-10e` (Warhammer 40,000)
- `https://github.com/BSData/wh40k-killteam` (Kill Team)
- `https://github.com/BSData/age-of-sigmar-4th` (Age of Sigmar, aktuell utgåva)

**Metod:** `git clone`/`git pull` respektive repo till en lokal mapp under `data/bsdata/<repo>` (enklast — ger versionshistorik gratis och är lätt att diffa/felsöka manuellt). Kör synken dels vid appstart, dels som ett dagligt bakgrundsjobb (samma mönster som BrickRadars schemalagda scraper-tråd i `app.py`), plus en manuell trigger: `POST /api/sync` för att köra om på begäran.

**Parsing:** Filerna är XML. Varje repo har en `.gst` (game system-fil, definierar globala kategorier/roller) och en eller flera `.cat`-filer (en per fraktion/katalog). Leta efter `selectionEntries`/`sharedSelectionEntries` av typen `unit` (inte `upgrade`/`model` som är underenheter) och läs ut:
- namn
- `categoryLinks` → roll (Battleline/Elite/Character/etc — primär kategori)
- kostnad: `costs`-elementet ger grundpoäng, men flera datasheets har poäng som varierar med antal modeller via `constraints` (min/max på en `selectionEntryGroup`) snarare än en enkel tabell. **Flagga detta som den svåraste delen** — börja med en enkel heuristik (grundkostnad × försök hitta min/max-constraints för att bygga en `{count, points}`-lista), verifiera manuellt mot ett par kända enheter (t.ex. Intercessor Squad ska ge 5=100p enligt mockup-seedet), och notera i `CLAUDE.md` vilka edge-cases som inte hanteras korrekt än.
- nyckelord: `<categoryLink>`- och `<profile>`-element med taggar/keywords

Spara rå-XML-referensen (filnamn + entry-id) per `entries`-rad så felsökning senare är möjlig utan att gissa.

### 4. Sök-API

- `GET /api/entries/search?system=<40k|kill_team|aos>&q=<text>` — söker på `entries.name` (och gärna `catalogues.name`) inom valt spelsystem, returnerar `{id, name, catalogue_name, role, keywords, points_table}` för varje träff. Detta är endpointen Fas 2:s sökruta/autocomplete kommer använda.
- `GET /api/entries/<id>` — detaljvy för en enskild BSData-post.

### 5. CRUD för `collection_units`

Spegla BrickRadar-mönstret i `api.py` (Blueprint under `/api`, JSON-fel som `{"error": "..."}` med rätt statuskod, aldrig HTML-felsidor):
- `GET /api/units` — lista, med filter på spelsystem/fraktion/status (motsvarar mockupens filter/sök/sortering)
- `POST /api/units` — skapa (kräver `entry_id` eller `name_override`, samt `count`)
- `PUT /api/units/<id>` — redigera (antal, status, foto, ev. byta länkad `entry_id`)
- `DELETE /api/units/<id>`

Ingen `X-API-Key`-auth behövs här (till skillnad från BrickRadars mobilapps-API) — WarAsset har ingen separat mobilapp och ska vara helt öppet på hemnätverket enligt beslut.

### 6. Docker / Unraid-drift

- `Dockerfile`: samma bas som BrickRadar (`python:3.14-slim`, `pip install -r requirements.txt`, `CMD ["python", "app.py"]`). Notera att `git` måste finnas i imagen (`apt-get install -y git`) eftersom synktjänsten klonar BSData-repos.
- `docker-compose.yml`:
  ```yaml
  services:
    warasset:
      build: .
      ports:
        - "5001:5001"
      volumes:
        - warasset_data:/app/data
      env_file:
        - .env
      restart: unless-stopped

  volumes:
    warasset_data:
  ```
  (Port 5001 vald för att inte krocka med BrickRadar som kör 5000 på samma Unraid-server.)
- Se till att Flask lyssnar på `host="0.0.0.0", port=5001` så den nås från andra enheter på nätverket.
- Deploy-flöde (samma som BrickRadar): lokalt `git add -A && git commit -m "..." && git push`, sedan på servern `ssh unraid "cd /mnt/user/appdata/warasset/app && git pull && docker compose -p warasset up -d --build"`. Använd alltid `-p warasset` explicit. Verifiera med `curl http://192.168.1.142:5001/` (eller motsvarande lokala IP) efter deploy.

## Verifiering

1. `docker compose up --build` startar lokalt utan fel.
2. Synktjänsten klonar alla tre BSData-repos första gången och fyller `game_systems`/`catalogues`/`entries` — kontrollera radantal per spelsystem (rimligt: hundratals catalogue-entries per system).
3. `GET /api/entries/search?system=40k&q=plague` returnerar minst "Plague Marines" med korrekt fraktion (Death Guard) och en poängtabell.
4. Manuellt stickprov: jämför 3–5 kända enheters poäng mot officiella/kända värden (t.ex. mockupens seed-data: Intercessor Squad 5 st = 100p) för att bekräfta att parsingen av poäng-constraints fungerar.
5. `POST /api/units` med en `entry_id` skapar en rad, `GET /api/units` listar den med rätt beräknade poäng utifrån `count`.
6. `POST /api/sync` kör om synken utan att döda befintliga `collection_units`-rader (dvs. synken får uppdatera `entries`, aldrig röra användarens egen data).
7. Deploy till Unraid enligt flödet ovan, verifiera live på port 5001.

## Avslutning

- Skriv `CLAUDE.md` med: databasschema, vilka BSData-repos som synkas och hur ofta, kända begränsningar i poäng-parsingen, och Unraid-deploy-detaljerna (sökväg, compose-projektnamn, port).
- Uppdatera `TODO.md` med öppna punkter, särskilt eventuella datasheets/edge-cases där poängparsingen inte gav korrekt resultat.
- Flagga tydligt i `CLAUDE.md` att Fas 2 (UI, baserat på `Miniatyrarkiv.dc.html`/Nocturne-designsystemet i `C:\WarAsset`) inte är påbörjad än.
