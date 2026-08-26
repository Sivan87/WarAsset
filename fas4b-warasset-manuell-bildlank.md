# Kickoff: WarAsset – Fas 4b: Manuell bildlänk från miniset.net

## Bakgrund

Fas 4:s automatiska matchning mot miniset.net fungerar, men har två typer av kända, svårlösta edge-cases som Sivan stött på i praktiken:

1. **Flera utgåvor av samma enhet** — t.ex. Plague Marines finns i flera "sculpts"/utgåvor på miniset.net, och den automatiska matchningen hittar ibland den äldsta modellen istället för den nuvarande.
2. **Hjältar sålda i multi-pack-set** — t.ex. Malignant Plaguecaster säljs inte som en egen box, utan som del av setet "Chosen of Mortarion" tillsammans med två andra hjältar. BSData ser tre separata enheter (regelmässigt), men miniset.net har bara en produktsida för hela setet — automatisk namnmatchning hittar inte det sambandet.

Det här är inte buggar i matchningslogiken att fixa — det är i grunden tvetydiga fall där bara en människa vet vilken bild som är "rätt". Lösningen är att lägga till en **manuell override**: i redigera-enhet-dialogen kan Sivan själv klistra in länken till rätt produktsida på miniset.net, så hämtar verktyget bilden därifrån istället för att förlita sig på automatisk matchning.

## Uppgifter

### 1. Datamodell

- Lägg till `collection_units.image_source` (t.ex. `'auto'` / `'manual'` / `null`) för att skilja på en automatiskt matchad bild och en manuellt länkad — så att en framtida automatisk om-matchning (eller en bakgrundsprocess senare) aldrig skriver över en bild Sivan medvetet valt själv.
- `image_url`/`image_source_url`/`image_checked_at` (från Fas 4) återanvänds som de är.

### 2. API

- `POST /api/units/<id>/image-from-url` — body `{"source_url": "https://miniset.net/sets/..."}`.
  - Validera att URL:en faktiskt pekar på `miniset.net` (och gärna specifikt ett `/sets/...`-mönster) — avvisa med tydligt felmeddelande annars. Detta är samma sajt hela rate-limit-/hotlink-resonemanget från Fas 4 gäller för, så samma regler ska följas här: gå igenom samma globala 10-sekunders rate-limit-lås som `miniset_client.py` redan implementerar (återanvänd den funktionen, duplicera inte låslogiken).
  - Hämta sidan, extrahera samma "huvudbild" som den automatiska matchningen redan vet hur man plockar ut (återanvänd den bildextraktionslogiken från Fas 4 istället för att skriva en ny parser).
  - Spara `image_url`, `image_source_url` (= den inskickade länken) och `image_source = 'manual'`.
  - Om sidan inte går att hämta eller ingen bild hittas: tydligt JSON-fel, inte en tyst no-op.
- Automatisk om-matchning (`POST /api/units/<id>/fetch-image` från Fas 4) ska **inte** skriva över en `image_source = 'manual'`-bild av misstag — antingen vägra (kräv en explicit `?force=true`-flagga eller liknande för att medvetet ersätta en manuell länk), eller åtminstone tydligt kommunicera i UI:t att det kommer skriva över en manuellt vald bild innan det görs.

### 3. UI

- I redigera-enhet-dialogen: ett textfält "Länk till rätt bild (miniset.net)" + en liten "Hämta"-knapp bredvid, som anropar `/image-from-url`. Visa gärna en förhandsvisning av bilden i dialogen innan man sparar hela enheten, så Sivan ser att rätt bild hämtades innan den committas.
- På enhetskortet: om `image_source === 'manual'`, visa gärna en diskret markering (t.ex. en liten pin-ikon eller ändrad tooltip-text på bildkrediten) så det är tydligt att just den bilden är manuellt vald och inte kommer bytas ut av en framtida automatisk körning.
- Behåll de befintliga "Hämta/matcha om bild (auto)" och "Ta bort bild"-knapparna från Fas 4 — den manuella länken är ett alternativ, inte en ersättning av det automatiska flödet, eftersom automatisk matchning fortfarande är bekvämast för de enheter där den redan fungerar bra.

## Verifiering

1. Klistra in en miniset.net-produktlänk för en specifik (nyare) Plague Marines-utgåva → rätt bild hämtas och sparas, `image_source = 'manual'`.
2. Klicka "Hämta/matcha om bild (auto)" på samma enhet efteråt → antingen vägras det (utan `force`), eller ett tydligt varningssteg krävs — bilden byts inte ut i tysthet.
3. Klistra in en ogiltig/icke-miniset.net-länk → tydligt felmeddelande, inget krasch och ingen bild sparas.
4. Länka Malignant Plaguecaster mot "Chosen of Mortarion"-produktsidan → bilden visas korrekt på kortet trots att BSData-namnet inte matchar produktnamnet.
5. Verifiera att `image_source_url`-krediten på kortet fortfarande länkar till rätt sida och att attributionen ("Bild: miniset.net") är kvar oavsett om bilden kom automatiskt eller manuellt.
6. Testa i riktig webbläsare, deploya till Unraid enligt samma flöde som tidigare faser, verifiera live.

## Avslutning

- Dokumentera i `CLAUDE.md` att `image_source` nu styr om en bild är skyddad från automatisk om-matchning, och notera de två konkreta edge-case-exemplen (flera utgåvor, multi-hjälte-set) som motiverade funktionen.
