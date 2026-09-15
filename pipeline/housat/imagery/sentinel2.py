"""Acquisition Sentinel-2 L2A via catalogue STAC gratuit (Earth Search, AWS).
Sentinel-2 L2A fetching from the free Element84 Earth Search STAC API — 0$ input,
c'est le levier economique central (cf. docs/competitive-analysis.md).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

import numpy as np
import rasterio
from pystac_client import Client
from rasterio.mask import mask as rio_mask

from housat.config import settings

COLLECTION = "sentinel-2-l2a"
# Bandes 10/20 m necessaires aux indices : rouge, vert, bleu, NIR, SWIR1
BANDS: tuple[str, ...] = ("red", "green", "blue", "nir", "swir16")


@dataclass
class Scene:
    item_id: str
    acquired: date
    cloud_cover: float


def search_best_scene(
    polygon: dict[str, Any],
    *,
    max_cloud: float | None = None,
    window_days: int | None = None,
    end: date | None = None,
) -> Scene | None:
    """Scene la moins nuageuse sur le polygone dans la fenetre temporelle.
    Least-cloudy Sentinel-2 scene intersecting the site polygon.
    """
    max_cloud = settings.max_cloud_cover if max_cloud is None else max_cloud
    window_days = settings.search_window_days if window_days is None else window_days
    end = end or datetime.now(timezone.utc).date()
    start = end - timedelta(days=window_days)

    catalog = Client.open(settings.stac_api_url)
    search = catalog.search(
        collections=[COLLECTION],
        intersects=polygon,
        datetime=f"{start.isoformat()}/{end.isoformat()}",
        query={"eo:cloud_cover": {"lt": max_cloud}},
        sortby=[{"field": "properties.eo:cloud_cover", "direction": "asc"}],
        max_items=1,
    )
    item = next(iter(search.items()), None)
    if item is None:
        return None
    return Scene(
        item_id=item.id,
        acquired=datetime.fromisoformat(item.properties["datetime"].replace("Z", "+00:00")).date(),
        cloud_cover=float(item.properties.get("eo:cloud_cover", 100.0)),
    )


def fetch_bands(polygon: dict[str, Any], scene: Scene) -> dict[str, np.ndarray]:
    """Telecharge et clippe les bandes sur le polygone du chantier (<= ~1 km2).
    Download + clip bands to the site polygon. Jamais de tuilage multi-scene en v0.1 (dette assumee).
    """
    catalog = Client.open(settings.stac_api_url)
    item = next(iter(catalog.search(ids=[scene.item_id], collections=[COLLECTION]).items()))
    out: dict[str, np.ndarray] = {}
    for band in BANDS:
        href = item.assets[band].href
        with rasterio.open(href) as src:
            clipped, _ = rio_mask(src, [polygon], crop=True, filled=True, nodata=0)
            out[band] = clipped[0].astype(np.float32) / 10000.0  # reflectance 0-1
    return out
