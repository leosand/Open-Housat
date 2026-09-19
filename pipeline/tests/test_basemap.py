"""Tests du fond visuel haute resolution (cascade de fournisseurs) — sans reseau.
Basemap (provider cascade) tests — no network (fetcher injecte).
"""

import io

import pytest
from housat.imagery import basemap
from PIL import Image


def _solid_png(color: tuple[int, int, int] = (255, 255, 255)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (basemap.TILE_SIZE, basemap.TILE_SIZE), color).save(buf, format="PNG")
    return buf.getvalue()


# --- Geometrie de tuiles (Web Mercator) ---

def test_lonlat_to_global_px_origin_is_centre_of_world() -> None:
    px, py = basemap.lonlat_to_global_px(0.0, 0.0, 1)
    assert px == 256.0 and py == 256.0


def test_lonlat_to_tile_known_value() -> None:
    assert basemap.lonlat_to_tile(0.0, 0.0, 1) == (1, 1)
    assert basemap.lonlat_to_tile(-180.0, 85.0, 0) == (0, 0)


def test_tile_range_and_zoom_bound_request_count() -> None:
    bbox = (9.70, 4.04, 9.71, 4.05)
    z = basemap.choose_zoom(bbox, max_tiles=4)
    x0, y0, x1, y1 = basemap.tile_range(bbox, z)
    assert (x1 - x0 + 1) <= 4 and (y1 - y0 + 1) <= 4
    assert z >= 10  # emprise ~1 km : le zoom retenu doit donner une vraie resolution


def test_stitch_xyz_builds_requested_size_from_tiles() -> None:
    urls: list[str] = []

    def fetcher(url: str) -> bytes:
        urls.append(url)
        return _solid_png((10, 20, 30))

    png = basemap.stitch_xyz((9.70, 4.04, 9.71, 4.05), 128,
                             "https://tiles.example/{z}/{x}/{y}.png", fetcher=fetcher, zoom=14)
    assert png[:4] == b"\x89PNG"
    assert Image.open(io.BytesIO(png)).size == (128, 128)
    assert urls and all("tiles.example" in u for u in urls)
    assert all("{z}" not in u and "{x}" not in u for u in urls)  # placeholders substitues


def test_stitch_xyz_raises_on_empty_tile() -> None:
    with pytest.raises(RuntimeError):
        basemap.stitch_xyz((9.70, 4.04, 9.71, 4.05), 64, "https://t/{z}/{x}/{y}.png",
                           fetcher=lambda _u: b"", zoom=13)


# --- Fournisseur Esri ---

def test_fetch_basemap_esri_builds_url_and_returns_provenance() -> None:
    seen: dict[str, str] = {}

    def fake_fetcher(url: str) -> bytes:
        seen["url"] = url
        return b"\xff\xd8\xffJPEGDATA"

    img = basemap.fetch_basemap((9.70, 4.04, 9.71, 4.05), size=512, fetcher=fake_fetcher)
    assert seen["url"].startswith("https://services.arcgisonline.com/")
    assert "bbox=9.7,4.04,9.71,4.05" in seen["url"]
    assert img.data.startswith(b"\xff\xd8\xff")
    assert img.provider == "esri_world_imagery"
    assert img.redistributable is False
    assert img.bbox == (9.70, 4.04, 9.71, 4.05)
    assert img.attribution


# --- Robustesse de l'API publique ---

def test_fetch_basemap_rejects_unknown_provider() -> None:
    with pytest.raises(ValueError):
        basemap.fetch_basemap((0, 0, 1, 1), provider="inexistant", fetcher=lambda _u: b"x")


def test_fetch_basemap_rejects_empty_response() -> None:
    with pytest.raises(RuntimeError):
        basemap.fetch_basemap((0, 0, 1, 1), fetcher=lambda _u: b"")


def test_fetch_basemap_rejects_bad_size() -> None:
    with pytest.raises(ValueError):
        basemap.fetch_basemap((0, 0, 1, 1), size=0, fetcher=lambda _u: b"x")


def test_validate_bbox_rejects_unordered_or_out_of_range() -> None:
    with pytest.raises(ValueError):
        basemap.validate_bbox((10, 0, 5, 1))
    with pytest.raises(ValueError):
        basemap.validate_bbox((0, 10, 1, 5))
    with pytest.raises(ValueError):
        basemap.validate_bbox((-200, 0, 1, 1))
    with pytest.raises(ValueError):
        basemap.validate_bbox((0, 0, 1))


def test_validate_bbox_normalises_types() -> None:
    assert basemap.validate_bbox((0, 0, 1, 1)) == (0.0, 0.0, 1.0, 1.0)


def test_cli_writes_file_with_injected_fetch(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(basemap, "_http_get", lambda _url: b"\xff\xd8\xffCLI")
    out = tmp_path / "square.jpg"
    rc = basemap.main(["--bbox", "9.70,4.04,9.71,4.05", "--out", str(out), "--size", "64"])
    assert rc == 0
    assert out.read_bytes().startswith(b"\xff\xd8\xff")
