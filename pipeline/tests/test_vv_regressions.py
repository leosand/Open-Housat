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
    assert BAND_ORDER == ("blue", "green", "red", "nir", "swir16")
    assert list(BAND_ORDER) != sorted(BAND_ORDER)


def test_bicubic_preserve_range() -> None:
    bands = {k: np.full((4, 4), 0.3, dtype=np.float32) for k in BAND_ORDER}
    out, method = upscale_bands(bands, factor=2)
    assert method == "bicubic_fallback"
    assert out["red"].shape == (8, 8)
    assert abs(float(out["red"].mean()) - 0.3) < 0.02


def test_pivot_croissance_pure_sans_queue_negative() -> None:
    pv_t = _field(0.0, 1.0)
    div = _field(0.0, 0.20)
    r = obs.detect_pivot_pv(div, pv_t)
    assert r["mean_neg"] == 0.0
    assert r["dpra"] > 0.15
    assert r["qualifie"] is True
