"""
JSON REST-API för WarAsset, som en egen Flask Blueprint under prefix /api —
samma grundmönster som BrickRadar-Web/api.py.

Ingen X-API-Key-auth här (till skillnad från BrickRadar): WarAsset har ingen
separat mobilapp och ska vara helt öppet på hemnätverket enligt
produktbeslutet i kickoff-dokumentet (fas1-warasset-grunddata-bsdata.md).

Alla fel returneras som JSON ({"error": "..."}) med rätt statuskod, aldrig
en HTML-felsida — se _api_aware_404/_api_aware_500.
"""
import os
import threading
import uuid

from flask import Blueprint, Response, abort, jsonify, request, send_from_directory

import bsdata_sync
import database as db

api_bp = Blueprint("api", __name__, url_prefix="/api")

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "uploads")
_ALLOWED_UPLOAD_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

# Skyddar mot att flera samtidiga POST /api/sync-anrop startar parallella
# git clone/pull mot samma mapp (kan korrumpera en pågående klon). En synk
# tar typiskt allt från några sekunder (git pull, inga ändringar) till några
# minuter (första klonen av alla tre repon) — därför körs den i en
# bakgrundstråd och den här flaggan används för att svara 409 på ett
# överlappande anrop istället för att låta dem krocka.
_sync_lock = threading.Lock()
_sync_running = False


@api_bp.app_errorhandler(404)
def _api_aware_404(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Endpoint hittades inte"}), 404
    return e


@api_bp.app_errorhandler(500)
def _api_aware_500(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Internt serverfel"}), 500
    return e


# ---------------------------------------------------------------------------
# Spelsystem / synk
# ---------------------------------------------------------------------------

@api_bp.route("/game-systems", methods=["GET"])
def api_list_game_systems():
    return jsonify(db.list_game_systems())


@api_bp.route("/sync", methods=["POST"])
def api_trigger_sync():
    """Kör om BSData-synken på begäran (uppgift 3/6 i kickoff-dokumentet).
    Körs i en bakgrundstråd så anropet inte hänger kvar i flera minuter vid
    en första klon — svarar direkt med {"status": "started"}. Status för
    resultatet syns i GET /api/game-systems (last_synced_at) efteråt, samt
    i serverloggen."""
    global _sync_running

    with _sync_lock:
        if _sync_running:
            return jsonify({"error": "En synk körs redan"}), 409
        _sync_running = True

    def _run():
        global _sync_running
        try:
            bsdata_sync.run_full_sync()
        finally:
            with _sync_lock:
                _sync_running = False

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"status": "started"}), 202


# ---------------------------------------------------------------------------
# Sök-API mot BSData-katalogen (entries)
# ---------------------------------------------------------------------------

@api_bp.route("/entries/search", methods=["GET"])
def api_search_entries():
    system_key = request.args.get("system")
    query = request.args.get("q", "").strip()
    if system_key and system_key not in ("40k", "kill_team", "aos"):
        return jsonify({"error": "system måste vara 40k, kill_team eller aos"}), 400
    results = db.search_entries(system_key, query)
    return jsonify(results)


@api_bp.route("/entries/<int:entry_id>", methods=["GET"])
def api_get_entry(entry_id):
    entry = db.get_entry(entry_id)
    if not entry:
        return jsonify({"error": "Entry hittades inte"}), 404
    return jsonify(entry)


# ---------------------------------------------------------------------------
# CRUD för collection_units (Sivans faktiska samling)
# ---------------------------------------------------------------------------

VALID_STATUSES = set(db.STATUSES)


@api_bp.route("/units", methods=["GET"])
def api_list_units():
    system_key = request.args.get("system")
    catalogue_name = request.args.get("catalogue") or request.args.get("faction")
    status = request.args.get("status")
    if status and status not in VALID_STATUSES:
        return jsonify({"error": f"status måste vara en av {sorted(VALID_STATUSES)}"}), 400
    units = db.list_units(system_key=system_key, catalogue_name=catalogue_name, status=status)
    return jsonify(units)


@api_bp.route("/units/<int:unit_id>", methods=["GET"])
def api_get_unit(unit_id):
    unit = db.get_unit(unit_id)
    if not unit:
        return jsonify({"error": "Enheten hittades inte"}), 404
    return jsonify(unit)


def _validate_count(value):
    try:
        count = int(value)
    except (TypeError, ValueError):
        return None
    return count if count > 0 else None


@api_bp.route("/units", methods=["POST"])
def api_create_unit():
    data = request.get_json(silent=True) or {}

    entry_id = data.get("entry_id")
    name_override = (data.get("name_override") or "").strip() or None
    if not entry_id and not name_override:
        return jsonify({"error": "entry_id eller name_override krävs"}), 400
    if entry_id is not None and not db.get_entry(entry_id):
        return jsonify({"error": "entry_id pekar på en okänd BSData-post"}), 404

    count = _validate_count(data.get("count", 1))
    if count is None:
        return jsonify({"error": "count måste vara ett positivt heltal"}), 400

    status = data.get("status", "unbuilt")
    if status not in VALID_STATUSES:
        return jsonify({"error": f"status måste vara en av {sorted(VALID_STATUSES)}"}), 400

    points_override = data.get("points_override")
    if points_override is not None:
        try:
            points_override = int(points_override)
        except (TypeError, ValueError):
            return jsonify({"error": "points_override måste vara ett heltal"}), 400

    unit = db.create_unit(
        entry_id=entry_id,
        name_override=name_override,
        count=count,
        points_override=points_override,
        status=status,
        photo_path=data.get("photo_path"),
    )
    return jsonify(unit), 201


@api_bp.route("/units/<int:unit_id>", methods=["PUT"])
def api_update_unit(unit_id):
    if not db.get_unit(unit_id):
        return jsonify({"error": "Enheten hittades inte"}), 404

    data = request.get_json(silent=True) or {}
    fields = {}

    if "entry_id" in data:
        entry_id = data["entry_id"]
        if entry_id is not None and not db.get_entry(entry_id):
            return jsonify({"error": "entry_id pekar på en okänd BSData-post"}), 404
        fields["entry_id"] = entry_id

    if "name_override" in data:
        fields["name_override"] = (data["name_override"] or "").strip() or None

    if "count" in data:
        count = _validate_count(data["count"])
        if count is None:
            return jsonify({"error": "count måste vara ett positivt heltal"}), 400
        fields["count"] = count

    if "points_override" in data:
        points_override = data["points_override"]
        if points_override is not None:
            try:
                points_override = int(points_override)
            except (TypeError, ValueError):
                return jsonify({"error": "points_override måste vara ett heltal"}), 400
        fields["points_override"] = points_override

    if "status" in data:
        if data["status"] not in VALID_STATUSES:
            return jsonify({"error": f"status måste vara en av {sorted(VALID_STATUSES)}"}), 400
        fields["status"] = data["status"]

    if "photo_path" in data:
        fields["photo_path"] = data["photo_path"]

    if not fields:
        return jsonify({"error": "Inga fält att uppdatera skickades"}), 400
    if "entry_id" in fields and fields["entry_id"] is None and "name_override" not in fields:
        current = db.get_unit(unit_id)
        if not current.get("name_override"):
            return jsonify({"error": "Kan inte nolla entry_id utan att sätta name_override"}), 400

    unit = db.update_unit(unit_id, **fields)
    return jsonify(unit)


@api_bp.route("/units/<int:unit_id>", methods=["DELETE"])
def api_delete_unit(unit_id):
    if not db.get_unit(unit_id):
        return jsonify({"error": "Enheten hittades inte"}), 404
    db.delete_unit(unit_id)
    return "", 204


# ---------------------------------------------------------------------------
# Foto av en samlingsenhet (motsvarar BrickRadars build-photo, se dess api.py)
# ---------------------------------------------------------------------------

@api_bp.route("/units/<int:unit_id>/photo", methods=["POST"])
def api_upload_unit_photo(unit_id):
    unit = db.get_unit(unit_id)
    if not unit:
        return jsonify({"error": "Enheten hittades inte"}), 404

    file = request.files.get("photo")
    if not file or not file.filename:
        return jsonify({"error": "Ingen bildfil skickades"}), 400

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in _ALLOWED_UPLOAD_EXTENSIONS:
        return jsonify({"error": "Filtypen stöds inte (jpg/png/webp/gif)"}), 400

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    old_photo = unit.get("photo_path")
    if old_photo and old_photo.startswith("/uploads/"):
        old_path = os.path.join(UPLOAD_DIR, old_photo[len("/uploads/"):])
        if os.path.exists(old_path):
            os.remove(old_path)

    filename = f"unit-{unit_id}-{uuid.uuid4().hex}{ext}"
    file.save(os.path.join(UPLOAD_DIR, filename))

    updated = db.update_unit(unit_id, photo_path=f"/uploads/{filename}")
    return jsonify(updated)


@api_bp.route("/units/<int:unit_id>/photo", methods=["GET"])
def api_get_unit_photo(unit_id):
    unit = db.get_unit(unit_id)
    if not unit or not unit.get("photo_path"):
        abort(404)
    photo_path = unit["photo_path"]
    if not photo_path.startswith("/uploads/"):
        abort(404)
    return send_from_directory(UPLOAD_DIR, photo_path[len("/uploads/"):])
