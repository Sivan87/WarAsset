"""
Synktjänst mot BSData: klonar/uppdaterar de publika BSData-repona för
40k/Kill Team/AoS lokalt (data/bsdata/<repo>) och tolkar deras .cat-filer
(XML) till game_systems/catalogues/entries i databasen.

BSData-formatet i korthet (verifierat mot riktiga filer från
BSData/wh40k-10e, BSData/age-of-sigmar-4th under utveckling av den här
modulen — se CLAUDE.md, "Kända begränsningar i poäng-parsingen" för det som
INTE hanteras):

- Varje repo har en .gst-fil (spelsystemets globala definitioner) och en
  .cat-fil per katalog. Vi bryr oss bara om .cat-filerna — .gst-filen
  behövs inte, eftersom varje enhets roll redan finns som klartext i dess
  egen <categoryLink primary="true" name="...">.
- Root-elementet <catalogue> har attributen id/name/revision/library.
  library="true" betyder att katalogen inte är en spelbar fraktion i sig
  själv utan bara en delad datakälla som andra kataloger importerar via
  <catalogueLinks><catalogueLink targetId="..."/> — det här mönstret
  används på TVÅ olika sätt i de repon vi synkar:
    1. AoS: varje fraktions riktiga units ligger i en separat
       "<Fraktion> - Library.cat" (library="true") som huvudfilen
       "<Fraktion>.cat" (library="false") länkar in.
    2. 40k: en undergrenskatalog (t.ex. "Blood Angels", library="false")
       länkar in sin bas-katalog (t.ex. "Space Marines", också
       library="false" — den är spelbar på egen hand också) för att få
       tillgång till de generiska enheterna.
  Vi hanterar båda fallen med SAMMA generella mekanism: en spelbar katalog
  (library="false") får sina entries från summan av sina EGNA direkt
  definierade unit-selectionEntries plus (rekursivt) samma sak för varje
  katalog den <catalogueLink>:ar till, oavsett om den länkade katalogen
  själv råkar heta "... - Library" eller ej.
- Endast selectionEntry/sharedSelectionEntry av type="unit" ELLER type="model"
  (med en egen <costs>) som är DIREKTA barn av katalogens rot räknas som en
  registrerbar enhet (datasheet) — se _direct_unit_entries. Nästlade
  type="model"/"upgrade"-poster INUTI en sådan post (vapen, enskilda
  miniatyrer i en trupp) är underval och ignoreras som egna entries.
"""
import glob
import json
import os
import re
import subprocess
import xml.etree.ElementTree as ET

import database as db

BSDATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "bsdata")

# De tre repona som synkas. Kill Team-repot heter historiskt "wh40k-killteam"
# trots att det numera täcker den fristående Kill Team-utgåvan; Age of
# Sigmar pekar på 4:e utgåvans repo (det aktiva när den här modulen
# skrevs — BSData arkiverar föregående utgåvors repo när en ny utgåva
# släpps, så den här raden kan behöva bytas ut vid en framtida AoS-utgåva).
GAME_SYSTEMS = [
    {"key": "40k", "name": "Warhammer 40,000", "bsdata_repo": "BSData/wh40k-10e"},
    {"key": "kill_team", "name": "Kill Team", "bsdata_repo": "BSData/wh40k-killteam"},
    {"key": "aos", "name": "Age of Sigmar", "bsdata_repo": "BSData/age-of-sigmar-4th"},
]


# ---------------------------------------------------------------------------
# git clone/pull
# ---------------------------------------------------------------------------

def _repo_dir(repo_slug):
    return os.path.join(BSDATA_DIR, repo_slug.split("/")[-1])


def _git_clone_or_pull(repo_slug):
    """Klonar repot första gången, drar annars ner senaste ändringarna.
    --depth 1 (både vid clone och genom att alltid dra om en grund klon)
    håller nere diskanvändningen — vi bryr oss bara om senaste versionen av
    XML-filerna, inte historiken."""
    repo_dir = _repo_dir(repo_slug)
    url = f"https://github.com/{repo_slug}.git"
    if os.path.isdir(os.path.join(repo_dir, ".git")):
        print(f"[bsdata_sync] git pull {repo_slug}")
        subprocess.run(
            ["git", "-C", repo_dir, "pull", "--ff-only", "--depth", "1"],
            check=True, capture_output=True, text=True, timeout=120,
        )
    else:
        print(f"[bsdata_sync] git clone {repo_slug}")
        os.makedirs(BSDATA_DIR, exist_ok=True)
        subprocess.run(
            ["git", "clone", "--depth", "1", url, repo_dir],
            check=True, capture_output=True, text=True, timeout=300,
        )
    return repo_dir


# ---------------------------------------------------------------------------
# XML-parsing
# ---------------------------------------------------------------------------

def _strip_namespace(root):
    """BSData-filerna deklarerar en XML-namespace (catalogueSchema resp.
    gameSystemSchema) som annars tvingar fram namespace-prefix på varje
    ElementTree-sökning. Vi bryr oss inte om exakt schemaversion, så vi
    plattar till alla taggnamn till sina lokala namn en gång vid inläsning
    istället för att hantera namespaces genomgående."""
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


def _parse_catalogue_file(path):
    tree = ET.parse(path)
    root = _strip_namespace(tree.getroot())
    if root.tag != "catalogue":
        return None
    links_el = root.find("catalogueLinks")
    link_targets = [cl.get("targetId") for cl in links_el.findall("catalogueLink")] if links_el is not None else []
    return {
        "id": root.get("id"),
        "name": root.get("name"),
        "revision": root.get("revision"),
        "library": root.get("library") == "true",
        "file": os.path.basename(path),
        "root": root,
        "links": [t for t in link_targets if t],
    }


def _load_catalogues(repo_dir):
    catalogues = {}
    for path in glob.glob(os.path.join(repo_dir, "*.cat")):
        try:
            parsed = _parse_catalogue_file(path)
        except ET.ParseError as e:
            print(f"[bsdata_sync] Kunde inte tolka {path}: {e}")
            continue
        if parsed and parsed["id"]:
            catalogues[parsed["id"]] = parsed
    return catalogues


def _build_entry_index(catalogues):
    """Global uppslagning bsdata_id -> (element, filnamn) över ALLA
    selectionEntry-element (oavsett nästlingsdjup) i samtliga inlästa
    kataloger i repot. Behövs för att slå upp target för <entryLink>
    (se _direct_unit_entries) — targetId kan peka på ett element i en helt
    ANNAN fil än den som innehåller själva länken (typiskt: en fraktions
    huvudfil länkar in en specifik enhet från "<Fraktion> - Library.cat").
    Täcker även <sharedSelectionEntries>-innehåll (t.ex. fristående
    vapen-"upgrades" som operatörer/trupper länkar in via entryLink) — det
    är fortfarande bara <selectionEntry>-taggar, bara i en annan
    föräldratagg, så .iter("selectionEntry") hittar dem automatiskt."""
    index = {}
    for cat in catalogues.values():
        for el in cat["root"].iter("selectionEntry"):
            eid = el.get("id")
            if eid and eid not in index:
                index[eid] = (el, cat["file"])
    return index


def _build_profile_index(catalogues):
    """Global uppslagning profile-id -> element över ALLA <profile>-element
    i repot (oavsett om de sitter nästlade i en selectionEntry eller i ett
    rot-nivå <sharedProfiles>-block). Behövs för att slå upp target för
    <infoLink type="profile"> (se _collect_profiles) — samma sorts
    indirektion som _build_entry_index löser för <entryLink>, men för delade
    profiler (t.ex. en ledarmodells namngivna specialregel/aura, definierad
    en gång i <sharedProfiles> och återanvänd av flera selectionEntries)."""
    index = {}
    for cat in catalogues.values():
        for el in cat["root"].iter("profile"):
            pid = el.get("id")
            if pid and pid not in index:
                index[pid] = el
    return index


def _direct_unit_entries(cat, entry_index):
    """
    Registrerbara enheter som är DIREKTA barn av katalogens rot, som
    (name, bsdata_id, cost_el, structure_el, source_file)-tupler.
    cost_el är elementet vars <costs>/<modifiers> ska användas för
    poängberäkning; structure_el är elementet vars <categoryLinks>/
    <selectionEntryGroups> ska användas för roll/nyckelord/modellantal — de
    är samma element i normalfallet, men olika för entryLink-fallet nedan.

    Två sorters direkta barn hanteras, båda verifierade mot riktiga filer:

    1. Ett vanligt <selectionEntry type="unit|model"> MED en egen <costs>.
       ("unit" = vanlig form för trupper/squads i 40k/AoS. "model" = dels
       fordon/fristående karaktärer som annars hade missats helt, t.ex.
       Space Marines "Rhino"/"Land Raider", dels är det formen Kill Team
       genomgående använder för varje operatör.) cost_el = structure_el =
       samma element.

    2. Ett <entryLink type="selectionEntry"> vars targetId pekar på en
       type="unit|model"-post — upptäckt genom att Age of Sigmar 4:e
       utgåvans "Liberators" (Stormcast Eternals) annars helt saknade poäng:
       enhetens regler/kategorier ligger i "Stormcast Eternals - Library.cat",
       men själva POÄNGKOSTNADEN (90p) sitter på entryLinken i
       "Stormcast Eternals.cat", den fil som faktiskt importerar den till
       arméns lista. Vi använder entryLinkens EGNA <costs>/<modifiers> när
       den har några, annars target-elementets — men ALLTID
       target-elementets <categoryLinks>/<selectionEntryGroups> för
       roll/nyckelord/modellantal (den datan dupliceras inte på
       entryLinken). Om varken länken eller målet har ett pris hoppas
       posten över (den är då inte en köpbar datasheet).
    """
    root = cat["root"]
    out = []
    seen_ids = set()

    def _add(name, bsdata_id, cost_el, structure_el, source_file):
        if not name or not bsdata_id or bsdata_id in seen_ids:
            return
        seen_ids.add(bsdata_id)
        out.append((name, bsdata_id, cost_el, structure_el, source_file))

    for container_tag in ("selectionEntries", "sharedSelectionEntries"):
        container = root.find(container_tag)
        if container is None:
            continue
        for entry in container.findall("selectionEntry"):
            if entry.get("type") in ("unit", "model") and entry.find("costs") is not None:
                _add(entry.get("name"), entry.get("id"), entry, entry, cat["file"])

    # entryLinks bor i ett EGET rot-element <entryLinks>, en SYSKON-tagg till
    # <selectionEntries> (inte nästlad i den) — bekräftat genom att
    # Stormcast Eternals "Liberators"-entryLinken annars aldrig hittades.
    links_container = root.find("entryLinks")
    if links_container is not None:
        for link in links_container.findall("entryLink"):
            if link.get("type") != "selectionEntry":
                continue
            target = entry_index.get(link.get("targetId"))
            if target is None:
                continue
            target_el, target_file = target
            if target_el.get("type") not in ("unit", "model"):
                continue
            cost_el = link if link.find("costs") is not None else target_el
            if cost_el.find("costs") is None:
                continue
            _add(link.get("name") or target_el.get("name"), target_el.get("id"), cost_el, target_el, target_file)

    return out


# Hur många steg av catalogueLinks som följs från en spelbar fraktions egen
# katalogfil. 1 räcker för de båda verifierade mönstren (40k:
# undergrenskatalog -> baskatalog; AoS: fraktion -> "<Fraktion> - Library").
# Att följa längre (obegränsat) visade sig i praktiken explodera för AoS:
# flera fraktioner länkar (direkt eller via sitt Library-lager) till delade
# "hub"-kataloger som "Regiments of Renown", vilka i sin tur länkar vidare
# till DECENNIER av andra, orelaterade fraktioners egna bibliotek — utan
# djupbegränsning drog varje AoS-fraktion in >1000 entries från i praktiken
# hela spelsystemet. Med djup=1 inkluderas Regiments of Renown-katalogens
# EGNA formationer (rimligt, spelare kan faktiskt ta dem) men inte de
# ytterligare fraktionsbiblioteken den i sin tur länkar till.
_MAX_LINK_DEPTH = 1


def _collect_entries_for_faction(cat, catalogues, entry_index, visited=None, depth=0):
    """Se moduldocstringen: en spelbar katalogs entries = dess egna +
    entries från varje katalog den direkt länkar till via catalogueLinks
    (se _MAX_LINK_DEPTH ovan för varför det INTE görs rekursivt på
    obegränsat djup). `visited` skyddar mot cirkulära länkar inom det
    tillåtna djupet.

    Kan ge enstaka dubbletter av samma bsdata_id inom en fraktion om
    samma enhet nås både via ett direkt entryLink (med sin egen kostnad,
    se _direct_unit_entries) OCH via en depth-1-länkad katalogs råa
    selectionEntry (om den råkar ha en egen giltig kostnad också) — då
    vinner den som skrivs sist (db.upsert_entry är en UPSERT). Ovanligt och
    självläkande vid nästa synk om ordningen skulle ge fel pris, men värt
    att känna till."""
    if visited is None:
        visited = set()
    if cat["id"] in visited:
        return []
    visited.add(cat["id"])
    entries = _direct_unit_entries(cat, entry_index)
    if depth >= _MAX_LINK_DEPTH:
        return entries
    for target_id in cat["links"]:
        linked = catalogues.get(target_id)
        if linked is not None:
            entries.extend(_collect_entries_for_faction(linked, catalogues, entry_index, visited, depth=depth + 1))
    return entries


# --- poäng- och antal-heuristik -------------------------------------------

def _own_constraint_range(el):
    """min/max från ett elements EGNA direkta <constraints>-barn, begränsat
    till field="selections" scope="parent" (dvs "hur många av mig får/måste
    väljas inom min förälder") — det är det enda constraint-mönster som
    faktiskt beskriver truppstorlek i BSData. Returnerar (None, None) om
    elementet saknar en sådan constraint."""
    constraints_el = el.find("constraints")
    if constraints_el is None:
        return None, None
    min_v = max_v = None
    for c in constraints_el.findall("constraint"):
        if c.get("field") != "selections" or c.get("scope") != "parent":
            continue
        try:
            val = int(float(c.get("value")))
        except (TypeError, ValueError):
            continue
        if c.get("type") == "min":
            min_v = val
        elif c.get("type") == "max":
            max_v = val
    return min_v, max_v


def _model_count_range(unit_el):
    """
    Uppskattar hur många modeller enheten kan bestå av, genom att leta upp
    de selectionEntryGroups som är direkta barn av unit-entryn och vars
    innehåll är av type="model" (dvs faktiska miniatyrer — grupper som bara
    innehåller "upgrade"-vapen eller Crusade-tillval hoppas över).

    Prioritetsordning per grupp (verifierad mot riktiga datasheets, se
    moduldocstringen):
      1. Gruppens EGEN constraint (min OCH max båda satta där) — det
         vanligaste och mest tillförlitliga fallet, t.ex. Intercessor
         Squad har min=5/max=10 direkt på gruppen "Intercessors" (1
         obligatorisk sergeant + 4-9 menige, korrekt hopräknat till 5-10).
      2. Om gruppen bara innehåller EN model-post: använd den postens egna
         min/max istället (grupp-constraint saknar ofta max när det bara
         finns ett alternativ, t.ex. Poxwalkers-gruppen har bara min=10 på
         gruppnivå men modellposten "Poxwalker" har min=10/max=20).
      3. Annars (flera model-poster utan en tydlig grupp-constraint):
         summera varje posts egna min/max rakt av. Kan överskatta max när
         posterna egentligen är ALTERNATIV till varandra snarare än
         tillägg (känd begränsning, se CLAUDE.md).
    Fallback om inget kan avgöras alls (karaktärer, fordon, enstaka
    enheter utan sammansättningsgrupper): (1, 1).
    """
    total_min = total_max = 0
    found = False

    # Fristående ledare/modeller som är DIREKTA barn av unit-entryns egna
    # <selectionEntries> (dvs inte insvepta i en selectionEntryGroup) — t.ex.
    # "Plague Champion" i Death Guards Plague Marines, en obligatorisk
    # gruppledare som annars missas helt av loopen över
    # <selectionEntryGroups> nedan.
    direct_entries_el = unit_el.find("selectionEntries")
    if direct_entries_el is not None:
        for e in direct_entries_el.findall("selectionEntry"):
            if e.get("type") != "model":
                continue
            c_min, c_max = _own_constraint_range(e)
            total_min += c_min if c_min is not None else 1
            total_max += c_max if c_max is not None else (c_min if c_min is not None else 1)
            found = True

    groups_el = unit_el.find("selectionEntryGroups")
    if groups_el is None:
        return (max(total_min, 1), max(total_max, total_min, 1)) if found else (1, 1)

    for group in groups_el.findall("selectionEntryGroup"):
        entries_el = group.find("selectionEntries")
        model_children = []
        if entries_el is not None:
            model_children = [e for e in entries_el.findall("selectionEntry") if e.get("type") == "model"]
        if not model_children:
            continue

        g_min, g_max = _own_constraint_range(group)
        if g_min is not None and g_max is not None:
            total_min += g_min
            total_max += g_max
        elif len(model_children) == 1:
            c_min, c_max = _own_constraint_range(model_children[0])
            total_min += c_min if c_min is not None else 1
            total_max += c_max if c_max is not None else (c_min if c_min is not None else 1)
        else:
            for e in model_children:
                c_min, c_max = _own_constraint_range(e)
                total_min += c_min or 0
                total_max += c_max if c_max is not None else (c_min or 0)
        found = True

    if not found:
        return 1, 1
    return max(total_min, 1), max(total_max, total_min, 1)


def _base_cost(unit_el):
    """Grundkostnaden i poäng och dess cost-typeId —
    <costs><cost name="pts" typeId="..." value="X"/></costs> direkt under
    unit-entryn. Ignorerar övriga cost-typer (Crusade Points m.fl., inte
    relevanta för WarAsset). typeId behövs för att matcha ihop med
    _count_based_cost_overrides nedan."""
    costs_el = unit_el.find("costs")
    if costs_el is None:
        return None, None
    for c in costs_el.findall("cost"):
        if c.get("name") == "pts":
            typeid = c.get("typeId")
            try:
                return int(float(c.get("value"))), typeid
            except (TypeError, ValueError):
                return None, typeid
    return None, None


def _count_based_cost_overrides(unit_el, pts_typeid):
    """
    Fångar det VERKLIGA exemplet på poäng-som-varierar-med-antal som hittades
    i Death Guards "Plague Marines" under utvecklingen av den här modulen:
    en <modifier type="set" field="<pts-typeId>" value="X"> vars
    <conditions> innehåller <condition field="selections" type="atLeast"
    childId="model" value="N">, dvs "från och med N modeller i enheten,
    kosta X poäng istället för grundkostnaden". childId="model" är BSData:s
    generiska referens till "vilken modell som helst i den här enheten"
    (inte en specifik under-entry), så N är ett rakt totalt modellantal.

    Andra modifier-mönster (t.ex. villkorade på en SPECIFIK vapenkedja,
    eller på annat än totalt modellantal) hanteras inte och ignoreras tyst —
    se "Kända begränsningar i poäng-parsingen" i CLAUDE.md.
    """
    if not pts_typeid:
        return []
    modifiers_el = unit_el.find("modifiers")
    if modifiers_el is None:
        return []
    out = []
    for m in modifiers_el.findall("modifier"):
        if m.get("type") != "set" or m.get("field") != pts_typeid:
            continue
        try:
            new_value = int(float(m.get("value")))
        except (TypeError, ValueError):
            continue
        conditions_el = m.find("conditions")
        if conditions_el is None:
            continue
        for c in conditions_el.findall("condition"):
            if c.get("field") == "selections" and c.get("type") == "atLeast" and c.get("childId") == "model":
                try:
                    count = int(float(c.get("value")))
                except (TypeError, ValueError):
                    continue
                out.append({"count": count, "points": new_value})
    return out


def _compute_points_table(cost_el, structure_el):
    """
    Bygger entries.points_table: grundkostnaden vid det lägsta modellantalet
    (från _model_count_range på structure_el), plus ev. count-baserade
    prishöjningar hittade av _count_based_cost_overrides (på cost_el).

    cost_el och structure_el är samma element i normalfallet — men olika
    för AoS entryLink-fallet (se _direct_unit_entries): poängen sitter på
    entryLinken, modellsammansättningen på target-elementet i Library-filen.

    KÄND BEGRÄNSNING (flaggad redan i kickoff-dokumentet som den svåraste
    delen, se CLAUDE.md): för de allra flesta datasheets (verifierat mot
    wh40k-10e och age-of-sigmar-4th) finns ingen sådan modifier alls — GW:s
    nuvarande poängsystem prissätter oftast inte extra lösa modeller inom
    det tryckta min-max-intervallet (t.ex. Poxwalkers 10-20, Intercessor
    Squad 5-10 kostar samma oavsett hur många av de tillåtna modellerna man
    tar). points_table blir då en lista med EN post. Mönstret ovan täcker
    bara det enda konkreta motexemplet vi hittade (Plague Marines, som höjer
    priset vid 6 och 8 modeller) — andra, annorlunda uttryckta varianter kan
    fortfarande missas. Saknas en exakt träff faller uppslagningen i
    database.py:_points_for_count tillbaka på "närmaste antal" istället för
    att krascha.
    """
    base, pts_typeid = _base_cost(cost_el)
    min_c, max_c = _model_count_range(structure_el)
    if base is None:
        return [], min_c, max_c
    table = [{"count": min_c, "points": base}]
    table.extend(_count_based_cost_overrides(cost_el, pts_typeid))
    table.sort(key=lambda r: r["count"])
    return table, min_c, max_c


def _parse_profile_element(profile_el):
    """Ett <profile>-element till entries.profiles-formatet (se CLAUDE.md,
    Fas 3): {"name": ..., "type": ..., "characteristics": {...}}. name/type
    kommer rakt av från profilens egna name/typeName-attribut (typeName är
    redan uppslaget klartext i XML:en, t.ex. "Unit"/"Ranged Weapons"/
    "Abilities" i 40k, "Operative"/"Weapons" i Kill Team, "Unit"/"Melee
    Weapon" i AoS — vi behöver alltså aldrig slå upp den mot .gst-filens
    <profileTypes>). characteristics byggs i samma dokumentordning som
    XML:en (Python-dictar är ordnade sedan 3.7), t.ex. M/T/SV/W/LD/OC för en
    40k-enhet."""
    characteristics = {}
    chars_el = profile_el.find("characteristics")
    if chars_el is not None:
        for c in chars_el.findall("characteristic"):
            name = c.get("name")
            if name:
                characteristics[name] = (c.text or "").strip()
    return {"name": profile_el.get("name"), "type": profile_el.get("typeName"), "characteristics": characteristics}


# Hur många nivåer av nästlade selectionEntries/selectionEntryGroups/
# entryLinks _collect_profiles följer nedåt från en enhets structure_el
# (vapenval sitter typiskt bakom 3-5 nivåer, se moduldocstring-exemplet med
# Death Guards "Plague Champion" -> Wargear-grupp -> "Plague knives
# options"-grupp -> entryLink -> vapnets egna profiler). Ett djuptak här är
# bara en säkerhetsspärr mot orimligt djupt/cirkulärt nästlade filer, inte
# ett förväntat gränsfall i praktiken.
_MAX_PROFILE_DEPTH = 10


def _collect_profiles(el, entry_index, profile_index, visited_entries=None, seen_profile_ids=None, depth=0):
    """Samlar ALLA profiler (karaktäristik/vapen/förmågor) som hör till en
    enhet: dess egna <profiles>, delade profiler nådda via
    <infoLinks><infoLink type="profile"> (samma indirektionsmönster som
    redan löstes för AoS-poäng på entryLink i Fas 1, se _build_profile_index
    ovan), samt — rekursivt, eftersom en trupps vapenval i BSData:s XML
    typiskt ligger flera <selectionEntryGroups>/<entryLinks>-nivåer under
    själva unit-entryn snarare än direkt på den (se _MAX_PROFILE_DEPTH) —
    profilerna för varje nästlad modell/vapen/uppgradering under enheten.

    Det gör att t.ex. Plague Marines popover visar både trupp-statblocket
    OCH samtliga tillgängliga vapenprofiler (boltgevär, plasmapistol,
    kraftnäve, ...) — inte bara den utrustning som råkar vara vald just nu,
    eftersom collection_units (se produktbeslutet i CLAUDE.md) bara
    registrerar ANTAL modeller, inte enskilda vapenval. Det är en medveten
    följd av verktygets registreringsnivå, inte ett förbiseende.

    Dedupe:ar på profil-id (seen_profile_ids) så samma delade vapenprofil
    inte dyker upp flera gånger om flera väljbara alternativ länkar till
    samma mål. visited_entries skyddar mot cirkulära entryLink-kedjor."""
    if visited_entries is None:
        visited_entries = set()
    if seen_profile_ids is None:
        seen_profile_ids = set()
    if depth > _MAX_PROFILE_DEPTH:
        return []
    el_id = el.get("id")
    if el_id and el_id in visited_entries:
        return []
    if el_id:
        visited_entries.add(el_id)

    out = []

    def _add(profile_el):
        pid = profile_el.get("id")
        if pid and pid in seen_profile_ids:
            return
        if pid:
            seen_profile_ids.add(pid)
        out.append(_parse_profile_element(profile_el))

    profiles_el = el.find("profiles")
    if profiles_el is not None:
        for p in profiles_el.findall("profile"):
            _add(p)

    info_links_el = el.find("infoLinks")
    if info_links_el is not None:
        for link in info_links_el.findall("infoLink"):
            if link.get("type") != "profile":
                continue
            target = profile_index.get(link.get("targetId"))
            if target is not None:
                _add(target)

    for container_tag in ("selectionEntries", "sharedSelectionEntries"):
        container = el.find(container_tag)
        if container is None:
            continue
        for child in container.findall("selectionEntry"):
            out.extend(_collect_profiles(child, entry_index, profile_index, visited_entries, seen_profile_ids, depth + 1))

    entry_links_el = el.find("entryLinks")
    if entry_links_el is not None:
        for link in entry_links_el.findall("entryLink"):
            if link.get("type") != "selectionEntry":
                continue
            target = entry_index.get(link.get("targetId"))
            if target is None:
                continue
            target_el, _file = target
            out.extend(_collect_profiles(target_el, entry_index, profile_index, visited_entries, seen_profile_ids, depth + 1))

    groups_el = el.find("selectionEntryGroups")
    if groups_el is not None:
        for group in groups_el.findall("selectionEntryGroup"):
            out.extend(_collect_profiles(group, entry_index, profile_index, visited_entries, seen_profile_ids, depth + 1))

    return out


def _role_and_keywords(unit_el):
    links_el = unit_el.find("categoryLinks")
    if links_el is None:
        return None, []
    role = None
    keywords = []
    for link in links_el.findall("categoryLink"):
        name = link.get("name")
        if not name:
            continue
        keywords.append(name)
        if link.get("primary") == "true":
            role = name
    if role is None and keywords:
        role = keywords[0]
    return role, keywords


# ---------------------------------------------------------------------------
# Synk-orkestrering
# ---------------------------------------------------------------------------

_YEAR_PREFIX_RE = re.compile(r"^(\d{4}) - ")


def _dedupe_versioned_catalogues(faction_catalogues):
    """Kill Team-repot håller kvar filer för flera regelutgåvor av samma
    fraktion sida vid sida (t.ex. "2021 - Blooded.cat" OCH
    "2024 - Blooded.cat", båda library="false", båda med samma
    <catalogue name="Blooded">) — utan den här filtreringen hade "Blooded"
    dykt upp som två identiskt namngivna, förvirrande dubbletter i sök-API:t.
    Vi litar på filnamnets "YYYY - "-prefix (det enda mönster vi observerat
    i praktiken) och behåller bara den nyaste årgången per fraktionsnamn.
    Fraktioner UTAN det prefixet (40k, AoS) påverkas inte alls."""
    by_name = {}
    for cat in faction_catalogues:
        by_name.setdefault(cat["name"], []).append(cat)

    kept = []
    for name, group in by_name.items():
        if len(group) == 1:
            kept.append(group[0])
            continue
        years = [(_YEAR_PREFIX_RE.match(c["file"]), c) for c in group]
        if all(m for m, _ in years):
            newest = max(years, key=lambda pair: int(pair[0].group(1)))[1]
            print(f"[bsdata_sync] '{name}': behåller {newest['file']} (hoppar över {len(group) - 1} äldre årgång(ar))")
            kept.append(newest)
        else:
            kept.extend(group)
    return kept


def _sync_one_game_system(conn, gs_row):
    repo_dir = _git_clone_or_pull(gs_row["bsdata_repo"])
    catalogues = _load_catalogues(repo_dir)
    entry_index = _build_entry_index(catalogues)
    profile_index = _build_profile_index(catalogues)
    faction_catalogues = [c for c in catalogues.values() if not c["library"]]
    faction_catalogues = _dedupe_versioned_catalogues(faction_catalogues)

    seen_catalogue_bsids = set()
    catalogue_count = 0
    entry_count = 0

    for cat in faction_catalogues:
        catalogue_db_id = db.upsert_catalogue(conn, gs_row["id"], cat["id"], cat["name"], cat["revision"])
        seen_catalogue_bsids.add(cat["id"])
        catalogue_count += 1

        seen_entry_bsids = set()
        for name, bsdata_id, cost_el, structure_el, source_file in _collect_entries_for_faction(cat, catalogues, entry_index):
            role, keywords = _role_and_keywords(structure_el)
            points_table, _min_c, _max_c = _compute_points_table(cost_el, structure_el)
            profiles = _collect_profiles(structure_el, entry_index, profile_index)
            raw_source_ref = f"{source_file}::{bsdata_id}"
            db.upsert_entry(conn, catalogue_db_id, bsdata_id, name, role, keywords, points_table, profiles, raw_source_ref)
            seen_entry_bsids.add(bsdata_id)
            entry_count += 1

        db.prune_missing_entries(conn, catalogue_db_id, seen_entry_bsids)

    db.prune_missing_catalogues(conn, gs_row["id"], seen_catalogue_bsids)
    db.mark_game_system_synced(conn, gs_row["id"])
    return {"catalogues": catalogue_count, "entries": entry_count}


def run_full_sync():
    """Synkar alla tre spelsystem. Anropas vid appstart, från den dagliga
    bakgrundstråden i app.py, och från POST /api/sync. En enda
    WRITE_LOCK-transaktion per spelsystem (inte per rad) — se
    database.py:WRITE_LOCK — så en pågående synk inte håller låset i minuter
    åt gången och blockerar vanliga API-anrop mer än nödvändigt."""
    results = {}
    with db.WRITE_LOCK:
        conn = db.get_connection()
        for gs in GAME_SYSTEMS:
            db.upsert_game_system(conn, gs["key"], gs["name"], gs["bsdata_repo"])
        conn.commit()
        conn.close()

    for gs in GAME_SYSTEMS:
        with db.WRITE_LOCK:
            conn = db.get_connection()
            gs_row = db.get_game_system_by_key(gs["key"], conn=conn)
            try:
                stats = _sync_one_game_system(conn, gs_row)
                conn.commit()
                results[gs["key"]] = {"ok": True, **stats}
                print(f"[bsdata_sync] {gs['key']}: {stats['catalogues']} kataloger, {stats['entries']} entries")
            except Exception as e:
                conn.rollback()
                print(f"[bsdata_sync] Synk misslyckades för {gs['key']}: {e}")
                results[gs["key"]] = {"ok": False, "error": str(e)}
            finally:
                conn.close()
    return results
