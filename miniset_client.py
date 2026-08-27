"""
Klient mot miniset.net (https://miniset.net) för att bifoga referensbilder
(produktfoton) till samlingsenheter — ENDAST via en av Sivan manuellt
inklistrad länk. Se fas4b-warasset-manuell-bildlank.md för hur den flödet
ursprungligen tillkom och fas6-warasset-retire-auto-image-match.md /
CLAUDE.md ("Fas 6") för det fulla resonemanget bakom det här läget.

Fas 6 (retired den automatiska fuzzy-matchningen): den gamla match_unit()
-sök-/poängsättningslogiken (rapidfuzz-baserad namnmatchning, kategori-
slug-gissning för 40k, paginerad fallback-crawler för Kill Team/AoS) är
BORTTAGEN, inte bara avstängd — den var både den mest riskfyllda delen av
integrationen (flera gissade requests per enhet, ingen människa som
bekräftar att träffen faktiskt stämmer) och den mest sannolika drivkraften
bakom Fas 4c-incidentens request-VOLYM. Det enda sättet en bild kan
kopplas till en enhet nu är att Sivan klistrar in en specifik miniset.net-
länk (fetch_product_image nedan) — ett enda, mänskligt bekräftat anrop.

Fas 6 ändrade också vad som händer med den länken: själva bildFILEN laddas
nu ner EN gång (download_image_bytes) och cachas lokalt av anroparen
(api.py, data/uploads/miniset/<unit_id>.<ext>) istället för att hotlinkas
för alltid — se api.api_set_unit_image_from_url. Den här modulen slår
fortfarande bara UPP url:er; att spara bytes till disk är api.py:s jobb,
samma ansvarsfördelning som foto-uppladdning redan hade.

Viktigt att komma ihåg vid ändringar:
- miniset.nets robots.txt sätter "Crawl-delay: 10" för alla user agents.
  _rate_limited_get nedan garanterar >= MIN_REQUEST_INTERVAL_SECONDS mellan
  att FÖRRA anropets svar kom in och att NÄSTA anrop skickas, via ett enda
  globalt lås. Efter Fas 6 finns bara EN triggerkälla kvar (den manuella
  länken i redigera-dialogen), men den gör numera upp till TVÅ anrop för
  en produktside-länk (sidhämtning + bildnedladdning) — samma delade lås/
  cooldown skyddar båda, se download_image_bytes.
"""
import os
import re
import threading
import time
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

import database as db

BASE_URL = "https://miniset.net"
USER_AGENT = "WarAsset/1.0 (privat icke-kommersiellt inventeringsverktyg; github.com/Sivan87/WarAsset)"
REQUEST_TIMEOUT_SECONDS = 20
MIN_REQUEST_INTERVAL_SECONDS = 10

# Fas 4c incident (fas4c-warasset-miniset-incident.md, CLAUDE.md "Fas 4c"):
# miniset.net's own bot-protection flagged the Unraid server's IP despite
# the 10-second global rate-limit below being correctly shared across all
# call paths (verified by code audit during the incident — not a gap/lock
# bug). The most plausible cause given the evidence that remained:
# cumulative REQUEST VOLUME during Fas 4/4b's compressed development+test
# cycle — the automatic fuzzy-match crawler this module used to contain
# (many correctly-spaced but still numerous requests, systematically
# walking category/pagination pages). That crawler was retired entirely in
# Fas 6 for exactly this reason (see module docstring above); the circuit
# breaker below stays regardless, since even the single remaining
# human-triggered call path is still a real request to a site that has
# already flagged us once.
_BLOCK_TEXT_MARKERS = ("temporarily restricted", "suspicious automated activity")
BLOCK_COOLDOWN_HOURS = float(os.environ.get("MINISET_BLOCK_COOLDOWN_HOURS", "48"))
_BLOCK_REASON = "miniset.net returned its 'suspicious automated activity' restricted-access page"


class MinisetBlockedError(Exception):
    """Raised by _rate_limited_get — either a fresh block was just detected,
    or an earlier one is still in its cooldown window. Callers
    (fetch_product_image, download_image_bytes) catch this and turn it into
    a {"blocked": True, ...} result instead of letting it look like an
    ordinary fetch failure, so the UI can tell the two apart (see
    CLAUDE.md, Fas 4c)."""

    def __init__(self, blocked_until, reason):
        super().__init__(f"miniset.net access is in cooldown until {blocked_until} ({reason})")
        self.blocked_until = blocked_until
        self.reason = reason


def _looks_blocked(resp):
    """Text-based detection, not status-code-based: the actual status code
    miniset.net used for the block page was never confirmed (see CLAUDE.md,
    Fas 4c), so gating on a guessed code risked missing it entirely.
    Requires BOTH marker phrases from Sivan's literal observed wording to
    avoid a coincidental false positive.

    Fas 6: checked against Content-Type FIRST — download_image_bytes now
    pulls actual binary image files through this same function, and
    decoding a multi-hundred-KB JPEG as text on every download just to
    check for two English phrases would be wasted work for no benefit (the
    block page is always served as HTML, never as an image content-type)."""
    content_type = (resp.headers.get("Content-Type") or "").lower()
    if "html" not in content_type and "text" not in content_type:
        return False
    text = (resp.text or "").lower()
    return all(marker in text for marker in _BLOCK_TEXT_MARKERS)


def _raise_if_blocked():
    block = db.get_miniset_block()
    if block:
        raise MinisetBlockedError(block["blocked_until"], block["reason"])


_rate_lock = threading.Lock()
_last_request_finished_at = 0.0


def _rate_limited_get(url):
    """Se modulens docstring om rate-limit-garantin. Uppdaterar tidsstämpeln
    EFTER att svaret (eller felet) kommit in, inte innan anropet skickas —
    en strängare tolkning av "10 sekunders crawl-delay" som håller kravet
    även om ett enskilt anrop mot miniset.net skulle vara ovanligt långsamt.

    Fas 4c: also the single choke point for the circuit breaker (checked
    once before even queueing for the lock, and again right after
    acquiring it — the second check closes the race where the request
    immediately ahead of us in the queue is the one that just tripped the
    block) and for the durable request log (see database.py's
    miniset_requests table). Fas 6: also the single choke point for
    download_image_bytes, not just fetch_product_image — every real
    request to miniset.net, whatever it's for, goes through here."""
    global _last_request_finished_at
    _raise_if_blocked()
    with _rate_lock:
        _raise_if_blocked()
        wait = MIN_REQUEST_INTERVAL_SECONDS - (time.monotonic() - _last_request_finished_at)
        if wait > 0:
            time.sleep(wait)
        try:
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT_SECONDS)
        except requests.RequestException as e:
            db.log_miniset_request(url, status_code=None, error=str(e))
            raise
        finally:
            _last_request_finished_at = time.monotonic()

        if _looks_blocked(resp):
            blocked_until = db.set_miniset_block(reason=_BLOCK_REASON, cooldown_hours=BLOCK_COOLDOWN_HOURS)
            db.log_miniset_request(url, status_code=resp.status_code, blocked=True)
            print(f"[miniset_client] BLOCKED by miniset.net (status {resp.status_code}) at {url} "
                  f"— cooldown until {blocked_until}")
            raise MinisetBlockedError(blocked_until, _BLOCK_REASON)

        db.log_miniset_request(url, status_code=resp.status_code)
        return resp


def _colorbox_image_url(scope):
    """Bryter ut originalbildens URL ur en <a class="colorbox"> — en delad
    primitiv mellan en enskild, manuellt länkad produktsidas bildextraktion
    (fetch_product_image nedan). Verifierat live under utvecklingen av
    Fas 4/4b: samma colorbox-markup för originalbilden (samma fil som t.ex.
    .../set/gw-99810102007-0.jpg) används på både listnings- och
    produktsidor."""
    img_a = scope.select_one("a.colorbox")
    return img_a.get("href") if img_a else None


# En manuell bildlänk (Fas 4b) accepteras i TVÅ former:
#   1. En produktsida, /sets/<produkt-id> — huvudbilden bryts ut ur sidan.
#   2. En direkt bildfils-URL, /files/set/<produkt-id>-<n>.<ext> — t.ex.
#      https://miniset.net/files/set/gw-99120102114-3.jpg för att peka på
#      EN SPECIFIK bild i produktens galleri (inte bara "-0"-huvudbilden).
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
    """Slår upp bild-url:en för EN specifik, av Sivan manuellt vald
    miniset.net-länk (Fas 4b, se fas4b-warasset-manuell-bildlank.md — för
    edge-cases en fuzzy-matchning aldrig kunde lösa: flera "sculpts"/
    utgåvor av samma enhet, eller en hjälte som bara säljs som del av ett
    multi-hjälte-set), ELLER en specifik bild i en produkts galleri (en
    direkt bildfils-länk, se _miniset_file_product_id).

    Gör INTE själva nedladdningen av bildbytes — det gör
    download_image_bytes, anropad separat av api.py efter att den här
    funktionen lyckats (se fas6-warasset-retire-auto-image-match.md).

    En produktside-länk går igenom det globala rate-limitet
    (_rate_limited_get) och återanvänder _colorbox_image_url, se den
    funktionens docstring. En direkt bildfils-länk kräver INGET nätverks-
    anrop HÄR — den ÄR redan den slutgiltiga bild-URL:en (nedladdningen av
    dess bytes i download_image_bytes gör dock ett anrop).

    Returnerar {"image_url": "...", "source_page_url": "..."} vid träff
    (source_page_url är produktsidan krediten ska länka till — härledd
    från filnamnets produkt-id om en direkt bildlänk gavs, annars länken
    själv), annars {"error": "..."} — ALDRIG en tyst no-op."""
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
    except MinisetBlockedError as e:
        return {"error": str(e), "blocked": True, "blocked_until": e.blocked_until}
    except requests.RequestException as e:
        return {"error": f"Could not reach miniset.net: {e}"}
    if resp.status_code != 200:
        return {"error": f"miniset.net responded with status code {resp.status_code}"}
    image_url = _colorbox_image_url(BeautifulSoup(resp.text, "html.parser"))
    if not image_url:
        return {"error": "No image found on that page"}
    return {"image_url": image_url, "source_page_url": url}


# Content-Type -> filändelse för nedladdade bilder (Fas 6). Faller tillbaka
# på bildfils-URL:ens egen filändelse (se download_image_bytes) om
# servern skulle svara med en okänd/saknad Content-Type.
_EXT_BY_CONTENT_TYPE = {
    "image/jpeg": ".jpg",
    "image/pjpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


def download_image_bytes(image_url):
    """Laddar ner de faktiska bilbytesen för en image_url som redan slagits
    upp av fetch_product_image, så anroparen (api.py) kan spara en lokal
    kopia istället för att hotlinka — Fas 6, se
    fas6-warasset-retire-auto-image-match.md, uppgift 2. Går igenom SAMMA
    rate-limit/circuit-breaker som alla andra anrop mot miniset.net
    (_rate_limited_get) — nedladdningen är fortfarande ETT riktigt anrop,
    inte undantaget bara för att det "bara är en nedladdning" nu.

    Returnerar {"content": bytes, "ext": ".jpg"} vid lyckad nedladdning,
    annars {"error": "..."} (plus "blocked"/"blocked_until" om circuit
    breakern löste ut) — samma form som fetch_product_image:s felfall."""
    try:
        resp = _rate_limited_get(image_url)
    except MinisetBlockedError as e:
        return {"error": str(e), "blocked": True, "blocked_until": e.blocked_until}
    except requests.RequestException as e:
        return {"error": f"Could not download the image from miniset.net: {e}"}
    if resp.status_code != 200:
        return {"error": f"miniset.net responded with status code {resp.status_code} while downloading the image"}
    content_type = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    ext = _EXT_BY_CONTENT_TYPE.get(content_type)
    if not ext:
        ext = os.path.splitext(urlparse(image_url).path)[1].lower() or ".jpg"
    return {"content": resp.content, "ext": ext}
