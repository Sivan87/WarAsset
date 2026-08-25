# Kickoff: WarAsset – Fas 1b: GitHub-koppling + Deploy till Unraid

## Bakgrund

Fas 1 (grunddatabas + BSData-synk) är klar och verifierad mot skarp data lokalt. Sivan har redan skapat det tomma GitHub-repot `warasset` och har `gh`-CLI inloggat. Till skillnad från BrickRadar-mönstret (där repo-koppling+deploy delvis var manuella steg) ska Claude Code sköta hela den här fasen själv: koppla lokalt repo mot GitHub, pusha, och driftsätta på Unraid via det redan konfigurerade SSH-aliaset `ssh unraid` — inga manuella steg åt Sivan i den här fasen.

## Uppgifter

### 1. Förhandskontroll innan något pushas

- `git status` — bekräfta vad som är ospårat/ändrat.
- Kontrollera att `.env` (och ev. andra hemligheter) verkligen ligger i `.gitignore` och INTE är stagat. Om `.env` av misstag redan är trackad: ta bort den från git-historiken innan första pushen (inte bara lägga till i `.gitignore` nu), så den aldrig hamnar på GitHub.
- Kontrollera att `data/`-mappen (databas, ev. cache) också är gitignorad — den ska inte committas, den hör hemma i Docker-volymen på servern.

### 2. Koppla lokalt repo mot GitHub (via `gh`)

Repot heter `warasset` och är redan skapat på Sivans GitHub-konto. Använd `gh`-CLI för att slippa gissa exakt URL:

```
gh repo view warasset --json sshUrl -q .sshUrl
```

Lägg till resultatet som remote och pusha:

```
git remote add origin <url-från-ovan>
git branch -M main
git add -A
git commit -m "Fas 1: grunddatabas + BSData-synk"
git push -u origin main
```

Verifiera att koden syns på GitHub efteråt, t.ex. `gh repo view warasset --web` eller `gh api repos/{owner}/warasset/commits -q '.[0].commit.message'`.

### 3. Deploy till Unraid via SSH

SSH-aliaset `unraid` finns redan konfigurerat (samma som används för BrickRadar, pekar mot `192.168.1.142` med rätt `IdentityFile`) — använd alltid `ssh unraid`, aldrig rå IP eller Tailscale-hostnamnet (Tailscale/MagicDNS går inte att slå upp från denna miljö).

Första gången (repot finns inte på servern än):

```
ssh unraid "mkdir -p /mnt/user/appdata/warasset && cd /mnt/user/appdata/warasset && git clone <url-från-steg-2> app"
```

Skapa `.env` på servern (samma innehåll som lokalt, eller nya produktionsvärden om relevant) — detta är den enda delen som kräver att en fil manuellt läggs på servern eftersom `.env` av design inte ligger i git:

```
ssh unraid "cat > /mnt/user/appdata/warasset/app/.env" <<'EOF'
<motsvarande nyckel=värde-rader som lokala .env>
EOF
```

Bygg och starta:

```
ssh unraid "cd /mnt/user/appdata/warasset/app && docker compose -p warasset up -d --build"
```

Vid framtida kodändringar (samma tvåstegsflöde som BrickRadar): lokalt `git push`, sedan:

```
ssh unraid "cd /mnt/user/appdata/warasset/app && git pull && docker compose -p warasset up -d --build"
```

Använd alltid `-p warasset` explicit i compose-kommandon — annars kan Compose falla tillbaka på mappnamnet som projektnamn och skapa en dubblettcontainer/portkonflikt.

### 4. Verifiera live

- `ssh unraid curl -s http://localhost:5001/` — svarar appen från servern själv.
- `curl http://192.168.1.142:5001/` (eller `curl http://192.168.1.142:5001/api/units`) från utvecklingsmaskinen — bekräftar att den nås över nätverket, inte bara `localhost` på servern.
- Kör en första manuell BSData-synk på servern om den inte redan triggats av appstarten: `curl -X POST http://192.168.1.142:5001/api/sync` och bekräfta att katalogräkningen matchar det Fas 1 redan verifierade lokalt (40k 6671/36, Kill Team 1028/111, AoS 3602/97) — annars tyder det på att servern inte har nätverksåtkomst till GitHub eller att `git` saknas i containern.
- Bekräfta att containern överlever en omstart: `ssh unraid docker restart warasset-warasset-1` (kontrollera exakt containernamn med `docker ps` — mönstret är `<projekt>-<tjänst>-<instansnummer>`), vänta, kör om `/api/units`.

## Verifiering

- [ ] `.env` och `data/` finns INTE i git-historiken på GitHub
- [ ] `main` på GitHub innehåller all Fas 1-kod
- [ ] Containern kör på Unraid, port 5001, `docker ps` visar `warasset-warasset-1` som "healthy"/running
- [ ] Nås både lokalt på servern (`localhost:5001`) och över nätverket (`192.168.1.142:5001`)
- [ ] BSData-synk på servern ger samma radantal som den lokala verifieringen
- [ ] Containern startar om rent efter `docker restart` och efter en omstart av själva Unraid-datorn (om det går att testa utan att störa annan drift)

## Avslutning

- Uppdatera `CLAUDE.md` med ett "Unraid-server"-avsnitt i samma stil som BrickRadars (SSH-alias, app-sökväg, compose-projektnamn, deploy-flöde) så framtida Claude Code-sessioner slipper leta upp det på nytt.
- Markera i `TODO.md` att Fas 1 (inklusive deploy) är helt klar, och att Fas 2 (UI) är nästa steg.
