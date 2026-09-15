"""Tests unitaires du moteur de detection — donnees synthetiques, aucune IO reseau.
Unit tests for the detection engine on synthetic arrays.
"""

import numpy as np
from housat.detection.change import bsi, change_score, ndbi, ndvi
from housat.detection.milestones import Milestone, classify

SHAPE = (64, 64)


def _bands(nir: float = 0.5, red: float = 0.2, swir: float = 0.25) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(42)

    def noise(v: float) -> np.ndarray:
        return np.full(SHAPE, v, dtype=np.float32) + rng.normal(0, 0.005, SHAPE).astype(np.float32)

    return {
        "red": noise(red), "green": noise(0.3), "blue": noise(0.25),
        "nir": noise(nir), "swir16": noise(swir),
    }


def test_indices_ranges() -> None:
    b = _bands()
    for idx in (ndvi(b), ndbi(b), bsi(b)):
        assert idx.shape == SHAPE
        assert np.all(np.isfinite(idx))
        assert idx.min() >= -1.01 and idx.max() <= 1.01


def test_change_score_detects_construction_patch() -> None:
    prev = _bands(nir=0.55, swir=0.2)            # parcelle vegetalisee
    curr = _bands(nir=0.55, swir=0.2)
    patch = _bands(nir=0.15, red=0.35, swir=0.5)  # zone beton/terrassement : NIR baisse, SWIR monte
    for k in curr:
        curr[k][16:40, 16:40] = patch[k][16:40, 16:40]
    res = change_score(prev, curr)
    assert res.score > 0.02
    assert res.delta_ndbi_mean > 0
    assert res.delta_bsi_mean > 0


def test_change_score_stable_scene() -> None:
    prev = _bands()
    curr = _bands()
    res = change_score(prev, curr)
    assert res.score < 0.05


def test_milestone_progression() -> None:
    d0 = classify(built_ratio=0.01, delta_ndbi_mean=0.0, delta_bsi_mean=0.0,
                  change_score_value=0.01, sr_method="sen2sr")
    assert d0.milestone == Milestone.M0_TERRAIN

    d1 = classify(built_ratio=0.10, delta_ndbi_mean=0.01, delta_bsi_mean=0.05,
                  change_score_value=0.20, sr_method="sen2sr")
    assert d1.milestone == Milestone.M1_FONDATION

    d2 = classify(built_ratio=0.30, delta_ndbi_mean=0.03, delta_bsi_mean=0.0,
                  change_score_value=0.15, sr_method="sen2sr")
    assert d2.milestone == Milestone.M2_STRUCTURE


def test_low_confidence_flag_on_fallback() -> None:
    d = classify(built_ratio=0.30, delta_ndbi_mean=0.03, delta_bsi_mean=0.0,
                 change_score_value=0.15, sr_method="bicubic_fallback")
    assert d.low_confidence is True
    assert d.confidence < 0.8
