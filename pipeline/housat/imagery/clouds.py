"""Masque nuage PAR PARCELLE (SCL Sentinel-2) — la couverture de la tuile est trompeuse.
Per-parcel cloud mask (Sentinel-2 SCL) — tile-level cloud cover is misleading.

Pourquoi : `eo:cloud_cover` mesure les nuages sur **toute la tuile** Sentinel-2 (~110 x 110 km).
Une parcelle de ~180 m peut etre **parfaitement degagee** alors que la tuile est annoncee a 95 % de
nuages — et inversement. Filtrer sur la tuile fait donc perdre la majorite des dates exploitables
en zone tropicale. On lit ici la couche **SCL** (Scene Classification, 20 m) et on ne compte que
les pixels de la PARCELLE.
"""

from __future__ import annotations

import numpy as np

# Classes SCL (L2A) qui masquent le sol : 0 NO_DATA, 1 SATURATED/DEFECTIVE, 3 CLOUD_SHADOW,
# 8/9 CLOUD (medium/high probability), 10 THIN_CIRRUS, 11 SNOW/ICE.
SCL_OBSCURED: frozenset[int] = frozenset({0, 1, 3, 8, 9, 10, 11})


def parcel_cloud_pct(scl: np.ndarray) -> float:
    """Pourcentage de pixels OBSCURCIS (nuage/ombre/cirrus/neige/non-valide) sur la parcelle.

    `nan` si le tableau est vide (aucune donnee) : l'appelant decide alors de ne pas bloquer la
    scene plutot que de la rejeter a tort.
    """
    a = np.asarray(scl)
    if a.size == 0:
        return float("nan")
    a32 = a.astype(np.int32)
    return 100.0 * int(np.isin(a32, list(SCL_OBSCURED)).sum()) / a32.size
