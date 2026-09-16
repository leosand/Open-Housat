"""Tests des emprises de batiments (OSM/Overpass) — sans reseau (fetcher injecte)."""

import json

from housat.imagery import buildings

BBOX = (9.7044, 4.0444, 9.7056, 4.0456)
SAMPLE = {"elements": [
    {"type": "way", "geometry": [
        {"lat": 4.0446, "lon": 9.7045}, {"lat": 4.0446, "lon": 9.7048},
        {"lat": 4.0449, "lon": 9.7048}, {"lat": 4.0449, "lon": 9.7045}]},
    {"type": "way", "geometry": [{"lat": 4.045, "lon": 9.705}]},  # < 3 sommets -> ignore
]}


def test_fetch_buildings_parses_polygons() -> None:
    polys = buildings.fetch_buildings(BBOX, fetcher=lambda _u: json.dumps(SAMPLE))
    assert len(polys) == 1 and len(polys[0]) == 4
    assert polys[0][0] == (9.7045, 4.0446)


def test_footprint_stats_caracterise_l_emprise() -> None:
    """Emprise de 0,0012 deg (~133 m) contenant un batiment de 0,0003 deg (~33 m) : ~6 % bati."""
    polys = buildings.fetch_buildings(BBOX, fetcher=lambda _u: json.dumps(SAMPLE))
    st = buildings.footprint_stats(polys, BBOX)
    assert st["count"] == 1
    assert 1050 <= st["built_m2"] <= 1180      # ~33,3 m x 33,4 m a la latitude 4,045
    assert 0.055 <= st["built_frac"] <= 0.07   # 1113 / ~17 800 m2
    assert st["mean_m2"] == st["built_m2"]
    assert 17600 <= st["area_m2"] <= 18000     # 0,0012 deg lon x 0,0012 deg lat


def test_footprint_stats_emprise_vide() -> None:
    st = buildings.footprint_stats([], BBOX)
    assert st["count"] == 0 and st["built_frac"] == 0.0 and st["mean_m2"] == 0


def test_footprint_stats_coupe_les_emprises_voisines() -> None:
    """Overpass renvoie la geometrie COMPLETE d'un way qui touche la zone : sans coupe, un immeuble
    voisin apporterait des m2 hors du carre et la part batie pourrait depasser 100 %."""
    deborde = [(9.70, 4.04), (9.72, 4.04), (9.72, 4.06), (9.70, 4.06)]  # bien plus grand que BBOX
    st = buildings.footprint_stats([deborde], BBOX)
    assert st["built_frac"] <= 1.0
    assert st["built_m2"] <= st["area_m2"]
