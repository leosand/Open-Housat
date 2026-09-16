"""Tests du masque nuage PAR PARCELLE (SCL) — pur, synthetique, sans reseau."""

import numpy as np
import pytest
from housat.imagery import clouds


def test_parcel_cloud_pct_counts_only_obscured_classes() -> None:
    """Vegetation (4) = clair ; un seul pixel nuage (8) sur 16 => 6,25 %."""
    scl = np.full((4, 4), 4, dtype=np.uint8)
    scl[0, 0] = 8
    assert clouds.parcel_cloud_pct(scl) == pytest.approx(6.25)


def test_parcel_cloud_pct_all_obscured_and_all_clear() -> None:
    assert clouds.parcel_cloud_pct(np.full((4, 4), 9, dtype=np.uint8)) == 100.0
    assert clouds.parcel_cloud_pct(np.full((4, 4), 4, dtype=np.uint8)) == 0.0


def test_parcel_cloud_pct_counts_invalid_pixels() -> None:
    """NO_DATA (0) et sature (1) ne sont pas exploitables non plus."""
    assert clouds.parcel_cloud_pct(np.array([[0, 1, 4, 4]], dtype=np.uint8)) == pytest.approx(50.0)


def test_parcel_cloud_pct_cloud_shadow_and_cirrus_count() -> None:
    assert clouds.parcel_cloud_pct(np.array([[3, 10]], dtype=np.uint8)) == 100.0


def test_parcel_cloud_pct_empty_is_nan() -> None:
    assert np.isnan(clouds.parcel_cloud_pct(np.array([], dtype=np.uint8)))


def test_realistic_mixed_parcel() -> None:
    """Parcelle majoritairement vegetee avec une bande de nuages : ~25 %."""
    scl = np.full((8, 8), 4, dtype=np.uint8)
    scl[:2, :] = 8  # 16 px nuage sur 64
    assert clouds.parcel_cloud_pct(scl) == pytest.approx(25.0)


def test_scl_window_etend_les_emprises_de_maison() -> None:
    """Une emprise de 16 x 8 m ne couvre aucun pixel SCL (20 m) : `nodata=0` etait alors compte
    comme obscurci et TOUTES les scenes etaient rejetees (« nuages 100 % » sur 20 dates d'affilee).
    Verifie : l'emprise de maison est etendue a 60 m de cote, une emprise plus grande est inchangee."""
    from housat.imagery.sentinel2 import SCL_MIN_SPAN_M, _scl_window
    from shapely.geometry import box

    maison = _scl_window(box(0, 0, 16, 8), SCL_MIN_SPAN_M)
    assert maison.bounds == (-22.0, -26.0, 38.0, 34.0)
    parcelle = _scl_window(box(0, 0, 178, 178), SCL_MIN_SPAN_M)
    assert parcelle.bounds == (0.0, 0.0, 178.0, 178.0)
