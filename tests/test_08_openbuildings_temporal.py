# -*- coding: utf-8 -*-
"""Suite de tests unitaires et d'intégration V&V pour 08_openbuildings_temporal.py.

Conforme aux exigences V&V d'acceptation A1-A10 et aux critères de tolérance
géospatiale de la branche finetune-douala.
"""

from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "housat-finedouala-1" / "08_openbuildings_temporal.py"
spec = importlib.util.spec_from_file_location("openbuildings_temporal", MODULE_PATH)
if spec is None or spec.loader is None:
    raise ImportError(f"Impossible de charger le module à l'emplacement : {MODULE_PATH}")
mod = importlib.util.module_from_spec(spec)
# VOIE B retenue (vs renommage du script en module) : le fichier `08_*.py` n'est pas importable
# comme module (il commence par un chiffre) et son renommage aurait casse le point d'entree CLI
# documente dans le plan V&V. Il faut enregistrer le module dans `sys.modules` AVANT `exec_module`,
# sinon `dataclasses`/`typing.get_type_hints` ne resolvent pas les annotations et le chargement leve
# `AttributeError: 'NoneType' object has no attribute '__dict__'` (0 test collecte sur 8).
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)

parse_bbox = mod.parse_bbox
resolve_openbuildings_tile_url = mod.resolve_openbuildings_tile_url
decide_provenance = mod.decide_provenance
OB_TEMPORAL_LAYOUT = mod.OB_TEMPORAL_LAYOUT
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


class TestOpenBuildingsTileResolution:
    """Vraie voie d'accès Open Buildings 2.5D : mesurée, jamais inventée.

    Historique : les tests précédents verrouillaient une invention (jeton de grille 2° `N04_E008` et
    chemin `/CMR/tiles/open_buildings_temporal_CMR_2023_N04_E008.tif`) qui renvoyait **HTTP 404**.
    Ils sont remplacés par des tests qui verrouillent la mesure du 2026-09-19.
    """

    def test_layout_structure_officielle_mesuree(self) -> None:
        """La constante décrit le chemin RÉELLEMENT servi (HEAD 200 mesuré le 2026-09-19)."""
        assert OB_TEMPORAL_LAYOUT.startswith(
            "https://storage.googleapis.com/open-buildings-temporal-data/v1/geotiffs/"
        )
        assert OB_TEMPORAL_LAYOUT.endswith("/tile_<hash>.tif")

    def test_resolution_refuse_d_inventer(self) -> None:
        """Sans index lat/lon -> tuile, aucune URL n'est fabriquée.

        Fabriquer une URL « plausible » produit un 404 puis un repli étiqueté comme la source
        distante — le mensonge de provenance que `docs/limites-et-honnetete.md` § 4.7 interdit.
        """
        assert resolve_openbuildings_tile_url((9.60, 3.95, 9.85, 4.15), 2023) is None
        assert resolve_openbuildings_tile_url((-87.64, 41.87, -87.60, 41.90), 2023) is None

    def test_sonde_200_ne_donne_pas_la_source(self) -> None:
        """La source distante ne s'attribue que si la tuile est RÉELLEMENT utilisée."""
        source, provenance, accord = decide_provenance(200, tuile_utilisee=False, osm_disponible=True)
        assert provenance == "local_fallback"
        assert "repli" in source
        assert accord.startswith("NON_VERIFIABLE")

        source_ok, prov_ok, accord_ok = decide_provenance(
            200, tuile_utilisee=True, osm_disponible=True
        )
        assert prov_ok == "remote_download"
        assert accord_ok == "CONFORME"
        assert "Google" in source_ok


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
