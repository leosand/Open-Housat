"""Regressions V&V transverses — synthetique, sans IO reseau."""

import numpy as np
from housat import observations as obs
from housat.imagery.super_resolution import BAND_ORDER, upscale_bands

SHAPE = (64, 64)


def _field(value: float, patch_value: float | None = None) -> np.ndarray:
    a = np.full(SHAPE, value, dtype=np.float32)
    if patch_value is not None:
        a[16:40, 16:40] = patch_value
    return a


def test_band_order_physique_sentinel2() -> None:
    """L'ordre alphabetique inverserait nir et red — tenseur SEN2SR incoherent."""
    assert BAND_ORDER == ("blue", "green", "red", "nir", "swir16")
    assert list(BAND_ORDER) != sorted(BAND_ORDER)


def test_bicubic_preserve_range() -> None:
    bands = {k: np.full((4, 4), 0.3, dtype=np.float32) for k in BAND_ORDER}
    out, method = upscale_bands(bands, factor=2)
    assert method == "bicubic_fallback"
    assert out["red"].shape == (8, 8)
    assert abs(float(out["red"].mean()) - 0.3) < 0.02


def test_bicubic_bands_hetero_resolution_alignees() -> None:
    """swir16 (20 m) arrive a demi-resolution vs red (10 m) : la SR doit produire
    une grille commune sinon NDBI/BSI crashent (broadcast) sur donnees reelles."""
    bands = {"blue": np.full((8, 8), 0.2, dtype=np.float32),
             "green": np.full((8, 8), 0.25, dtype=np.float32),
             "red": np.full((8, 8), 0.3, dtype=np.float32),
             "nir": np.full((8, 8), 0.5, dtype=np.float32),
             "swir16": np.full((4, 4), 0.35, dtype=np.float32)}  # 20 m : demi-grille
    out, method = upscale_bands(bands, factor=2)
    assert method == "bicubic_fallback"
    shapes = {v.shape for v in out.values()}
    assert len(shapes) == 1 and shapes.pop() == (16, 16)
    assert abs(float(out["swir16"].mean()) - 0.35) < 0.03


def test_pivot_croissance_pure_sans_queue_negative() -> None:
    """Construction franche (div >= 0 partout) : queue negative nulle = negligeable."""
    pv_t = _field(0.0, 1.0)
    div = _field(0.0, 0.20)
    r = obs.detect_pivot_pv(div, pv_t)
    assert r["mean_neg"] == 0.0
    assert r["dpra"] > 0.15
    assert r["qualifie"] is True
