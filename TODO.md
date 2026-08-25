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
  se CLAUDE.md). Skulle kunna filtreras bort i Fas 2:s UI om det stör.

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

## Fas 2 — INTE påbörjad

UI baserat på `Miniatyrarkiv.dc.html` + Nocturne-designsystemet. Se
"Fas 2"-avsnittet i CLAUDE.md för vad som behöver göras (ersätta
`localStorage`-seed med sökning mot `/api/entries/search` och CRUD mot
`/api/units`, samt lösa spelsystem-nyckelskillnaden `'kt'` vs `'kill_team'`).

## Deploy — KLART (Fas 1b, 2026-08-25)

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

**Fas 1 (backend + BSData-synk + API + deploy) är nu helt klar.** Nästa
steg är Fas 2 (UI), se ovan.
