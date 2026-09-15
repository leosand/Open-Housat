"""Acquisition Sentinel-2 L2A via catalogue STAC gratuit (Earth Search, AWS).
Sentinel-2 L2A fetching from the free Element84 Earth Search STAC API — 0$.
MVP-l1 : contexte HTTP partage, backfill multi-scenes, reprojection du polygone
EPSG:4326 -> CRS du raster (corrige le bug latent de v0.1).
"""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterator

import numpy as np
import rasterio
from pyproj import Transformer
from pystac_client import Client
from rasterio.mask import mask as rio_mask
from shapely.geometry import mapping, shape
from shapely.ops import transform as shp_transform

from housat.config import settings

COLLECTION = "sentinel-2-l2a"
BANDS: tuple[str, ...] = ("red", "green", "blue", "nir", "swir16")


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
    ) -> list[SceneMeta]:
        """Les `limit` scenes les moins nuageuses dans la fenetre, ordre chronologique."""
        max_cloud = settings.max_cloud_cover if max_cloud is None else max_cloud
        window_days = settings.search_window_days * 6 if window_days is None else window_days
        end = end or datetime.now(timezone.utc).date()
        start = end - timedelta(days=window_days)
        search = self.catalog.search(
            collections=[COLLECTION],
            intersects=polygon,
            datetime=f"{start.isoformat()}/{end.isoformat()}",
            query={"eo:cloud_cover": {"lt": max_cloud}},
            sortby=[{"field": "properties.eo:cloud_cover", "direction": "asc"}],
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
        return sorted(scenes, key=lambda s: s.acquired)  # t0 = plus ancienne


def _reproject_polygon(polygon: dict[str, Any], dst_crs: Any) -> dict[str, Any]:
    """Reprojete le polygone EPSG:4326 vers le CRS du raster (corrige le bug v0.1)."""
    tf = Transformer.from_crs("EPSG:4326", dst_crs, always_xy=True).transform
    return mapping(shp_transform(tf, shape(polygon)))


def fetch_bands(ctx: StacContext, polygon: dict[str, Any], scene: SceneMeta) -> dict[str, np.ndarray]:
    """Telecharge et clippe les bandes (reflectance 0-1) sur le polygone du chantier."""
    item = ctx.item(scene.item_id)
    out: dict[str, np.ndarray] = {}
    for band in BANDS:
        with rasterio.open(item.assets[band].href) as src:
            poly = _reproject_polygon(polygon, src.crs)
            clipped, _ = rio_mask(src, [poly], crop=True, filled=True, nodata=0)
            out[band] = clipped[0].astype(np.float32) / 10000.0
    return out
