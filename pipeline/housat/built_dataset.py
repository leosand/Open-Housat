"""Dataset bati : scene Sentinel-2 LR + masque bati rasterise depuis OSM (ODbL).

Repond aux objectifs 2 (contours de batiment) et 3 (dalle vs toit) en fournissant LE socle commun :
une grille unique ou l'entree (LR 10 m) et la supervision (empreintes OSM) sont alignees.

Pourquoi OSM et pas Open Buildings : mesure du 2026-09-16 sur Douala — **65 empreintes sur l'ilot de
178 m** (49,8 % de surface batie), **136 070 sur 10 km**, **286 542 sur la metropole**, sous licence
**ODbL** (redistribuable avec attribution). Un premier releve avait annonce 0 batiment : c'etait une
reponse VIDE d'Overpass sature (cf. `fetch_buildings`, qui reessaie desormais).

Objectif 3 : la meme grille sert a empiler une **trajectoire temporelle** (plusieurs dates) — c'est
la trajectoire, et non une image isolee, qui distingue une **dalle** (BSI/NDBI hauts, NDVI bas,
stables) d'un **toit pose** (saut de reflectance visible + plateau NDBI).
"""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np
import rasterio
from rasterio.features import rasterize
from shapely.geometry import Polygon

BBox = tuple[float, float, float, float]


def built_mask(polys: list[list[tuple[float, float]]], bbox: BBox,
               shape: tuple[int, int]) -> np.ndarray:
    """Masque bati binaire (1 = empreinte OSM) sur une grille `shape` (lignes, colonnes).

    `all_touched=False` : un pixel n'est bati que si **son centre** tombe dans une empreinte — regle
    conservatrice et reproductible, coherente avec la mesure de surface (`footprint_stats`).
    """
    minlon, minlat, maxlon, maxlat = bbox
    transform = rasterio.transform.from_bounds(minlon, minlat, maxlon, maxlat, shape[1], shape[0])
    geoms = [g for g in (Polygon(p) for p in polys) if g.is_valid and not g.is_empty]
    if not geoms:
        return np.zeros(shape, dtype=np.uint8)
    return rasterize([(g, 1) for g in geoms], out_shape=shape, transform=transform,
                     fill=0, all_touched=False, dtype=np.uint8)


def tiles(shape: tuple[int, int], size: int = 64,
          overlap: int = 0) -> Iterator[tuple[int, int, int, int]]:
    """Fenetres (r0, r1, c0, c1) couvrant `shape` **en entier**, avec recouvrement optionnel.

    La derniere fenetre de chaque axe est **aligee sur le bord** : sans cela une emprise non multiple
    de `size` perd une bande entiere (110 px, patches 64, pas 32 : 0-96 couverts, 14 px dehors) —
    attrape par le test de tuilage.
    """
    if size <= 0 or overlap >= size:
        raise ValueError("size > overlap >= 0 requis")
    step = size - overlap

    def debuts(n: int) -> list[int]:
        if n <= size:
            return [0]
        out = list(range(0, n - size, step)) or [0]
        if out[-1] + size < n:
            out.append(n - size)
        return out

    for r0 in debuts(shape[0]):
        for c0 in debuts(shape[1]):
            yield r0, min(r0 + size, shape[0]), c0, min(c0 + size, shape[1])


def built_fraction(mask: np.ndarray) -> float:
    """Part de pixels batis (0 si le masque est vide) — controle de coherence vecteur/raster."""
    return float(mask.mean()) if mask.size else 0.0
