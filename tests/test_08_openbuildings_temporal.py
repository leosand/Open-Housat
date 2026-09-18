# -*- coding: utf-8 -*-
"""Suite de tests unitaires et d'intégration V&V pour 08_openbuildings_temporal.py.

Conforme aux exigences V&V d'acceptation A1-A10 et aux critères de tolérance
géospatiale de la branche finetune-douala.
"""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path
from typing import Any

import numpy as np
import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "housat-finedouala-1" / "08_openbuildings_temporal.py"
spec = importlib.util.spec_from_file_location("openbuildings_temporal", MODULE_PATH)
if spec is None or spec.loader is None:
    raise ImportError(f"Impossible de charger le module à l'emplacement : {MODULE_PATH}")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

parse_bbox = mod.parse_bbox
lonlat_to_s2_tile_token = mod.lonlat_to_s2_tile_token
resolve_openbuildings_tile_url = mod.resolve_openbuildings_tile_url
compute_metrics = mod.compute_metrics
synthesize_temporal_proxy = mod.synthesize_temporal_proxy
BuildingMetrics = mod.BuildingMetrics


class TestBBoxParsing:
    """Validation géométrique et gestion des quadrants terrestres."""

    def test_parse_bbox_douala_standard(self) -> None:
        bbox = parse_bbox("9.60,3.95,9.85,4.15")
        assert bbox == (9.60, 3.95, 9.85, 4.15)

    def test_parse_bbox_hemisphere_ouest(self) -> None:
        """Contrôle de non-régression du bogue argparse avec les coordonnées négatives."""
        bbox = parse_bbox("-87.64,41.87,-87.60,41.90")
        assert bbox == (-87.64, 41.87, -87.60, 41.90)

    def test_parse_bbox_inversion_coordonnees(self) -> None:
        with pytest.raises(Exception):
            parse_bbox("10.0,4.0,9.0,5.0")

    def test_parse_bbox_format_invalide(self) -> None:
        with pytest.raises(Exception):
            parse_bbox("9.60,3.95,9.85")


class TestGeodesicTokening:
    """Validation de l'adressage spatial par tuilage géodésique mondial."""

    def test_token_douala(self) -> None:
        token = lonlat_to_s2_tile_token(9.70, 4.05)
        assert token == "N04_E008"

    def test_token_chicago(self) -> None:
        token = lonlat_to_s2_tile_token(-87.62, 41.88)
        assert token == "N40_W088"

    def test_tile_url_resolution_cameroon(self) -> None:
        meta = resolve_openbuildings_tile_url((9.60, 3.95, 9.85, 4.15), 2023)
        assert meta.country_iso3 == "CMR"
        assert meta.year == 2023
        assert "open_buildings_temporal_CMR_2023_N04_E008.tif" in meta.download_url


class TestPhysicalMilestonesVV:
    """Vérification et validation de l'arbitrage physique Dalle vs Toit (M0 -> M4)."""

    def test_milestone_m0_terrain_nu(self) -> None:
        presence = np.zeros((10, 10), dtype=np.float32)
        height = np.zeros((10, 10), dtype=np.float32)
        m = compute_metrics(presence, height, threshold=0.50)
        assert m.built_fraction == 0.0
        assert "M0" in m.roof_vs_slab_verdict

    def test_milestone_m1_m2_dalle_brute(self) -> None:
        presence = np.ones((10, 10), dtype=np.float32) * 0.80
        height = np.ones((10, 10), dtype=np.float32) * 1.20
        m = compute_metrics(presence, height, threshold=0.50)
        assert m.built_fraction == 1.0
        assert m.height_p50 == 1.20
        assert "M1/M2" in m.roof_vs_slab_verdict

    def test_milestone_m3_toiture_posee(self) -> None:
        presence = np.ones((10, 10), dtype=np.float32) * 0.85
        height = np.ones((10, 10), dtype=np.float32) * 3.60
        m = compute_metrics(presence, height, threshold=0.50)
        assert m.height_p50 == 3.60
        assert "M3" in m.roof_vs_slab_verdict

    def test_milestone_m4_batiment_etage(self) -> None:
        presence = np.ones((10, 10), dtype=np.float32) * 0.95
        height = np.ones((10, 10), dtype=np.float32) * 7.50
        m = compute_metrics(presence, height, threshold=0.50)
        assert m.height_p50 == 7.50
        assert "M4" in m.roof_vs_slab_verdict


class TestSpatialAlignmentAndConsistency:
    """Validation croisée sur l'îlot Housat (19x19) avec le masque OSM."""

    def test_alignment_with_osm_mask(self) -> None:
        osm_mask = np.zeros((19, 19), dtype=np.uint8)
        osm_mask[4:15, 4:15] = 1
        expected_ratio = float(np.mean(osm_mask))

        layers = synthesize_temporal_proxy((9.7042, 4.0442, 9.7058, 4.0458), (19, 19), osm_mask)
        metrics = compute_metrics(layers["presence"], layers["height"], threshold=0.45)

        assert abs(metrics.built_fraction - expected_ratio) < 0.10
        assert layers["presence"].shape == (19, 19)
        assert layers["height"].shape == (19, 19)
        assert layers["fractional_count"].shape == (19, 19)
