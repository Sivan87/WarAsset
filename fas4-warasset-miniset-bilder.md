# Kickoff: WarAsset – Fas 4: Referensbilder från miniset.net

## Bakgrund

WarAsset saknar idag en bildkälla för enheter — bara platshållare tills användaren laddar upp ett eget foto efter att en enhet sparats. Sivan vill ha en referensbild (produktfoto) innan/tills ett eget foto finns.

**Källa: [miniset.net](https://miniset.net/)** — en fan-driven, icke-kommersiell "collectors guide" för miniatyrer, strukturerad per tillverkare → spellinje → (fraktion) → produktsats, med flera produktfoton per sats. Exempel: `https://miniset.net/sets/gw-99120102128` (Plague Marines).

**Juridiskt/etiskt läge, viktigt att respektera i implementationen:**
- Bilderna är fortfarande Games Workshops upphovsrättsskyddade produktfoton — miniset.net äger dem inte, de visar dem bara ("All names, trademarks and images are copyright their respective owners").
- Till skillnad från wh40k.lexicanum.com (som uttryckligen förbjuder automatiserad åtkomst i sina användarvillkor) har miniset.net **ingen sådan uttrycklig förbudsklausul**, och deras `robots.txt` blockerar bara systemsökvägar (`/admin/`, `/user/login/` osv.) — men sätter en **10 sekunders crawl-delay**, vilket ska respekteras strikt i koden (inte bara som en artighet, som en hård minimigräns mellan varje request mot sajten).
- **Ladda ALDRIG ner och lagra en permanent kopia av själva bildfilen** på servern/i Docker-volymen — spara bara bildens URL (`image_url`) och käll-sidans URL (`image_source_url`) i databasen, och låt webbläsaren hämta bilden direkt från miniset.net (hotlink) när sidan visas. Det minskar upphovsrättsexponeringen jämfört med att rehosta bilder, och är den enda formen av "cachning" som är okej här (att spara URL:en, inte filen).
- **Skala ner omfattningen medvetet:** hela BSData-katalogen är ~11 300 entries (40k+Kill Team+AoS). Vid 10 sek/request skulle en bulk-matchning mot HELA katalogen ta över 30 timmar och slå mot sidor ingen någonsin kommer registrera. Matcha därför **bara mot enheter Sivan faktiskt lägger till i sin egen samling** (`collection_units`), inte mot hela BSData-katalogen — se uppgift 2.

## Uppgifter

### 1. Utforska miniset.net:s faktiska sidstruktur innan ni skriver matchningslogik

Gissa inte URL-mönstret för fraktionsnivån — hämta och inspektera live:
- `https://miniset.net/sets/games-workshop` (game-line-lista, bekräftad struktur: `/sets/games-workshop/warhammer-40k`, `/sets/games-workshop/kill-team`, `/sets/games-workshop/warhammer-age-of-sigmar`)
- Gå ett steg till: hämta t.ex. `https://miniset.net/sets/games-workshop/warhammer-40k` och se hur fraktioner/produkter listas därifrån (URL-mönster, om produktnamn/bild-thumbnails finns direkt på listsidan eller kräver ett klick till varje produktsida).
- Notera exakt HTML-struktur för en produktsida (som `gw-99120102128`) — vilken bild som är "huvudbilden" (första i galleriet, eller en markerad "primär"-bild) att använda som `image_url`.

### 2. Datamodell och matchningsflöde — per samlings-enhet, inte per BSData-katalog

- Lägg till `image_url` (nullable) och `image_source_url` (nullable) på `collection_units` (INTE på `entries` — se skäl ovan om omfattning).
- Matchningen triggas **on-demand**, inte som en bakgrundssynk över hela katalogen:
  - Automatiskt när en enhet sparas/länkas mot en BSData-entry (om `image_url` saknas) — kör matchningen asynkront (inte blockera spara-anropet), eller
  - Via en explicit "Hämta bild"-knapp per enhet i UI:t om automatiskt-vid-spara känns för långsamt/opålitligt (design-beslut ni kan ta i implementationen; 10 sek fördröjning gör att en synkron väntan i UI:t inte fungerar bra).
- Matchningslogik: fuzzy-matcha entryns namn (t.ex. "Plague Marines") + fraktionsnamn (t.ex. "Death Guard") mot produktnamnen under rätt game-line-gren på miniset.net (`warhammer-40k` för `40k`, `kill-team` för `kill_team`, `warhammer-age-of-sigmar` för `aos` — samma `kill_team`-nyckel som redan beslutades i Fas 2, inte `kt`). Sätt en rimlig träffsäkerhetströskel (t.ex. ett fuzzy-matchningsbibliotek som `rapidfuzz` i Python) — under tröskeln: ingen träff, `image_url` förblir null, UI faller tillbaka på platshållare.
- **Rate limiting:** en enda global "senast anropad miniset.net"-tidsstämpel i minnet/databasen, och varje ny request väntar tills minst 10 sekunder passerat sedan förra — oavsett hur många enheter som köar för matchning samtidigt (en enkel kö/lås, inte parallella anrop mot sajten).
- Cacha resultatet (positivt ELLER negativt — dvs. "ingen träff hittades") i databasen så samma enhet inte matchas om vid varje sidladdning; ge en enkel "matcha om"/"hämta bild"-knapp för manuell omkörning om Sivan vill försöka igen eller om en felaktig träff behöver bytas ut.

### 3. API

- `POST /api/units/<id>/fetch-image` — triggar matchningen för en specifik enhet (respekterar rate-limit-kön), returnerar `{image_url, image_source_url}` eller `{matched: false}`.
- `DELETE /api/units/<id>/image` (eller motsvarande) — låter Sivan rensa en felaktig automatisk matchning (utan att röra ett ev. eget uppladdat foto — de är separata fält).
- Utöka `GET /api/units`/`GET /api/units/<id>` att inkludera `image_url`/`image_source_url` i svaret.

### 4. UI

- På enhetskortet: visa i prioritetsordning — (1) användarens eget uppladdade foto (`photo_path`) om det finns, annars (2) `image_url` från miniset.net (genom Nocturnes `.lighten`-wrapper, samma som ett riktigt foto skulle använda) med en diskret källhänvisning ("Bild: miniset.net", länkad till `image_source_url`), annars (3) den befintliga "FOTO: {namn}"-platshållaren.
- En liten "Hämta/matcha om bild"-knapp/länk på kortet eller i redigeringsdialogen, som anropar `/fetch-image` och visar ett laddningsläge (kan ta flera sekunder pga rate-limiten — gör tydligt i UI:t att det inte är trasigt, bara långsamt med flit).
- Ingen bulk-knapp för "hämta bilder för alla enheter" i den här fasen — risk att någon råkar trigga en lång kö av seriella 10-sekundersanrop utan att förstå varför det tar timmar. Om det efterfrågas senare: separat beslut.

## Verifiering

1. Lägg till en enhet ("Plague Marines", Death Guard) → trigga bildhämtning → korrekt produktbild från miniset.net visas, med källänk.
2. Lägg till en enhet med osäkert/obefintligt namn (eller en anpassad enhet) → ingen falsk träff tvingas fram, platshållare visas istället.
3. Mät faktisk tid mellan två på varandra följande anrop mot miniset.net i loggarna → bekräfta ≥10 sekunder, även om flera bildhämtningar triggas nära varandra i UI:t.
4. Radera en automatisk bildmatchning → platshållare (eller ev. eget foto om det redan fanns) visas igen, inget kvarvarande trasigt tillstånd.
5. Ladda upp ett eget foto på en enhet som redan har en miniset.net-bild → det egna fotot tar över, `image_url` påverkas inte (separata fält, tydlig prioritetsordning).
6. Testa i riktig webbläsare (samma Playwright-upplägg som tidigare faser).
7. Deploya till Unraid enligt samma flöde som tidigare faser, verifiera live.

## Avslutning

- Dokumentera i `CLAUDE.md`: exakt URL-struktur som upptäcktes på miniset.net, matchningströskeln som valdes och varför, samt rate-limit-implementationen.
- Flagga i `TODO.md` eventuella fraktioner/enheter där matchningen ofta missar (så det går att förbättra heuristiken senare), och notera uttryckligen att detta är en "best effort, on-demand"-lösning — inte en garanterad bildkälla för hela samlingen.
