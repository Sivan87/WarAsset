# Kickoff: WarAsset – Fas 3: Stats-ruta vid klick på enhetsnamn

## Bakgrund

I dagens UI visar en enhetskort/rad bara namn, fraktion, antal och poäng. Sivan vill kunna klicka på själva namnet på en enhet och få upp en ruta med full statistik för den — karaktäristik (t.ex. Rörelse/Tålighet/Rustningsvärde/Sår/Ledarskap/OC för 40k, motsvarande för Kill Team/AoS), vapenprofiler och ev. förmågor/nyckelord. All den datan finns i BSData-repona, men **fångas inte av Fas 1:s synk idag** — `bsdata_sync.py` parsar bara namn, roll, nyckelord och poängtabell (`points_table`), inte `<profile>`-elementen som innehåller de faktiska stat-blocken. Den här fasen bygger både datafångsten och UI-rutan.

Rutan ska öppnas vid klick på namnet, stängas vid klick utanför (standard popover-beteende, inte en tung modal med backdrop som add/edit-dialogen).

## Uppgifter

### 1. Utöka datamodellen och synken

- Lägg till en kolumn `entries.profiles` (JSON) — en lista av profiler, t.ex. `[{"type": "Unit", "characteristics": {"M": "6\"", "T": "4", "SV": "3+", "W": "2", "LD": "6+", "OC": "2"}}, {"type": "Wapen: Boltgevär", "characteristics": {"Räckvidd": "24\"", "A": "2", "BS": "3+", "S": "4", "AP": "0", "D": "1"}}]` — exakt fältnamn/struktur beror på vad BSData:s `<profile>`/`<characteristicTypes>`-element faktiskt innehåller per spelsystem (40k/Kill Team/AoS har olika karaktäristik-set), så låt strukturen vara generisk (profilnamn + typ + nyckel/värde-par) istället för hårdkodade kolumner à la `M`/`T`/`SV`.
- Uppdatera `bsdata_sync.py` att läsa `<profiles><profile>`-element (både på entryn direkt och via `<infoLinks>`/delade profiler, samma typ av indirektion som redan löstes för AoS-poäng på `entryLink` i Fas 1 — kolla om profiler har samma mönster) och spara som `profiles`-JSON på entryn.
- **Databasmigrering:** lägg till kolumnen på befintlig, redan driftsatt databas utan att tappa `collection_units`-data (`ALTER TABLE entries ADD COLUMN profiles ...`, kör som en enkel migrering vid appstart om kolumnen saknas — samma försiktighetsprincip som redan gäller för synken: den får bara röra `entries`/`catalogues`, aldrig användarens egna rader).
- Kör om en full synk (`POST /api/sync` eller motsvarande) efter migreringen så befintliga entries får `profiles` ifyllt.

### 2. API

- Utöka `GET /api/entries/<id>` (finns redan från Fas 1) med `profiles` i svaret, om det inte redan skickas med rakt av.
- Om `GET /api/units/<id>` idag inte returnerar den länkade entryns fulla data (bara `entry_id`): antingen utöka det svaret med en nästlad `entry`-detalj, eller låt UI:t göra ett andra anrop mot `/api/entries/<entry_id>` när stats-rutan öppnas — välj det som stämmer bäst med hur `app.js` redan är strukturerat, ingen anledning att duplicera data i varje `/api/units`-svar om det inte redan görs.

### 3. UI: popover vid klick på namn

- Gör enhetsnamnet (både i galleri- och listvyn) klickbart — visuellt en diskret hover-indikation (t.ex. understrykning eller accentfärg vid hover, enligt Nocturnes länk-stil `a{color:#9184d9}`), inte en knapp.
- Klick: hämta profildata (från steg 2) och rendera en popover **positionerad relativt det klickade namnet** (inte centrerad modal), med samma Nocturne-styling som `.card`/`.tag` (mörk grund, tunn kant, `--shadow-md`). Innehåll: enhetsnamn, fraktion/roll, respektive profil som en liten tabell (karaktäristik-namn → värde), vapenprofiler grupperade separat om flera finns.
- **Stäng vid klick utanför:** en `document`-nivå click-listener som stänger rutan om klicket landar utanför popover-elementet (samma mönster som add/edit-dialogens `stopClick`/backdrop-klick i mockupen, men utan full backdrop — bara en osynlig "klick utanför"-yta). Stäng även vid `Escape`-tangenten och vid klick på ett *annat* enhetsnamn (byt innehåll istället för att kräva två klick).
- **Anpassade enheter** (`entry_id: null`) har ingen BSData-koppling och därmed ingen profildata — namnet ska antingen inte vara klickbart för dessa, eller visa ett tydligt "Ingen BSData-koppling — anpassad enhet"-meddelande i rutan istället för tom/trasig data.
- Kom ihåg buggen från Fas 2 (Nocturnes `.dialog-backdrop{display:grid}` som slog ut `[hidden]`) — testa explicit att popovern verkligen är helt osynlig/icke-interaktiv i stängt läge, inte bara visuellt dold.

## Verifiering

1. Klicka på "Plague Marines" i en riktig enhetsrad → popover visar karaktäristik + vapenprofiler som matchar det som faktiskt står i BSData-katalogen för den enheten (stickprovskontrollera manuellt mot källfilen).
2. Klicka utanför rutan → den stängs. Klicka på ett annat enhetsnamn medan rutan är öppen → innehållet byts till den nya enheten utan att kräva en extra stängningsklick.
3. `Escape` stänger rutan.
4. En "anpassad enhet" (utan `entry_id`) hanteras utan krasch — antingen inte klickbar, eller tydligt meddelande.
5. Kör om `POST /api/sync` efter migreringen → bekräfta att `collection_units`-tabellen är orörd (samma test som redan finns från Fas 1) och att `entries.profiles` nu är ifyllt för ett stickprov av rader.
6. Testa i riktig webbläsare (samma Playwright-upplägg som Fas 2 om inget run-skill finns) — inte bara curl — eftersom Fas 2:s enda riktiga bugg hittades just genom att faktiskt klicka i UI:t.
7. Verifiera på faktisk Unraid-drift efter deploy.

## Avslutning

- Dokumentera i `CLAUDE.md` exakt hur `profiles`-JSON:en är strukturerad per spelsystem (40k/Kill Team/AoS kan skilja sig åt i vilka karaktäristiker som finns), och eventuella entries där profildata saknas/är ofullständig i själva BSData-källan.
- Deploya enligt samma flöde som tidigare faser, verifiera live.
