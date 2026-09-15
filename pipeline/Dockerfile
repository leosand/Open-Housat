FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

COPY requirements.txt .
# libexpat1 : meme exigence d'execution que l'API (wheel manylinux rasterio/GDAL).
RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.txt
RUN python -c "import rasterio, PIL, shapely, pyproj, numpy; print('runtime deps OK:', rasterio.__version__)"

COPY housat/ housat/
ENV PYTHONPATH=/srv

RUN useradd -r -u 1000 housat
USER housat

CMD ["python", "-m", "housat.worker", "--once"]
