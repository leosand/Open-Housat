FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

COPY pipeline/requirements.txt pipeline/requirements.txt
COPY apps/api/requirements.txt apps/api/requirements.txt
# libexpat1 : requis A L'EXECUTION par les wheels manylinux de rasterio (GDAL) —
# absent de python:3.11-slim, il fait echouer `import rasterio` (libexpat.so.1).
# Le garde d'import ci-dessous rend ce type d'oubli impossible a livrer silencieusement.
RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 \
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
