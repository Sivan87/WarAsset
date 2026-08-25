# Kickoff: WarAsset – Fas 2: UI (kopplar Nocturne-mockupen mot Fas 1:s API)

## Bakgrund

Fas 1 är klar och driftsatt på Unraid (port 5001): databas, BSData-synk (40k/Kill Team/AoS) och ett REST-API (`/api/entries/search`, `/api/entries/<id>`, `/api/units` CRUD, `/api/sync`). Den här fasen bygger den faktiska webb-UI:n i Flask/`app.py` + `templates/` + `static/`, och kopplar den mot det API:t.

Det finns redan en fristående HTML-mockup att utgå från: `C:\WarAsset\Miniatyrarkiv.dc.html`, byggd mot Nocturne-designsystemet (samma mapp, se `readme.md`/`styles.css` där). Mockupen är byggd i ett eget "design canvas"-format (`x-dc`/`sc-for`/`sc-if`-taggar, en inbäddad JS-komponentklass) — den är INTE körbar Flask/Jinja-kod rakt av, utan ett visuellt facit för layout, komponenter, interaktioner och Nocturne-styling som ska återskapas som riktiga Jinja-templates + vanlig JS (fetch mot `/api/...`), inte kopieras rad för rad. Länka Nocturne-designsystemets `styles.css` och följ dess tokens/klasser (`.btn`, `.card`, `.tag`, `.field`/`.input`, `.table`, `.dialog-backdrop`+`.dialog`, `.lighten` för bilder osv. — se `readme.md` för fullständig lista) istället för att hårdkoda nya färger/mått.

**Skillnaden mot mockupen som måste implementeras (produktbeslut 2026-08-25):** i mockupen är "Namn", "Fraktion/armé" och poäng fria textfält. I den riktiga appen ska "Namn"-fältet i Lägg till/Redigera-dialogen vara en **sökruta mot `/api/entries/search`** (debouncad, filtrerad på valt spelsystem), där man väljer en träff ur en dropdown/lista. När en träff väljs: fyll automatiskt i fraktion, roll och poäng (skrivskyddade fält i UI:t, inte editerbara textfält) baserat på den valda `entry`:n och det ifyllda antalet. Poängen ska räknas om live när användaren ändrar "Antal modeller", genom att slå upp rätt brytpunkt i `entry.points_table`. Behåll `entry_id: null`-vägen som en medveten "Anpassad enhet"-växel/länk längst ner i dialogen (litet, inte förstahandsval) för scratch-builds/konverteringar som saknas i BSData — då blir namn/fraktion/poäng fria fält igen, precis som mockupen redan gör.

**Namngivning att lösa:** mockupen använder filternyckeln `kt` för Kill Team, backend/databasen använder `kill_team`. Lös genom att UI:t (JS-konstanterna för filter/systemval) använder samma nycklar som backend (`kill_team`, `40k`/`aos` — bekräfta exakt stavning mot `game_systems.key` i databasen innan ni hårdkodar), inte tvärtom.

## Uppgifter

### 1. Kartlägg mockupen och Fas 1:s API innan ni skriver kod

- Läs `C:\WarAsset\Miniatyrarkiv.dc.html` i sin helhet — notera varje vy/state (galleri/lista-vy, sök, filter per spelsystem, filter per roll, sortering, grupp-collapse per fraktion, statuskedja ej byggd/byggd/målad, add/edit-dialogen, stat-band-siffrorna).
- Läs `C:\WarAsset\readme.md` (Nocturne-designsystemet) för klasser/tokens.
- Läs Fas 1:s `api.py`/`CLAUDE.md` i warasset-repot för exakta fält-/JSON-format på `/api/entries/search`, `/api/units` osv. — bygg mot det som faktiskt implementerades, inte mot kickoff-dokumentets ursprungsförslag om de skiljer sig åt.

### 2. Sidstruktur i Flask

- `templates/index.html` (eller `base.html` + `index.html`) — huvudvyn: nav, sökfält, filter (spelsystem/roll), stat-band, grupperad enhetslista i galleri/lista-vy, add/edit-dialog. Server-renderad grundstruktur är okej, men interaktivitet (sök, filter, sortering, dialogen) sköts med vanlig JS mot API:t (samma mönster som BrickRadars `templates/` + inline/`static/`-JS, ingen ny frontend-ramverk behövs).
- `static/` — CSS (länka/kopiera in Nocturne `styles.css`, justera relativ sökväg) och en JS-fil för sidans logik.
- Foto-uppladdning: lagra i `data/uploads/` (samma volymmönster som databasen — persisteras via `warasset_data`-volymen), servera via en egen route eller Flasks statiska filhantering, spara filsökvägen i `collection_units.photo_path`. Ersätt mockupens "FOTO: {namn}"-platshållare med en riktig `<img>` när `photo_path` finns, annars behåll platshållarrutan.

### 3. Sök/autocomplete i add/edit-dialogen

- Textinput → debounce (~250ms) → `GET /api/entries/search?system=<valt>&q=<text>` → rendera resultatlista under fältet (namn + fraktion + roll).
- Val av en rad: lås namn/fraktion/roll till den valda entryn, visa poäng beräknat från `points_table` + aktuellt "Antal"-värde, spara `entry_id` i draften.
- Ändras "Antal modeller" efteråt: räkna om poängen mot samma `points_table` (klientsidan, ingen ny API-anrop behövs om `points_table` redan hämtades med sökträffen — annars hämta full detalj via `GET /api/entries/<id>` vid val).
- "Anpassad enhet"-läge (litet växelval): frigör namn/fraktion/poäng som fria fält igen, `entry_id` sätts till null vid spar.

### 4. Koppla resten av vyn mot API:t

- Sidladdning: `GET /api/units` (med ev. server- eller klientside-filter) → gruppera per fraktion i JS precis som mockupens `renderVals()`-logik redan gör, men läs riktig data istället för `SEED`.
- Spara/redigera/ta bort: `POST`/`PUT`/`DELETE /api/units/...` istället för `localStorage`. Ta bort `localStorage`-koden helt (`loadUnits`/`persist` i mockupen) — databasen är nu källan till sanning.
- Stat-bandet (Enheter/Modeller/Poäng totalt/Målade %) beräknas från samma `/api/units`-svar, samma formler som mockupens `renderVals()`.
- "Sync BSData nu"-knapp (ny, fanns inte i mockupen): en liten knapp/länk, gärna i nav eller inställningsvyn, som anropar `POST /api/sync` och visar status (kör/klar/fel) — nyttig eftersom det annars inte finns någon UI-väg att trigga en synk manuellt.

### 5. Följ Nocturne-designsystemets regler

- Ingen hårdkodad hex/font/px — allt via `styles.css`s variabler och befintliga klasser.
- Outline-knappar (inte solid-fyllda), `:focus-visible`-ring i accentfärg, hover/pressed-tillstånd från accent-rampen — inte webbläsarens default.
- Bilder genom `.lighten`-wrappern.

## Verifiering

1. Öppna appen i webbläsaren (lokalt och/eller mot Unraid-instansen på port 5001) — sidan laddar riktig data från databasen, inte seed-data.
2. Sök "Plague Marines" i add-dialogen med spelsystem 40k valt → korrekt träff (Death Guard) visas, val fyller i fraktion/roll/poäng automatiskt.
3. Ändra antal modeller till 6 och 8 för en Plague Marines-post → poängen uppdateras till 130 respektive 190 (det redan verifierade testfallet från Fas 1).
4. Skapa, redigera och ta bort en enhet via UI:t → verifiera via `GET /api/units` (curl) att ändringen faktiskt ligger i databasen, inte bara i webbläsarens minne.
5. Testa filter per spelsystem med korrekt `kill_team`-nyckel (inte `kt`) — Kill Team-enheter visas/döljs korrekt.
6. Ladda upp ett foto på en enhet, ladda om sidan → fotot visas fortfarande (persisterat, inte bara i sessionen).
7. "Anpassad enhet"-läget fungerar (fria fält, `entry_id` null) och visas korrekt i listan/gruppen (grupperas rimligt, t.ex. under en "Övrigt"/anpassad-rubrik om ingen fraktion är känd).
8. Kör igenom hela flödet på faktisk Unraid-drift (`http://192.168.1.142:5001`), inte bara lokalt.

## Avslutning

- Uppdatera `CLAUDE.md`/`TODO.md`: vilken del av mockupen som är 1:1 återskapad kontra medvetet ändrad (sök-först-flödet, `kt`→`kill_team`-fixen, ny sync-knapp), samt eventuella kvarstående skillnader mot originaldesignen.
- Deploya till Unraid enligt samma flöde som Fas 1b (`git push` → `ssh unraid "cd /mnt/user/appdata/warasset/app && git pull && docker compose -p warasset up -d --build"`), verifiera live.
