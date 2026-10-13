FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

COPY pipeline/requirements.txt pipeline/requirements.txt
COPY apps/api/requirements.txt apps/api/requirements.txt
# libexpat1 : requis A L'EXECUTION par les wheels manylinux de rasterio (GDAL) —
# absent de python:3.11-slim, il fait echouer `import rasterio` (libexpat.so.1).
# Le garde d'import ci-dessous rend ce type d'oubli impossible a livrer silencieusement.
# curl + ca-certificates : le harnais V&V `scripts/vv_live.sh` (assertions A1-A10) doit pouvoir
# s'executer DANS ce conteneur (`docker compose exec api bash /srv/scripts/vv_live.sh`). Mesure du
# 2026-09-19 : l'image ne fournissait que `sha256sum` et `python` -> `command -v curl` vide, donc
# l'etape 4 du runbook d'exploitation echouait en « command not found ». `ca-certificates` garantit
# la chaine TLS pour les sondes HTTPS depuis le conteneur.
RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r pipeline/requirements.txt -r apps/api/requirements.txt
RUN python -c "import rasterio, PIL, shapely, pyproj, numpy; print('runtime deps OK:', rasterio.__version__)"

COPY pipeline/ pipeline/
COPY apps/api/ api/

ENV PYTHONPATH=/srv/pipeline:/srv/api
EXPOSE 8000
RUN useradd -r -u 1000 housat
USER housat

CMD ["uvicorn", "main:app", "--app-dir", "api", "--host", "0.0.0.0", "--port", "8000"]
