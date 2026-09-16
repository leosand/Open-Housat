"""Acquisition Sentinel-2 L2A via catalogue STAC gratuit (Earth Search, AWS).
Sentinel-2 L2A fetching from the free Element84 Earth Search STAC API — 0$.
MVP-l1 : contexte HTTP partage, backfill multi-scenes, reprojection du polygone
EPSG:4326 -> CRS du raster (corrige le bug latent de v0.1).
V&V 2026-09-15 : alignement des bandes hetero-resolution — swir16 (20 m) est
reechantillonnee sur la grille 10 m de red avant les indices (sinon broadcast crash).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

import numpy as np
import rasterio
from pyproj import Transformer
from pystac_client import Client
from rasterio.mask import mask as rio_mask
from shapely.geometry import mapping, shape
from shapely.ops import transform as shp_transform

from housat import observations as obs
from housat.config import settings

COLLECTION = "sentinel-2-l2a"
BANDS: tuple[str, ...] = ("red", "green", "blue", "nir", "swir16")
# Couche de classification de scene (20 m, CATEGORIELLE) : sert au masque nuage PAR PARCELLE.
SCL_ASSET = "scl"
# Cote minimal (m) du voisinage lu dans SCL pour juger les nuages : sous ce cote, une emprise de
# maison ne couvre meme pas un pixel de 20 m et le test nuage devient un tirage au sort
# (cf. `_scl_window`). La MESURE, elle, reste sur l'emprise exacte.
SCL_MIN_SPAN_M = 60.0


@dataclass
class SceneMeta:
    item_id: str
    acquired: date
    cloud_cover: float


class StacContext:
    """Contexte STAC reutilisable (evite de rouvrir le catalogue par scene)."""

    def __init__(self, url: str | None = None) -> None:
        self.url = url or settings.stac_api_url
        self.catalog = Client.open(self.url)
        self._items: dict[str, Any] = {}

    def item(self, item_id: str) -> Any:
        if item_id not in self._items:
            self._items[item_id] = next(
                iter(self.catalog.search(ids=[item_id], collections=[COLLECTION]).items())
            )
        return self._items[item_id]

    def search_scenes(
        self,
        polygon: dict[str, Any],
        *,
        max_cloud: float | None = None,
        window_days: int | None = None,
        limit: int = 10,
        end: date | None = None,
        mode: str = "archive",
    ) -> list[SceneMeta]:
        """Recherche STAC.

        mode='archive' : les `limit` scenes les moins nuageuses, rendues en ordre chrono (backfill).
        mode='latest'  : la scene la plus recente sous le seuil de nuages (verification ponctuelle).
        """
        max_cloud = settings.tile_cloud_prefilter if max_cloud is None else max_cloud
        if window_days is None:
            window_days = settings.search_window_days * 6 if mode == "archive" else settings.search_window_days
        end = end or datetime.now(timezone.utc).date()
        start = end - timedelta(days=window_days)
        sortby = ([{"field": "properties.datetime", "direction": "desc"}] if mode == "latest"
                  else [{"field": "properties.eo:cloud_cover", "direction": "asc"}])
        search = self.catalog.search(
            collections=[COLLECTION],
            intersects=polygon,
            datetime=f"{start.isoformat()}/{end.isoformat()}",
            query={"eo:cloud_cover": {"lt": max_cloud}},
            sortby=sortby,
            limit=limit,
        )
        scenes = [
            SceneMeta(
                item_id=it.id,
                acquired=datetime.fromisoformat(it.properties["datetime"].replace("Z", "+00:00")).date(),
                cloud_cover=float(it.properties.get("eo:cloud_cover", 100.0)),
            )
            for it in search.items()
        ]
        if mode == "latest":
            return sorted(scenes, key=lambda s: s.acquired, reverse=True)
        return sorted(scenes, key=lambda s: s.acquired)


def _reproject_polygon(polygon: dict[str, Any], dst_crs: Any) -> dict[str, Any]:
    """Reprojete le polygone EPSG:4326 vers le CRS du raster (corrige le bug v0.1)."""
    tf = Transformer.from_crs("EPSG:4326", dst_crs, always_xy=True).transform
    return mapping(shp_transform(tf, shape(polygon)))


def fetch_bands(ctx: StacContext, polygon: dict[str, Any], scene: SceneMeta) -> dict[str, np.ndarray]:
    """Telecharge et clippe les bandes (reflectance 0-1) sur le polygone du chantier.
    Aligne les bandes a resolutions differentes (swir16 20 m) sur la grille 10 m de red."""
    item = ctx.item(scene.item_id)
    out: dict[str, np.ndarray] = {}
    for band in BANDS:
        with rasterio.open(item.assets[band].href) as src:
            poly = _reproject_polygon(polygon, src.crs)
            clipped, _ = rio_mask(src, [poly], crop=True, filled=True, nodata=0)
            out[band] = clipped[0].astype(np.float32) / 10000.0
    ref = out.get("red")
    if ref is not None:
        for band, arr in out.items():
            if arr.shape != ref.shape:
                out[band] = obs.match_shape({band: arr}, ref.shape)[band]
    return out


def _scl_window(geom: Any, span_m: float) -> Any:
    """Etend l'emprise analysee a `span_m` de cote MINIMUM, centree dessus.

    SCL est a **20 m** : pour une emprise de maison (10-20 m), `rio_mask` couvre au mieux UN pixel
    (et souvent zero centre de pixel) — le remplissage `nodata=0` etait alors compte comme
    « obscurci » et **toutes** les scenes etaient rejetees a 100 % de nuages (mesure du 2026-09-16 sur
    un chantier de 16 x 8 m : 20 scenes refusees d'affilee, aucune observation). On juge donc les
    nuages sur un **voisinage** d'au moins 60 m, tout en mesurant le changement sur l'emprise exacte.
    """
    from shapely.geometry import box

    minx, miny, maxx, maxy = geom.bounds
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    half = max(span_m / 2, (maxx - minx) / 2, (maxy - miny) / 2)
    return box(cx - half, cy - half, cx + half, cy + half)


def fetch_scl(ctx: StacContext, polygon: dict[str, Any], scene: SceneMeta) -> np.ndarray | None:
    """Classes SCL (20 m) des pixels REELLEMENT couverts par l'emprise (valeurs valides, 1-D).

    Deux pieges corriges ici (mesure du 2026-09-16) :
    - `rio_mask(filled=False)` : les pixels **hors** emprise ne sont plus comptes. Avec
      `filled=True, nodata=0`, le remplissage etait compte comme « obscurci » et gonflait le taux
      (43,8 % la ou la part reelle est plus faible) ;
    - `_scl_window` : a 20 m par pixel, une emprise de maison ne couvre aucun centre de pixel — on
      lit un voisinage de 60 m au minimum, sans quoi le test nuage est un tirage au sort.

    Reechantillonnage **PLUS PROCHE VOISIN** obligatoire : une couche CATEGORIELLE ne s'interpole pas
    (melanger 8 « nuage » et 4 « vegetation » produirait une classe inexistante).
    Renvoie `None` si l'asset est absent — l'appelant applique alors son repli documente.
    """
    item = ctx.item(scene.item_id)
    asset = item.assets.get(SCL_ASSET)
    if asset is None:
        return None
    with rasterio.open(asset.href) as src:
        geom = shape(_reproject_polygon(polygon, src.crs))
        clipped, _ = rio_mask(src, [mapping(_scl_window(geom, SCL_MIN_SPAN_M))],
                              crop=True, filled=False)
        return np.asarray(clipped[0].compressed(), dtype=np.uint8)
