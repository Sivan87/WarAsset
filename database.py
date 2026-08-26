"""
Databaslager för WarAsset. Använder SQLite (ingen serverinstallation krävs),
samma grundmönster som BrickRadar-Web/database.py.

Schema (se CLAUDE.md för den fullständiga beskrivningen):
  game_systems      - vilka spelsystem som synkas (40k/kill_team/aos) + vilket
                       BSData-repo respektive system kommer från
  catalogues        - en rad per spelbar fraktion (BSData-katalog), knuten
                       till ett game_system
  entries           - en rad per datasheet/enhet i BSData (källan till
                       sanning för fraktion/roll/poäng/nyckelord)
  collection_units  - Sivans faktiska samling. entry_id pekar på entries när
                       enheten kommer från BSData-sökningen (normalfallet);
                       nullable som undantagsventil för konverteringar/
                       scratch-builds som inte finns i BSData (se
                       name_override)
"""
import json
import os
import sqlite3
import threading
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "warasset.db")

# Samma SQLite-skrivproblematik som BrickRadar löste (se dess database.py):
# WAL-läge + lång busy_timeout + ett processglobalt lås runt alla skrivningar,
# så att bakgrundstrådar (BSData-synken) och API-anrop aldrig krockar med
# "database is locked". WRITE_LOCK är medvetet inte "privat" (inget
# understreck) — bsdata_sync.py delar samma lås för sina egna
# bulk-skrivningar (många upserts i en enda transaktion/commit istället för
# en per rad, se _sync_catalogue i bsdata_sync.py).
WRITE_LOCK = threading.RLock()

STATUSES = ("unbuilt", "built", "painted")


def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def init_db():
    """Skapar tabeller om de inte redan finns. Körs vid varje serverstart (idempotent)."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS game_systems (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            bsdata_repo TEXT NOT NULL,
            last_synced_at TEXT
        );

        CREATE TABLE IF NOT EXISTS catalogues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_system_id INTEGER NOT NULL REFERENCES game_systems(id) ON DELETE CASCADE,
            bsdata_id TEXT NOT NULL,
            name TEXT NOT NULL,
            revision TEXT,
            UNIQUE(game_system_id, bsdata_id)
        );

        CREATE TABLE IF NOT EXISTS entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            catalogue_id INTEGER NOT NULL REFERENCES catalogues(id) ON DELETE CASCADE,
            bsdata_id TEXT NOT NULL,
            name TEXT NOT NULL,
            role TEXT,
            keywords TEXT NOT NULL DEFAULT '[]',
            points_table TEXT NOT NULL DEFAULT '[]',
            profiles TEXT NOT NULL DEFAULT '[]',
            raw_source_ref TEXT,
            UNIQUE(catalogue_id, bsdata_id)
        );
        CREATE INDEX IF NOT EXISTS idx_entries_name ON entries(name);

        -- entry_id har medvetet INGEN ON DELETE CASCADE: när BSData-synken
        -- tar bort en entry som inte längre finns i källdatan ska raden i
        -- collection_units överleva (se prune_missing_entries nedan, som
        -- kopierar namn/poäng till *_override innan länken nollas), inte
        -- försvinna tyst. Det är hela poängen med kravet i kickoff-dokumentet
        -- att synken aldrig får röra användarens egen data.
        CREATE TABLE IF NOT EXISTS collection_units (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entry_id INTEGER REFERENCES entries(id) ON DELETE SET NULL,
            name_override TEXT,
            count INTEGER NOT NULL DEFAULT 1,
            points_override INTEGER,
            status TEXT NOT NULL DEFAULT 'unbuilt',
            photo_path TEXT,
            image_url TEXT,
            image_source_url TEXT,
            image_checked_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_collection_units_entry ON collection_units(entry_id);
    """)
    conn.commit()
    _migrate_add_entries_profiles(conn)
    _migrate_add_collection_units_image_fields(conn)
    conn.close()


def _migrate_add_entries_profiles(conn):
    """Fas 3: entries.profiles fanns inte i Fas 1/2:s schema. CREATE TABLE IF
    NOT EXISTS ovan rör inte en redan existerande entries-tabell, så en
    databas skapad före Fas 3 saknar kolumnen tills den läggs till här.
    Rör bara entries (skrivs om av synken ändå) — collection_units är, precis
    som alltid, helt orörd av migreringen."""
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(entries)").fetchall()}
    if "profiles" not in cols:
        conn.execute("ALTER TABLE entries ADD COLUMN profiles TEXT NOT NULL DEFAULT '[]'")
        conn.commit()


def _migrate_add_collection_units_image_fields(conn):
    """Fas 4: image_url/image_source_url/image_checked_at (miniset.net-
    referensbilder) fanns inte i Fas 1-3:s schema. Samma mönster som
    _migrate_add_entries_profiles ovan, men på collection_units eftersom
    bilderna är kopplade till Sivans ägda enheter, inte BSData-katalogen
    (se produktbeslutet i fas4-warasset-miniset-bilder.md om varför)."""
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(collection_units)").fetchall()}
    if "image_url" not in cols:
        conn.execute("ALTER TABLE collection_units ADD COLUMN image_url TEXT")
        conn.execute("ALTER TABLE collection_units ADD COLUMN image_source_url TEXT")
        conn.execute("ALTER TABLE collection_units ADD COLUMN image_checked_at TEXT")
        conn.commit()


# ---------------------------------------------------------------------------
# game_systems
# ---------------------------------------------------------------------------

def list_game_systems(conn=None):
    owns_conn = conn is None
    conn = conn or get_connection()
    rows = [dict(r) for r in conn.execute("SELECT * FROM game_systems ORDER BY id").fetchall()]
    if owns_conn:
        conn.close()
    return rows


def get_game_system_by_key(key, conn=None):
    owns_conn = conn is None
    conn = conn or get_connection()
    row = conn.execute("SELECT * FROM game_systems WHERE key = ?", (key,)).fetchone()
    if owns_conn:
        conn.close()
    return dict(row) if row else None


def upsert_game_system(conn, key, name, bsdata_repo):
    """Körs alltid inuti bsdata_sync:s egen WRITE_LOCK/commit — se kommentaren
    vid WRITE_LOCK ovan. Ingen commit här."""
    conn.execute(
        """INSERT INTO game_systems (key, name, bsdata_repo, last_synced_at)
           VALUES (?, ?, ?, NULL)
           ON CONFLICT(key) DO UPDATE SET name = excluded.name, bsdata_repo = excluded.bsdata_repo""",
        (key, name, bsdata_repo),
    )
    return conn.execute("SELECT id FROM game_systems WHERE key = ?", (key,)).fetchone()["id"]


def mark_game_system_synced(conn, game_system_id):
    conn.execute("UPDATE game_systems SET last_synced_at = ? WHERE id = ?", (now_iso(), game_system_id))


# ---------------------------------------------------------------------------
# catalogues
# ---------------------------------------------------------------------------

def upsert_catalogue(conn, game_system_id, bsdata_id, name, revision):
    conn.execute(
        """INSERT INTO catalogues (game_system_id, bsdata_id, name, revision)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(game_system_id, bsdata_id) DO UPDATE SET name = excluded.name, revision = excluded.revision""",
        (game_system_id, bsdata_id, name, revision),
    )
    return conn.execute(
        "SELECT id FROM catalogues WHERE game_system_id = ? AND bsdata_id = ?", (game_system_id, bsdata_id)
    ).fetchone()["id"]


def prune_missing_catalogues(conn, game_system_id, kept_bsdata_ids):
    """Tar bort katalog-rader vars fraktion inte längre finns i BSData-repot.
    entries under dem faller bort via ON DELETE CASCADE, vilket i sin tur
    triggar samma entry_id-skydd som prune_missing_entries (SET NULL) för
    ev. collection_units-rader — datan skyddas alltså även i det här,
    ovanliga fallet (en hel fraktion tas bort ur BSData)."""
    rows = conn.execute("SELECT id, bsdata_id FROM catalogues WHERE game_system_id = ?", (game_system_id,)).fetchall()
    stale_ids = [r["id"] for r in rows if r["bsdata_id"] not in kept_bsdata_ids]
    if not stale_ids:
        return 0
    placeholders = ",".join("?" for _ in stale_ids)
    conn.execute(f"DELETE FROM catalogues WHERE id IN ({placeholders})", stale_ids)
    return len(stale_ids)


# ---------------------------------------------------------------------------
# entries
# ---------------------------------------------------------------------------

def upsert_entry(conn, catalogue_id, bsdata_id, name, role, keywords, points_table, profiles, raw_source_ref):
    conn.execute(
        """INSERT INTO entries (catalogue_id, bsdata_id, name, role, keywords, points_table, profiles, raw_source_ref)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(catalogue_id, bsdata_id) DO UPDATE SET
               name = excluded.name, role = excluded.role, keywords = excluded.keywords,
               points_table = excluded.points_table, profiles = excluded.profiles,
               raw_source_ref = excluded.raw_source_ref""",
        (catalogue_id, bsdata_id, name, role, json.dumps(keywords), json.dumps(points_table),
         json.dumps(profiles), raw_source_ref),
    )


def prune_missing_entries(conn, catalogue_id, kept_bsdata_ids):
    """Se kommentaren vid collection_units i init_db: innan en entry som
    försvunnit ur BSData raderas, kopieras dess namn/poäng in i
    name_override/points_override på ev. collection_units-rader som pekade
    på den, så att de inte blir namnlösa spökrader när entry_id sedan
    nollas av ON DELETE SET NULL."""
    rows = conn.execute("SELECT id, bsdata_id FROM entries WHERE catalogue_id = ?", (catalogue_id,)).fetchall()
    stale_ids = [r["id"] for r in rows if r["bsdata_id"] not in kept_bsdata_ids]
    if not stale_ids:
        return 0
    placeholders = ",".join("?" for _ in stale_ids)
    stale_entries = conn.execute(
        f"SELECT id, name, points_table FROM entries WHERE id IN ({placeholders})", stale_ids
    ).fetchall()
    for e in stale_entries:
        points_table = json.loads(e["points_table"] or "[]")
        fallback_points = points_table[0]["points"] if points_table else None
        conn.execute(
            """UPDATE collection_units
               SET name_override = COALESCE(name_override, ?),
                   points_override = COALESCE(points_override, ?)
               WHERE entry_id = ?""",
            (e["name"], fallback_points, e["id"]),
        )
    conn.execute(f"DELETE FROM entries WHERE id IN ({placeholders})", stale_ids)
    return len(stale_ids)


def search_entries(system_key, query, limit=50):
    conn = get_connection()
    sql = """
        SELECT entries.*, catalogues.name AS catalogue_name, game_systems.key AS system_key
        FROM entries
        JOIN catalogues ON catalogues.id = entries.catalogue_id
        JOIN game_systems ON game_systems.id = catalogues.game_system_id
        WHERE 1=1
    """
    params = []
    if system_key:
        sql += " AND game_systems.key = ?"
        params.append(system_key)
    if query:
        sql += " AND (entries.name LIKE ? OR catalogues.name LIKE ?)"
        like = f"%{query}%"
        params.extend([like, like])
    sql += " ORDER BY entries.name LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [_entry_row_to_dict(r) for r in rows]


def get_entry(entry_id):
    conn = get_connection()
    row = conn.execute(
        """SELECT entries.*, catalogues.name AS catalogue_name, game_systems.key AS system_key
           FROM entries
           JOIN catalogues ON catalogues.id = entries.catalogue_id
           JOIN game_systems ON game_systems.id = catalogues.game_system_id
           WHERE entries.id = ?""",
        (entry_id,),
    ).fetchone()
    conn.close()
    return _entry_row_to_dict(row) if row else None


def _entry_row_to_dict(row):
    d = dict(row)
    d["keywords"] = json.loads(d.get("keywords") or "[]")
    d["points_table"] = json.loads(d.get("points_table") or "[]")
    d["profiles"] = json.loads(d.get("profiles") or "[]")
    return d


# ---------------------------------------------------------------------------
# collection_units
# ---------------------------------------------------------------------------

def _points_for_count(points_table, count):
    """Slår upp poäng för ett givet antal i entry.points_table. Exakt
    träff först; annars den poster vars count ligger närmast (se
    "Kända begränsningar i poäng-parsingen" i CLAUDE.md — de flesta
    datasheets har bara EN poängpost i tabellen, så det här är i praktiken
    en enkel fallback för de fall Sivan äger fler/färre modeller än vad
    BSData-datasheetet är tryckt för)."""
    if not points_table:
        return None
    for row in points_table:
        if row.get("count") == count:
            return row.get("points")
    closest = min(points_table, key=lambda r: abs((r.get("count") or 0) - count))
    return closest.get("points")


def _unit_row_to_dict(row):
    d = dict(row)
    entry_id = d.get("entry_id")
    points_table = json.loads(d.pop("entry_points_table") or "[]") if "entry_points_table" in d else []
    if d.get("points_override") is not None:
        computed_points = d["points_override"]
    elif entry_id is not None:
        computed_points = _points_for_count(points_table, d["count"])
    else:
        computed_points = None
    d["computed_points"] = computed_points
    d["name"] = d.get("name_override") or d.get("entry_name")
    if "entry_keywords" in d:
        d["keywords"] = json.loads(d.pop("entry_keywords") or "[]")
    return d


_UNIT_SELECT = """
    SELECT
        collection_units.*,
        entries.name AS entry_name,
        entries.role AS role,
        entries.keywords AS entry_keywords,
        entries.points_table AS entry_points_table,
        catalogues.name AS catalogue_name,
        game_systems.key AS system_key,
        game_systems.name AS system_name
    FROM collection_units
    LEFT JOIN entries ON entries.id = collection_units.entry_id
    LEFT JOIN catalogues ON catalogues.id = entries.catalogue_id
    LEFT JOIN game_systems ON game_systems.id = catalogues.game_system_id
"""


def list_units(system_key=None, catalogue_name=None, status=None):
    conn = get_connection()
    sql = _UNIT_SELECT + " WHERE 1=1"
    params = []
    if system_key:
        sql += " AND game_systems.key = ?"
        params.append(system_key)
    if catalogue_name:
        sql += " AND catalogues.name = ?"
        params.append(catalogue_name)
    if status:
        sql += " AND collection_units.status = ?"
        params.append(status)
    sql += " ORDER BY collection_units.updated_at DESC"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [_unit_row_to_dict(r) for r in rows]


def get_unit(unit_id):
    conn = get_connection()
    row = conn.execute(_UNIT_SELECT + " WHERE collection_units.id = ?", (unit_id,)).fetchone()
    conn.close()
    return _unit_row_to_dict(row) if row else None


def create_unit(entry_id=None, name_override=None, count=1, points_override=None, status="unbuilt", photo_path=None):
    ts = now_iso()
    with WRITE_LOCK:
        conn = get_connection()
        cur = conn.execute(
            """INSERT INTO collection_units
               (entry_id, name_override, count, points_override, status, photo_path, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (entry_id, name_override, count, points_override, status, photo_path, ts, ts),
        )
        conn.commit()
        unit_id = cur.lastrowid
        conn.close()
    return get_unit(unit_id)


def update_unit(unit_id, **fields):
    if not fields:
        return get_unit(unit_id)
    fields["updated_at"] = now_iso()
    cols = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [unit_id]
    with WRITE_LOCK:
        conn = get_connection()
        conn.execute(f"UPDATE collection_units SET {cols} WHERE id = ?", values)
        conn.commit()
        conn.close()
    return get_unit(unit_id)


def delete_unit(unit_id):
    with WRITE_LOCK:
        conn = get_connection()
        conn.execute("DELETE FROM collection_units WHERE id = ?", (unit_id,))
        conn.commit()
        conn.close()


# ---------------------------------------------------------------------------
# collection_units — miniset.net-referensbild (Fas 4)
# ---------------------------------------------------------------------------

def set_unit_image(unit_id, image_url, image_source_url):
    """Sparar en lyckad matchning. image_checked_at sätts samtidigt så
    en efterföljande sidladdning inte matchar om enheten i onödan (se
    "Cacha resultatet" i fas4-warasset-miniset-bilder.md)."""
    return update_unit(unit_id, image_url=image_url, image_source_url=image_source_url, image_checked_at=now_iso())


def mark_unit_image_checked(unit_id):
    """Cachar ett NEGATIVT resultat (ingen träff hittad) — image_url förblir
    NULL, men image_checked_at sätts så vi inte försöker igen vid varje
    sidladdning. En manuell 'hämta om'-knapp ignorerar den här cachen och
    anropar match_unit på nytt ändå."""
    return update_unit(unit_id, image_checked_at=now_iso())


def clear_unit_image(unit_id):
    """Nollställer en felaktig automatisk matchning till 'aldrig kontrollerad'
    igen (inte bara 'kontrollerad, ingen träff') — så en framtida sparning av
    enheten kan trigga automatchningen på nytt. Rör aldrig photo_path (eget
    uppladdat foto), separat fält enligt produktbeslutet."""
    return update_unit(unit_id, image_url=None, image_source_url=None, image_checked_at=None)
