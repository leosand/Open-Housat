"""Tests des frames et indicateurs V&V (pivots) — synthetique, sans reseau.
Unit tests for frames + V&V pivot indicators on synthetic arrays.
"""

import numpy as np
from housat import observations as obs
from housat.detection import change
from housat.detection.milestones import Milestone, classify, hold_milestone

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
    assert np.max(np.abs(loaded["nir"] - bands["nir"])) < 1e-3


def test_match_shape_aligns_grids() -> None:
    # fenetres de clip decalees (bug latent corrige) : formes differentes -> alignees sur l'ancre
    bands = {k: np.full((64, 64), 0.3, dtype=np.float32) for k in ("red", "nir")}
    bands["red"] = np.full((63, 65), 0.3, dtype=np.float32)  # derive de fenetre sub-pixel
    out = obs.match_shape(bands, (64, 64))
    assert all(v.shape == (64, 64) for v in out.values())
    assert abs(float(out["red"].mean()) - 0.3) < 1e-3


def test_pv_truncation_ring() -> None:
    a = np.ones((8, 8), dtype=np.float32)
    out = obs.truncate_ring(a)
    assert out[0, 0] == 0 and out[4, 4] == 1 and out[7, 7] == 0


def test_progress_gt_100_with_positive_pivot() -> None:
    div0 = _field(0.0, 0.30)
    div_t = _field(0.0, 0.10)
    div_t[40:56, 40:56] = 0.35
    p = obs.compute_div_progress(div0, div_t)
    assert 0.0 <= p <= 130.0
    div_neg = _field(0.0, -0.30)
    div_neg[40:56, 40:56] = 0.10
    p_neg = obs.compute_div_progress(div0, div_neg)
    assert p_neg <= 100.0


def test_detect_pivot_qualifie() -> None:
    pv_t = _field(0.0, 1.0)
    div = _field(-0.001, 0.20)
    r = obs.detect_pivot_pv(div, pv_t)
    assert r["dpra"] > 0.15
    assert r["qualifie"] is True


def _scene(veg: float, soil: float, built: float) -> dict[str, np.ndarray]:
    """Bandes synthetiques melangeant 3 materiaux : vegetal, sol nu, bati (red/blue/nir/swir16)."""
    r = np.random.default_rng(3).random(SHAPE)
    m_veg = r < veg
    m_soil = (r >= veg) & (r < veg + soil)
    out: dict[str, np.ndarray] = {}
    for k, (v, s, b) in {"red": (0.05, 0.22, 0.30), "blue": (0.03, 0.18, 0.28),
                         "nir": (0.45, 0.25, 0.16), "swir16": (0.15, 0.32, 0.42)}.items():
        a = np.full(SHAPE, 0.05, dtype=np.float32)
        a[m_veg], a[m_soil], a[~m_veg & ~m_soil] = v, s, b
        out[k] = a
    return out


def _stage(prev: dict[str, np.ndarray], curr: dict[str, np.ndarray],
           sr_method: str = "sen2sr"):
    """La chaine REELLE du worker : prev -> change_score -> classify."""
    cr = change.change_score(prev, curr)
    return classify(built_ratio=change.built_ratio(curr), delta_ndbi_mean=cr.delta_ndbi_mean,
                    delta_bsi_mean=cr.delta_bsi_mean, change_score_value=cr.score,
                    sr_method=sr_method)


def test_built_ratio_mesure_la_part_minerale() -> None:
    """Signal d'ETAT : part de la parcelle sans vegetation (NDBI > 0)."""
    assert change.built_ratio(_scene(1.0, 0.0, 0.0)) == 0.0   # 100 % vegetal
    assert change.built_ratio(_scene(0.0, 0.0, 1.0)) == 1.0   # 100 % bati


def test_chaine_complete_atteint_les_5_jalons() -> None:
    """Les 5 jalons doivent etre ATTEIGNABLES par la chaine reelle du worker.

    Mesure du 2026-09-19 (avant ce cablage) : M4 etait du CODE MORT (0 fois sur 6000 tirages —
    `growth` valait toujours l'emprise car le worker passait des zeros comme ligne de base), et
    une parcelle stable sortait en « M1 fondation detectee ». Ce test verrouille la propriete
    inverse : chaque etat de chantier a un chemin mesurable.
    """
    assert _stage(_scene(0.9, 0.1, 0.0), _scene(0.9, 0.1, 0.0)).milestone == Milestone.M0_TERRAIN
    assert _stage(_scene(1.0, 0.0, 0.0), _scene(0.90, 0.10, 0.0)).milestone == Milestone.M1_FONDATION
    assert _stage(_scene(0.55, 0.05, 0.40),
                  _scene(0.45, 0.05, 0.50)).milestone == Milestone.M2_STRUCTURE
    assert _stage(_scene(0.30, 0.05, 0.65), _scene(0.30, 0.05, 0.65)).milestone == Milestone.M3_TOITURE
    assert _stage(_scene(0.05, 0.85, 0.10), _scene(0.75, 0.15, 0.10)).milestone == Milestone.M4_FINITION


def test_hold_milestone_ne_regresse_jamais() -> None:
    """Un chantier ne se de-construit pas : le jalon deja atteint est un plancher."""
    assert hold_milestone(Milestone.M1_FONDATION, 3) == Milestone.M3_TOITURE
    assert hold_milestone(Milestone.M4_FINITION, -1) == Milestone.M4_FINITION  # chantier neuf
    assert hold_milestone(Milestone.M0_TERRAIN, 0) == Milestone.M0_TERRAIN


def test_png_rgb_bytes() -> None:
    bands = {"red": _field(0.2), "green": _field(0.25), "blue": _field(0.15),
             "nir": _field(0.5), "swir16": _field(0.3)}
    png = obs.image_png_rgb(bands)
    assert png[:4] == b"\x89PNG"
    assert len(png) > 100
