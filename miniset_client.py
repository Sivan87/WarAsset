"""
Klient mot miniset.net (https://miniset.net) för att hitta referensbilder
(produktfoton) till samlingsenheter — se fas4-warasset-miniset-bilder.md och
CLAUDE.md (Fas 4) för det fulla resonemanget.

Viktigt att komma ihåg vid ändringar:
- Bildfilerna lagras ALDRIG lokalt — bara image_url (hotlink) och
  image_source_url (käll-sidan) sparas i databasen, se database.py:s
  set_unit_image. Ladda aldrig ner och spara en kopia av själva bilden.
- miniset.nets robots.txt sätter "Crawl-delay: 10" för alla user agents.
  _rate_limited_get nedan garanterar >= MIN_REQUEST_INTERVAL_SECONDS mellan
  att FÖRRA anropets svar kom in och att NÄSTA anrop skickas, via ett enda
  globalt lås — oavsett hur många matchningar som triggas nära varandra i
  UI:t (bakgrundstriggern vid spara + den manuella "hämta bild"-knappen
  delar samma lås).
"""
import re
import threading
import time
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from rapidfuzz import fuzz

BASE_URL = "https://miniset.net"
USER_AGENT = "WarAsset/1.0 (privat icke-kommersiellt inventeringsverktyg; github.com/Sivan87/WarAsset)"
REQUEST_TIMEOUT_SECONDS = 20
MIN_REQUEST_INTERVAL_SECONDS = 10

# WarAssets egna game_system.key -> miniset.nets URL-slug för spellinjen.
# Bekräftat genom att hämta https://miniset.net/sets/games-workshop live
# under utvecklingen av Fas 4 (se CLAUDE.md) — gissa inte om detta ändras,
# hämta sidan på nytt och verifiera.
GAME_LINE_SLUGS = {
    "40k": "warhammer-40k",
    "kill_team": "kill-team",
    "aos": "warhammer-age-of-sigmar",
}

# Träffsäkerhetströskel för rapidfuzz.fuzz.WRatio (0-100). Valt genom
# stickprov mot riktiga miniset-produktnamn (se CLAUDE.md, Fas 4): en äkta
# näraträff som "Intercessor Squad" (BSData) mot "Intercessors" (miniset)
# hamnar strax under 76, medan obesläktade produkter (t.ex. "Plague Marines"
# mot "Death Guard Battleforce: Vile Vectorium") hamnar under 40 — 75
# skiljer de två robust utan att vara så högt att normala namnvarianter
# (singular/plural, "Squad"-suffix) faller bort.
MATCH_THRESHOLD = 75

# 40k-fraktionssidor på miniset har (för de flesta fraktioner) en uppsättning
# äldre force-org-liknande underkategorier (troops/elites/hq/vehicles/...)
# som gör att en fraktion på hundratals produkter kan sökas igenom med EN
# riktad request istället för att paginera igenom alla — verifierat live
# (Death Guards "infantry"-underkategori gav 2 produkter, varav "Plague
# Marines", mot 151 osorterade produkter på huvudfraktionssidan). Mappningen
# är en approximation (BSData:s 10e-roller matchar inte exakt miniset:s
# äldre kategorier) — se TODO.md för kända luckor.
# Kill Team och AoS saknar motsvarande underkategorier på miniset
# (verifierat live: både en Kill Team- och en AoS-fraktionssida gav bara
# "/none/" som underkategori) — där görs istället bara ett anrop mot
# fraktionslistans FÖRSTA sida, en medveten, dokumenterad begränsning.
_ROLE_CATEGORY_HINTS = [
    (re.compile(r"battleline|troop", re.I), ("troops", "infantry")),
    (re.compile(r"transport", re.I), ("dedicated-transport", "vehicles")),
    (re.compile(r"heavy support", re.I), ("heavy-support",)),
    (re.compile(r"fast attack", re.I), ("fast-attack",)),
    (re.compile(r"elite", re.I), ("elites",)),
    (re.compile(r"character|hero|leader|^hq$", re.I), ("hq", "characters")),
    (re.compile(r"vehicle|mounted", re.I), ("vehicles",)),
    (re.compile(r"monster|beast", re.I), ("monstrous-creatures",)),
]

# Totalt antal miniset.net-requests EN ENDA matchning max får göra. Håller
# värsta-fall-latensen nere (vid 10 sek/request blir taket ~30 sekunder,
# "flera sekunder" enligt kickoff-dokumentet — inte minuter av paginering
# genom en fraktion på hundratals produkter).
_MAX_REQUESTS_PER_MATCH = 3

_rate_lock = threading.Lock()
_last_request_finished_at = 0.0


def _rate_limited_get(url):
    """Se modulens docstring om rate-limit-garantin. Uppdaterar tidsstämpeln
    EFTER att svaret (eller felet) kommit in, inte innan anropet skickas —
    en strängare tolkning av "10 sekunders crawl-delay" som håller kravet
    även om ett enskilt anrop mot miniset.net skulle vara ovanligt långsamt."""
    global _last_request_finished_at
    with _rate_lock:
        wait = MIN_REQUEST_INTERVAL_SECONDS - (time.monotonic() - _last_request_finished_at)
        if wait > 0:
            time.sleep(wait)
        try:
            return requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT_SECONDS)
        finally:
            _last_request_finished_at = time.monotonic()


def _slugify(text):
    text = (text or "").lower().replace("'", "").replace("’", "")
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


# Kända namnskillnader mellan BSData:s katalognamn och miniset.nets
# fraktionsslugs, upptäckta under testning mot den riktiga databasen (se
# CLAUDE.md, Fas 4) — t.ex. Kill Teams BSData-katalog heter "Asuryani" men
# miniset.net använder "aeldari" (40k:s egen katalog heter redan "Aeldari",
# så mismatchen är Kill Team-specifik). INTE en uttömmande lista över alla
# namnskillnader — se TODO.md för fraktioner där matchningen ändå missar.
_FACTION_SLUG_ALIASES = {
    "asuryani": "aeldari",
}


def _faction_slug(system_key, catalogue_name):
    """catalogues.name är INTE bara fraktionsnamnet rakt av — formen skiljer
    sig mellan spelsystemen (verifierat mot den riktiga databasen under
    utvecklingen av Fas 4, se CLAUDE.md):

    - 40k: alltid "<Grand Alliance> - [<kapitel-/underfraktion> - ]<Fraktion>"
      (t.ex. "Chaos - Death Guard", "Imperium - Adeptus Astartes - Space
      Marines") — den faktiska armén miniset.net känner till är alltid
      SISTA segmentet.
    - aos: "<Fraktion>[ - <underlista/warband>]" (t.ex. "Cities of Sigmar -
      The Iron March") — här är det istället FÖRSTA segmentet som är
      fraktionen, omvänt mot 40k.
    - kill_team: catalogues.name ÄR redan bara fraktionsnamnet, ingen
      uppdelning behövs.

    "[LEGENDS]"-liknande bracket-taggar (AoS) hör inte till fraktionsnamnet
    och tas bort innan uppdelningen."""
    name = re.sub(r"\[[^\]]*\]", "", catalogue_name or "").strip()
    parts = [p.strip() for p in name.split(" - ") if p.strip()]
    if not parts:
        return ""
    faction = parts[-1] if system_key == "40k" else parts[0]
    slug = _slugify(faction)
    return _FACTION_SLUG_ALIASES.get(slug, slug)


def _category_candidates_for_role(system_key, role):
    if system_key != "40k" or not role:
        return []
    candidates = []
    for pattern, slugs in _ROLE_CATEGORY_HINTS:
        if pattern.search(role):
            for slug in slugs:
                if slug not in candidates:
                    candidates.append(slug)
    return candidates


def _colorbox_image_url(scope):
    """Bryter ut originalbildens URL ur en <a class="colorbox"> — en delad
    primitiv mellan listningssidans per-produkt-parsing
    (_parse_category_page) och en enskild, manuellt länkad produktsidas
    bildextraktion (fetch_product_image, Fas 4b). BÅDA sidtyperna använder
    samma colorbox-markup för originalbilden (samma fil som t.ex.
    .../set/gw-99810102007-0.jpg), verifierat live under utvecklingen —
    men en produktsida saknar listningssidans div.set-<id>/gallery_title-
    wrapper, så bara den HÄR extraktionsbiten (inte hela sidparsern) går
    att återanvända rakt av mellan de två fallen."""
    img_a = scope.select_one("a.colorbox")
    return img_a.get("href") if img_a else None


def _parse_category_page(html):
    """Bryter ut (namn, produkt-url, bild-url) för varje produkt på en
    kategori-/fraktionslistningssida. DOM-strukturen verifierades live under
    utvecklingen (se CLAUDE.md, Fas 4): varje produkt ligger i en
    <div class="set-<nod-id>">, med produktnamn+länk i ett nästlat
    div.gallery_title och originalbilden i en nästlad a.colorbox (se
    _colorbox_image_url)."""
    soup = BeautifulSoup(html, "html.parser")
    entries = []
    for block in soup.find_all("div", class_=re.compile(r"^set-\d+$")):
        title_a = block.select_one("div.gallery_title a")
        image_url = _colorbox_image_url(block)
        if not title_a or not image_url:
            continue
        href = title_a.get("href")
        name = title_a.get_text(strip=True)
        if not href or not name:
            continue
        entries.append({
            "name": name,
            "product_url": BASE_URL + href if href.startswith("/") else href,
            "image_url": image_url,
        })
    return entries


def _fetch_category(game_line_slug, faction_slug, category_slug=None, page=1):
    path = f"/sets/games-workshop/{game_line_slug}/{faction_slug}"
    if category_slug:
        path += f"/{category_slug}/"
    if page > 1:
        path += f"page-{page}" if category_slug else f"/page-{page}"
    try:
        resp = _rate_limited_get(BASE_URL + path)
    except requests.RequestException as e:
        print(f"[miniset_client] Nätverksfel mot {path}: {e}")
        return []
    if resp.status_code != 200:
        return []
    return _parse_category_page(resp.text)


# En manuell bildlänk (Fas 4b) accepteras i TVÅ former:
#   1. En produktsida, /sets/<produkt-id> — huvudbilden bryts ut ur sidan
#      (som tidigare).
#   2. En direkt bildfils-URL, /files/set/<produkt-id>-<n>.<ext> — t.ex.
#      https://miniset.net/files/set/gw-99120102114-3.jpg för att peka på
#      EN SPECIFIK bild i produktens galleri (inte bara "-0"-huvudbilden).
#      Redan den slutgiltiga bild-URL:en, så INGET nätverksanrop mot
#      miniset.net behövs för den varianten — bara formkontrollen nedan.
# Ingen annan sökväg accepteras, och ingen annan domän som råkar innehålla
# "miniset.net" i sökvägen eller som underdomän/suffix
# (urlparse().netloc jämförs exakt, inte med "in").
_PRODUCT_PATH_RE = re.compile(r"^/sets/[A-Za-z0-9_-]+/?$")
_FILE_PATH_RE = re.compile(r"^/files/set/([A-Za-z0-9_-]+)-\d+\.(jpe?g|png|gif|webp)$", re.I)


def _parsed_miniset_url(url):
    """urlparse:ar url och returnerar den bara om den pekar på miniset.net
    eller www.miniset.net, annars None — delad host-koll mellan
    is_miniset_product_url och _miniset_file_product_id."""
    try:
        parsed = urlparse((url or "").strip())
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https"):
        return None
    if parsed.netloc.lower() not in ("miniset.net", "www.miniset.net"):
        return None
    return parsed


def is_miniset_product_url(url):
    parsed = _parsed_miniset_url(url)
    return bool(parsed and _PRODUCT_PATH_RE.match(parsed.path))


def _miniset_file_product_id(url):
    """Om url är en direkt bildfils-länk (/files/set/<produkt-id>-<n>.ext),
    returnerar produkt-id:t (t.ex. "gw-99120102114") — annars None."""
    parsed = _parsed_miniset_url(url)
    if not parsed:
        return None
    m = _FILE_PATH_RE.match(parsed.path)
    return m.group(1) if m else None


def fetch_product_image(source_url):
    """Hämtar bilden för EN specifik, av Sivan manuellt vald
    miniset.net-länk (Fas 4b, se fas4b-warasset-manuell-bildlank.md — för
    edge-cases den automatiska matchningen i match_unit() inte kan lösa:
    flera "sculpts"/utgåvor av samma enhet, eller en hjälte som bara säljs
    som del av ett multi-hjälte-set), ELLER en specifik bild i en produkts
    galleri (en direkt bildfils-länk, se _miniset_file_product_id).

    En produktside-länk går igenom SAMMA globala rate-limit som
    match_unit() (_rate_limited_get) och återanvänder samma
    bildextraktions-primitiv (_colorbox_image_url) som listningssidorna,
    se den funktionens docstring för varför bara primitiven (inte hela
    sidparsern) återanvänds. En direkt bildfils-länk kräver INGET
    nätverksanrop — den ÄR redan den slutgiltiga bild-URL:en.

    Returnerar {"image_url": "...", "source_page_url": "..."} vid träff
    (source_page_url är produktsidan krediten ska länka till — härledd
    från filnamnets produkt-id om en direkt bildlänk gavs, annars länken
    själv), annars {"error": "..."} — ALDRIG en tyst no-op (kickoff-
    dokumentets krav)."""
    url = (source_url or "").strip()

    file_product_id = _miniset_file_product_id(url)
    if file_product_id:
        return {"image_url": url, "source_page_url": f"{BASE_URL}/sets/{file_product_id}"}

    if not is_miniset_product_url(url):
        return {"error": (
            "The link must point to a product page (e.g. "
            "https://miniset.net/sets/gw-99810102007) or an image file "
            "(e.g. https://miniset.net/files/set/gw-99810102007-0.jpg) on miniset.net"
        )}
    try:
        resp = _rate_limited_get(url)
    except requests.RequestException as e:
        return {"error": f"Could not reach miniset.net: {e}"}
    if resp.status_code != 200:
        return {"error": f"miniset.net responded with status code {resp.status_code}"}
    image_url = _colorbox_image_url(BeautifulSoup(resp.text, "html.parser"))
    if not image_url:
        return {"error": "No image found on that page"}
    return {"image_url": image_url, "source_page_url": url}


def match_unit(system_key, catalogue_name, entry_name, role=None):
    """Försöker hitta en produktbild på miniset.net för en BSData-entry.

    Returnerar {"matched": True, "image_url", "image_source_url", "score",
    "matched_name"} vid en träff över MATCH_THRESHOLD, annars
    {"matched": False}. Gör aldrig fler än _MAX_REQUESTS_PER_MATCH anrop mot
    miniset.net, och varje anrop passerar det globala rate-limitet i
    _rate_limited_get."""
    game_line_slug = GAME_LINE_SLUGS.get(system_key)
    if not game_line_slug or not catalogue_name or not entry_name:
        return {"matched": False}

    faction_slug = _faction_slug(system_key, catalogue_name)
    if not faction_slug:
        return {"matched": False}

    # (category_slug, page)-par att försöka, i ordning. Rollgissningarna
    # (bara 40k, se _category_candidates_for_role) går alltid först eftersom
    # de ger mycket högre träffsäkerhet per request (en riktad underlista på
    # ett fåtal produkter istället för en osorterad fraktionslista på
    # hundratals). Återstående requestbudget läggs på att PAGINERA den råa
    # fraktionslistan (kill_team/aos har inga användbara underkategorier på
    # miniset.net, se modulens kommentar vid _ROLE_CATEGORY_HINTS) — bättre
    # täckning än att bara titta på första sidan, fortfarande begränsat av
    # _MAX_REQUESTS_PER_MATCH.
    category_slugs = _category_candidates_for_role(system_key, role)
    attempts = [(cat, 1) for cat in category_slugs]
    for page in range(1, _MAX_REQUESTS_PER_MATCH - len(attempts) + 1):
        attempts.append((None, page))
    attempts = attempts[:_MAX_REQUESTS_PER_MATCH]

    best_score = -1
    best_entry = None
    for category_slug, page in attempts:
        entries = _fetch_category(game_line_slug, faction_slug, category_slug, page)
        for entry in entries:
            score = fuzz.WRatio(entry_name, entry["name"])
            if score > best_score:
                best_score, best_entry = score, entry
        if best_score >= 97:
            break  # nära-perfekt träff — inget skäl att göra fler anrop

    if best_entry and best_score >= MATCH_THRESHOLD:
        return {
            "matched": True,
            "image_url": best_entry["image_url"],
            "image_source_url": best_entry["product_url"],
            "matched_name": best_entry["name"],
            "score": best_score,
        }
    return {"matched": False}
