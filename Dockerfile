FROM python:3.14-slim

WORKDIR /app

# git krävs av bsdata_sync.py, som klonar/uppdaterar BSData-repona vid
# körning (se docker-compose.yml-volymen och data/bsdata/).
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# database.py/bsdata_sync.py/api.py löser alla sina datavägar relativt /app
# (data/warasset.db, data/bsdata/<repo>, data/uploads) — mounta en volym på
# /app/data så databasen och de klonade BSData-repona överlever en
# omstart/ombyggnad av containern. Se docker-compose.yml.
EXPOSE 5001

# Flasks inbyggda dev-server (samma som `python app.py` utanför Docker) —
# ingen produktions-WSGI-server. Se motsvarande kommentar i BrickRadars
# Dockerfile för resonemanget kring detta (gäller likadant här: appen är
# enanvändare och serialiserar redan SQLite-skrivningar bakom ett
# processglobalt lås, se database.py:WRITE_LOCK).
CMD ["python", "app.py"]
