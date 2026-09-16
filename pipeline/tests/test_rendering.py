"""Tests du rendu d'affichage RGB (voie VISION) — synthetique, sans reseau.
Tests for the display rendering (VISION track) — synthetic, no network.
"""

import io

import numpy as np
from housat import observations as obs
from housat.imagery import rendering
from PIL import Image


def _decode(png: bytes) -> np.ndarray:
    return np.asarray(Image.open(io.BytesIO(png)).convert("RGB"), dtype=np.float32)


def test_stretch_uses_full_range_on_low_contrast() -> None:
    """Contraste local faible (0.10-0.16) : l'etirement doit occuper toute la gamme 0-255."""
    a = np.linspace(0.10, 0.16, 16 * 16, dtype=np.float32).reshape(16, 16, 1).repeat(3, axis=2)
    u8 = rendering.stretch_to_uint8(a)
    assert u8.dtype == np.uint8
    assert int(u8.max()) - int(u8.min()) > 200


def test_stretch_uniform_image_is_safe() -> None:
    """Image quasi-uniforme : percentiles degeneres (hi - lo ~ 0) — aucune division par 0."""
    a = np.full((8, 8, 3), 0.3, dtype=np.float32)
    u8 = rendering.stretch_to_uint8(a)
    assert u8.dtype == np.uint8 and u8.shape == (8, 8, 3)


def test_stretch_neutralises_nan_inf() -> None:
    """Donnees de bord (NaN/inf) neutralisees avant percentiles — sinon sortie non finie."""
    a = np.full((8, 8, 3), 0.3, dtype=np.float32)
    a[0, 0, 0] = np.nan
    a[0, 0, 1] = np.inf
    u8 = rendering.stretch_to_uint8(a)
    assert np.isfinite(u8).all()


def test_gamma_below_one_brightens_midtones() -> None:
    a = np.linspace(0.0, 1.0, 256, dtype=np.float32).reshape(16, 16, 1).repeat(3, axis=2)
    darker_gamma = rendering.stretch_to_uint8(a, gamma=1.0).mean()
    brighter_gamma = rendering.stretch_to_uint8(a, gamma=0.7).mean()
    assert brighter_gamma > darker_gamma


def test_display_png_is_valid_png() -> None:
    rgb = np.linspace(0.1, 0.3, 16 * 16 * 3, dtype=np.float32).reshape(16, 16, 3)
    png = rendering.display_png(rgb)
    assert png[:4] == b"\x89PNG"


def test_image_png_rgb_stretch_beats_legacy_clip() -> None:
    """Regression V&V : le rendu etire doit offrir un contraste > a l'ancien clip dur."""
    ramp = np.linspace(0.08, 0.20, 64 * 64, dtype=np.float32).reshape(64, 64)
    bands = {"red": ramp, "green": ramp, "blue": ramp}
    new = _decode(obs.image_png_rgb(bands))
    legacy = _decode(obs.image_png_rgb(bands, stretch=False))
    assert new.std() > legacy.std()
    assert new.max() - new.min() > legacy.max() - legacy.min()
