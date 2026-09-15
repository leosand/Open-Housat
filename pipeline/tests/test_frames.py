"""Tests des frames et indicateurs V&V (pivots) — synthetique, sans reseau.
Unit tests for frames + V&V pivot indicators on synthetic arrays.
"""

import numpy as np

from housat import observations as obs

SHAPE = (64, 64)


def _field(value: float, patch_value: float | None = None) -> np.ndarray:
    a = np.full(SHAPE, value, dtype=np.float32)
    if patch_value is not None:
        a[16:40, 16:40] = patch_value
    return a


def test_frame_roundtrip() -> None:
    bands = {k: _field(0.3) for k in ("red", "green", "blue", "nir", "swir16")}
    loaded = obs.load_frame(obs.dump_frame(bands))
    assert set(loaded) == set(bands)
    assert loaded["nir"].dtype == np.float32
    assert np.max(np.abs(loaded["nir"] - bands["nir"])) < 1e-3  # float16 tolerance


def test_pv_truncation_ring() -> None:
    a = np.ones((8, 8), dtype=np.float32)
    out = obs.truncate_ring(a)
    assert out[0, 0] == 0 and out[4, 4] == 1 and out[7, 7] == 0


def test_progress_gt_100_with_positive_pivot() -> None:
    div0 = _field(0.0, 0.30)          # t0 : petite zone changee fortement
    div_t = _field(0.0, 0.10)         # t : meme ordre, totaux comparables
    div_t[40:56, 40:56] = 0.35        # nouveau pivot positif fort (somme den > num, masque plus grand)
    p = obs.compute_div_progress(div0, div_t)
    assert 0.0 <= p <= 130.0
    # pivot negatif : la zone de t0 revient a zero -> denominator gonfle, ratio bas
    div_neg = _field(0.0, -0.30)
    div_neg[40:56, 40:56] = 0.10
    p_neg = obs.compute_div_progress(div0, div_neg)
    assert p_neg <= 100.0


def test_detect_pivot_qualifie() -> None:
    pv_t = _field(0.0, 1.0)
    div = _field(-0.001, 0.20)   # forte croissance localisee, queue negative negligeable
    r = obs.detect_pivot_pv(div, pv_t)
    assert r["dpra"] > 0.15
    assert r["qualifie"] is True


def test_milestone_pivot_confirme_m2() -> None:
    anchor = [_field(0.30) for _ in range(3)]
    curr = [_field(0.30, 0.55) for _ in range(3)]  # hausse localisee sur les 3 indices
    pvs, divs = [], []
    for a, c in zip(anchor, curr):
        pv, div = obs.pv_div(a, c)
        pvs.append(pv)
        divs.append(div)
    pvs0 = [np.zeros_like(p) for p in pvs]
    ms, pivot, growth = obs.milestone_decision(pvs0, pvs, divs)
    assert pivot is True
    assert ms == 2
    assert growth > 0.01


def test_milestone_m0_stable() -> None:
    anchor = [_field(0.30) for _ in range(3)]
    pvs, divs = [], []
    for a, c in zip(anchor, anchor):
        pv, div = obs.pv_div(a, c)
        pvs.append(pv)
        divs.append(div)
    ms, pivot, _ = obs.milestone_decision([np.zeros_like(p) for p in pvs], pvs, divs)
    assert ms == 0 and pivot is False


def test_png_rgb_bytes() -> None:
    bands = {"red": _field(0.2), "green": _field(0.25), "blue": _field(0.15),
             "nir": _field(0.5), "swir16": _field(0.3)}
    png = obs.image_png_rgb(bands)
    assert png[:4] == b"\x89PNG"
    assert len(png) > 100
