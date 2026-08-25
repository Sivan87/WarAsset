"""
WarAsset – Flask-app. HTML-routes (byggs ut i Fas 2, se CLAUDE.md) + start av
BSData-synken (både engångs- och daglig bakgrundssynk). JSON-API:et bor i
api.py, samma uppdelning som BrickRadar-Web.
"""
import os
import threading
import time

from dotenv import load_dotenv
from flask import Flask, render_template

import bsdata_sync
import database as db

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

app = Flask(__name__, static_folder="static", template_folder="templates")

# Hur ofta (i sekunder) den automatiska BSData-synken ska köras i
# bakgrunden. 86400 = en gång/dygn, samma intervall som BrickRadars
# schemalagda skrapning (se dess app.py:SCRAPE_INTERVAL_SECONDS).
SYNC_INTERVAL_SECONDS = int(os.environ.get("SYNC_INTERVAL_SECONDS", str(24 * 60 * 60)))


@app.route("/")
def index():
    """Huvudvyn (Fas 2). Server-renderar bara den statiska sidskalet
    (nav/toolbar/dialog-markup) — enhetslistan hämtas och all interaktivitet
    (sök/filter/sortering/CRUD) sköts av static/js/app.js mot /api/units och
    /api/entries/search, se CLAUDE.md."""
    return render_template("index.html")


def _initial_sync_loop():
    """Kör en första BSData-synk i bakgrunden vid appstart, så Flask-servern
    kan börja svara på requests direkt istället för att vänta flera minuter
    på att tre repon klonas första gången."""
    print("[app] Startar initial BSData-synk i bakgrunden...")
    bsdata_sync.run_full_sync()
    print("[app] Initial BSData-synk klar.")


def _daily_sync_loop():
    """Bakgrundstråd som kör om synken en gång per SYNC_INTERVAL_SECONDS
    (samma mönster som BrickRadars scheduler_loop i dess app.py)."""
    while True:
        time.sleep(SYNC_INTERVAL_SECONDS)
        print("[app] Kör schemalagd BSData-synk...")
        bsdata_sync.run_full_sync()


# Registrerar API-blueprinten. Görs efter att appen skapats (annars hade
# api.py inte kunnat importera `app`-modulen utan en cirkulär import), samma
# ordning som BrickRadar-Web/app.py.
import api  # noqa: E402
app.register_blueprint(api.api_bp)


if __name__ == "__main__":
    db.init_db()

    initial_sync_thread = threading.Thread(target=_initial_sync_loop, daemon=True)
    initial_sync_thread.start()

    daily_sync_thread = threading.Thread(target=_daily_sync_loop, daemon=True)
    daily_sync_thread.start()

    # host="0.0.0.0" gör servern nåbar från andra enheter på hemnätverket.
    # Port 5001 (inte 5000) för att inte krocka med BrickRadar på samma
    # Unraid-server, se docker-compose.yml.
    app.run(host="0.0.0.0", port=5001, debug=False)
