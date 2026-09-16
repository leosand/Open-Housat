"""Tests du module Wayback (imagerie HR datee) — sans reseau (fetcher injecte)."""

import io
import json

import numpy as np
import pytest
from housat.imagery import wayback
from PIL import Image

CONFIG = {
    "1": {"itemTitle": "World Imagery (Wayback 2018-01-01)",
          "itemURL": "https://t/World_Imagery/MapServer/tile/111/{level}/{row}/{col}"},
    "2": {"itemTitle": "World Imagery (Wayback 2025-01-01)",
          "itemURL": "https://t/World_Imagery/MapServer/tile/222/{level}/{row}/{col}"},
}
BBOX = (9.70, 4.04, 9.71, 4.05)


def _png() -> bytes:
    """PNG 256x256 a bruit aleatoire : taille > seuil de detection de couverture Wayback."""
    arr = np.random.default_rng(0).integers(0, 256, (256, 256, 3), dtype=np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG")
    return buf.getvalue()


def _seed() -> None:
    """Injecte la config dans le cache (evite tout reseau) et purge le cache de dates."""
    wayback._releases_cache = wayback._parse_releases(CONFIG)
    wayback._dates_cache.clear()


def test_parse_releases_sorts_and_maps_placeholders() -> None:
    rels = wayback._parse_releases(CONFIG)
    assert [r.date for r in rels] == ["2018-01-01", "2025-01-01"]
    assert rels[0].release_id == "111"
    assert rels[0].url(3, 5, 7).endswith("/tile/111/3/7/5")  # {z}/{y}/{x} -> level/row/col


def test_load_releases_via_injected_config() -> None:
    rels = wayback.load_releases(fetcher=lambda _url: json.dumps(CONFIG), refresh=True)
    assert [r.date for r in rels] == ["2018-01-01", "2025-01-01"]


def test_available_dates_filters_missing_coverage() -> None:
    _seed()

    def fetcher(url: str) -> bytes:
        # release 2018 -> tuile vide (petite) ; release 2025 -> tuile reelle (grande)
        return _png() if "/tile/222/" in url else b"\x00" * 50

    assert wayback.available_dates(BBOX, fetcher=fetcher) == ["2025-01-01"]


def test_fetch_wayback_stitches_tiles() -> None:
    _seed()
    png = wayback.fetch_wayback(BBOX, "2025-01-01", size=64, zoom=15, fetcher=lambda _u: _png())
    assert png[:4] == b"\x89PNG"
    assert Image.open(io.BytesIO(png)).size == (64, 64)


def test_fetch_wayback_unknown_date_raises() -> None:
    _seed()
    with pytest.raises(ValueError):
        wayback.fetch_wayback(BBOX, "1999-01-01", size=64, fetcher=lambda _u: _png())


def test_latest_date_at_or_before_picks_most_recent_covered() -> None:
    """Sonde ciblee : on veut la date <= borne la PLUS RECENTE reellement couverte."""
    _seed()

    def fetcher(url: str) -> bytes:
        return _png() if "/tile/111/" in url else b"\x00" * 10  # seule 2018 est couverte

    assert wayback.latest_date_at_or_before(BBOX, "2025-12-31", fetcher=fetcher) == "2018-01-01"


def test_latest_date_at_or_before_none_without_coverage() -> None:
    _seed()
    assert wayback.latest_date_at_or_before(BBOX, "2025-12-31", fetcher=lambda _u: b"") is None


def test_fetch_wayback_native_size_avoids_upsampling() -> None:
    """Sans `size`, la sortie est a la taille NATIVE (jamais de sur-echantillonnage = flou)."""
    _seed()
    png = wayback.fetch_wayback(BBOX, "2025-01-01", zoom=15, fetcher=lambda _u: _png())
    native = wayback._native_size(wayback.validate_bbox(BBOX), 15)
    assert Image.open(io.BytesIO(png)).size == (native, native)


def test_fetch_wayback_falls_back_to_lower_zoom_when_tiles_missing() -> None:
    """Couverture absente au zoom demande -> on redescend au zoom inferieur (pas d'echec)."""
    _seed()

    def fetcher(url: str) -> bytes:
        if "/tile/222/15/" in url:      # zoom 15 sans couverture pour cette release
            raise RuntimeError("404")
        return _png()

    png = wayback.fetch_wayback(BBOX, "2025-01-01", zoom=15, fetcher=fetcher)
    assert png[:4] == b"\x89PNG"
