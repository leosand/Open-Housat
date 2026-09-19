"""Fond visuel haute resolution pour toute emprise lat/long — voie AFFICHAGE.
High-resolution visual basemap for any lat/long bbox — the DISPLAY track.

Constat (2026-09-15) : un carre tire au hasard de lat/long est ILLISIBLE si sa seule source
est Sentinel-2 (10 m/pixel, soit ~1-2 pixels par maison) — **aucune surresolution ne peut
compenser un facteur 15-30x**. Le probleme n'est pas le modele, c'est la SOURCE. La solution
perenne est donc d'ajouter une source a plus haute resolution, pas d'empiler des reseaux.

Cascade de fournisseurs, chacun portant sa licence et son attribution :

- `esri_world_imagery` : mosaique globale, sans cle, ~0,3-0,6 m en ville. Visualisation libre
  (attribution requise) mais **redistribution restreinte** -> ecran uniquement.

Le fournisseur est injectable (`fetcher`) -> testable sans reseau. La provenance (`provider`,
`licence`, `redistributable`) accompagne l'image : indispensable avant d'embarquer un fond
dans un rapport livre.
"""

from __future__ import annotations

import argparse
import io
import math
import sys
from collections.abc import Callable
from dataclasses import dataclass

import httpx

BBox = tuple[float, float, float, float]  # (minLon, minLat, maxLon, maxLat) EPSG:4326
Fetcher = Callable[[str], bytes]

USER_AGENT = "Housat-basemap/1.0"
TILE_SIZE = 256


@dataclass(frozen=True)
class BasemapImage:
    """Image de fond + provenance. `redistributable` conditionne son usage en rapport."""

    data: bytes
    bbox: BBox
    provider: str
    attribution: str
    licence: str
    redistributable: bool
    date_hint: str | None = None  # date de la source si connue (fond date), sinon None


@dataclass(frozen=True)
class BasemapProvider:
    name: str
    attribution: str
    licence: str
    redistributable: bool
    fetch: Callable[[BBox, int, str, Fetcher | None], bytes]
    date_hint: str | None = None


# --- Geometrie de tuiles XYZ (Web Mercator) — pur calcul, testable sans reseau ---

def lonlat_to_global_px(lon: float, lat: float, zoom: int, tile_size: int = TILE_SIZE) -> tuple[float, float]:
    """Pixel global (origine haut-gauche) d'un point lon/lat au zoom donne."""
    n = 2 ** zoom
    lat_r = math.radians(max(-85.05112878, min(85.05112878, lat)))
    px = (lon + 180.0) / 360.0 * n * tile_size
    py = (1.0 - math.asinh(math.tan(lat_r)) / math.pi) / 2.0 * n * tile_size
    return px, py


def lonlat_to_tile(lon: float, lat: float, zoom: int) -> tuple[int, int]:
    """Indice de tuile (x, y) contenant le point, borne a la grille [0, 2^zoom - 1]."""
    px, py = lonlat_to_global_px(lon, lat, zoom)
    hi = 2 ** zoom - 1
    return (max(0, min(hi, int(px // TILE_SIZE))), max(0, min(hi, int(py // TILE_SIZE))))


def tile_range(bbox: BBox, zoom: int) -> tuple[int, int, int, int]:
    """Plage de tuiles (x0, y0, x1, y1) couvrant la bbox au zoom donne."""
    x0, y0 = lonlat_to_tile(bbox[0], bbox[3], zoom)  # coin haut-gauche : minLon, maxLat
    x1, y1 = lonlat_to_tile(bbox[2], bbox[1], zoom)  # coin bas-droit  : maxLon, minLat
    return x0, y0, x1, y1


def choose_zoom(bbox: BBox, *, max_zoom: int = 17, max_tiles: int = 4) -> int:
    """Zoom le plus fin dont la couverture reste <= `max_tiles` par axe (borne requetes)."""
    b = validate_bbox(bbox)
    for z in range(max_zoom, -1, -1):
        x0, y0, x1, y1 = tile_range(b, z)
        if (x1 - x0 + 1) <= max_tiles and (y1 - y0 + 1) <= max_tiles:
            return z
    return 0


def stitch_xyz(
    bbox: BBox,
    size: int,
    url_template: str,
    *,
    fetcher: Fetcher | None = None,
    zoom: int | None = None,
    max_tiles: int = 4,
) -> bytes:
    """Assemble les tuiles XYZ couvrant `bbox` et recadre au cadre exact, puis redimensionne.

    `url_template` contient `{z}`, `{x}`, `{y}`. Renvoie un PNG (size x size). PIL est importe
    paresseusement. `fetcher` injectable -> aucun reseau en test.
    """
    from PIL import Image

    b = validate_bbox(bbox)
    z = choose_zoom(b, max_tiles=max_tiles) if zoom is None else zoom
    x0, y0, x1, y1 = tile_range(b, z)
    cols, rows = x1 - x0 + 1, y1 - y0 + 1
    canvas = Image.new("RGB", (cols * TILE_SIZE, rows * TILE_SIZE))
    fetch = fetcher or _http_get
    for ty in range(y0, y1 + 1):
        for tx in range(x0, x1 + 1):
            data = fetch(url_template.format(z=z, x=tx, y=ty))
            if not data:
                raise RuntimeError(f"tuile vide z={z} x={tx} y={ty}")
            canvas.paste(Image.open(io.BytesIO(data)).convert("RGB"), ((tx - x0) * TILE_SIZE, (ty - y0) * TILE_SIZE))

    gx0, gy0 = lonlat_to_global_px(b[0], b[3], z)
    gx1, gy1 = lonlat_to_global_px(b[2], b[1], z)
    left, top = int(gx0) - x0 * TILE_SIZE, int(gy0) - y0 * TILE_SIZE
    w, h = max(1, int(gx1) - int(gx0)), max(1, int(gy1) - int(gy0))
    crop = canvas.crop((left, top, left + w, top + h))
    out = io.BytesIO()
    crop.resize((size, size)).save(out, format="PNG", optimize=True)
    return out.getvalue()


# --- Fournisseurs ---

def _esri_url(bbox: BBox, size: int, fmt: str) -> str:
    minlon, minlat, maxlon, maxlat = bbox
    return (
        "https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/export"
        f"?bbox={minlon},{minlat},{maxlon},{maxlat}&bboxSR=4326&imageSR=4326"
        f"&size={size},{size}&format={fmt}&f=image"
    )


def _fetch_esri(bbox: BBox, size: int, fmt: str, fetcher: Fetcher | None) -> bytes:
    return (fetcher or _http_get)(_esri_url(bbox, size, fmt))


PROVIDERS: dict[str, BasemapProvider] = {
    "esri_world_imagery": BasemapProvider(
        name="esri_world_imagery",
        attribution="Esri, Maxar, Earthstar Geographics, and the GIS User Community",
        licence=(
            "Esri Master Agreement : visualisation autorisee (attribution requise), "
            "redistribution/cache restreints."
        ),
        redistributable=False,
        fetch=_fetch_esri,
    ),
}


# --- API publique ---

def validate_bbox(bbox: BBox) -> BBox:
    """Valide et normalise (float) une emprise EPSG:4326 ordonnee."""
    if len(bbox) != 4:
        raise ValueError("bbox doit etre (minLon, minLat, maxLon, maxLat)")
    minlon, minlat, maxlon, maxlat = (float(v) for v in bbox)
    if not (-180 <= minlon < maxlon <= 180):
        raise ValueError("longitudes invalides ou non ordonnees")
    if not (-90 <= minlat < maxlat <= 90):
        raise ValueError("latitudes invalides ou non ordonnees")
    return (minlon, minlat, maxlon, maxlat)


def _http_get(url: str) -> bytes:
    with httpx.Client(timeout=45.0, headers={"User-Agent": USER_AGENT}, follow_redirects=True) as c:
        r = c.get(url)
        r.raise_for_status()
        return r.content


def fetch_basemap(
    bbox: BBox,
    *,
    size: int = 1024,
    fmt: str = "jpg",
    provider: str = "esri_world_imagery",
    fetcher: Fetcher | None = None,
) -> BasemapImage:
    """Recupere un fond haute resolution pour `bbox` via la cascade de fournisseurs.

    `fetcher` est injectable (tests sans reseau). Leve si le fournisseur est inconnu, la bbox
    invalide, ou la reponse vide.
    """
    if provider not in PROVIDERS:
        raise ValueError(f"fournisseur inconnu: {provider!r} (dispo: {sorted(PROVIDERS)})")
    if size <= 0:
        raise ValueError("size doit etre > 0")
    b = validate_bbox(bbox)
    p = PROVIDERS[provider]
    data = p.fetch(b, size, fmt, fetcher)
    if not data:
        raise RuntimeError(f"fond vide renvoye par {provider}")
    return BasemapImage(data=data, bbox=b, provider=p.name, attribution=p.attribution,
                        licence=p.licence, redistributable=p.redistributable, date_hint=p.date_hint)


def _parse_bbox(text: str) -> BBox:
    parts = text.split(",")
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("bbox attendue: minLon,minLat,maxLon,maxLat")
    try:
        return (float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3]))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"bbox non numerique: {text!r}") from exc


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Fond visuel haute resolution pour une emprise lat/long")
    p.add_argument("--bbox", required=True, type=_parse_bbox, help="minLon,minLat,maxLon,maxLat")
    p.add_argument("--out", required=True, help="chemin du fichier image de sortie")
    p.add_argument("--size", type=int, default=1024, help="cote en pixels (defaut 1024)")
    p.add_argument("--format", dest="fmt", default="jpg", choices=("jpg", "png", "png32"))
    p.add_argument("--provider", default="esri_world_imagery", choices=sorted(PROVIDERS))
    args = p.parse_args(argv)
    img = fetch_basemap(args.bbox, size=args.size, fmt=args.fmt, provider=args.provider)
    with open(args.out, "wb") as fh:
        fh.write(img.data)
    print(f"{len(img.data)} octets -> {args.out}")
    print(f"source         : {img.provider}")
    print(f"attribution    : {img.attribution}")
    print(f"licence        : {img.licence}")
    print(f"redistribuable : {img.redistributable}")
    if img.date_hint:
        print(f"date           : {img.date_hint}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
