"""Tests de la selection de moteur SR + voie affichage (logique, poids reels non requis).
Super-resolution engine selection + display-track tests (logic only, no real weights).
"""

import numpy as np
import pytest
from housat.imagery import super_resolution as sr


class _FakeSession:
    """Session ONNX factice : reproduit chaque pixel `scale` fois (surresolution exacte)."""

    def __init__(self, scale: int) -> None:
        self.scale = scale

    def get_inputs(self) -> list[object]:
        class _Input:
            name = "input"

        return [_Input()]

    def run(self, _outputs: object, feeds: dict) -> list[np.ndarray]:
        x = next(iter(feeds.values()))
        return [np.repeat(x, self.scale, axis=2).repeat(self.scale, axis=3)]


def test_resolve_engine_falls_back_to_bicubic_without_sen2sr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sr, "sen2sr_available", lambda: False)
    assert sr.resolve_engine("auto") == "bicubic"
    assert sr.resolve_engine("sen2sr") == "bicubic"


def test_resolve_engine_prefers_sen2sr_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sr, "sen2sr_available", lambda: True)
    assert sr.resolve_engine("auto") == "sen2sr"
    assert sr.resolve_engine("bicubic") == "bicubic"


def test_upscale_bands_keeps_bicubic_method_label() -> None:
    bands = {k: np.full((4, 4), 0.3, dtype=np.float32) for k in sr.BAND_ORDER}
    out, method = sr.upscale_bands(bands, factor=2)
    assert method == "bicubic_fallback"
    assert out["red"].shape == (8, 8)


def test_upscale_bands_sen2sr_failure_degrades_gracefully(monkeypatch: pytest.MonkeyPatch) -> None:
    """Echec d'inference SEN2SR (memoire/modele) => repli bicubique, jamais de crash worker."""
    monkeypatch.setattr(sr, "resolve_engine", lambda engine=None: "sen2sr")

    def _boom(_bands: dict) -> dict:
        raise RuntimeError("CUDA out of memory")

    monkeypatch.setattr(sr, "_sen2sr_upscale", _boom)
    bands = {k: np.full((4, 4), 0.3, dtype=np.float32) for k in sr.BAND_ORDER}
    out, method = sr.upscale_bands(bands, factor=2)
    assert method == "bicubic_fallback"
    assert out["red"].shape == (8, 8)


def test_display_passthrough_without_model() -> None:
    bands = {k: np.zeros((6, 7), dtype=np.float32) for k in ("red", "green", "blue")}
    out, method = sr.upscale_rgb_display(bands, model_path="")
    assert method == "display_passthrough"
    assert out["red"].shape == (6, 7)


def test_display_uses_perceptual_model_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Backend:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def upscale(self, rgb: np.ndarray) -> np.ndarray:
            return np.repeat(np.repeat(rgb, 2, axis=0), 2, axis=1)

    monkeypatch.setattr(sr, "OnnxSrBackend", _Backend)
    bands = {k: np.ones((4, 4), dtype=np.float32) for k in ("red", "green", "blue")}
    out, method = sr.upscale_rgb_display(bands, model_path="dummy.onnx", scale=2)
    assert method == "realesrgan"
    assert out["red"].shape == (8, 8)


def test_display_rejects_incomplete_rgb() -> None:
    with pytest.raises(ValueError):
        sr.upscale_rgb_display({"red": np.zeros((4, 4), np.float32)}, model_path="")


def test_onnx_backend_tiling_reconstructs_with_padding() -> None:
    """H=6, W=5 avec tuile 4 : tuiles partielles (padding) -> reconstruction exacte."""
    rng = np.random.default_rng(1)
    rgb = rng.random((6, 5, 3)).astype(np.float32)
    backend = sr.OnnxSrBackend(scale=2, tile=4, session=_FakeSession(2), input_name="input")
    out = backend.upscale(rgb)
    assert out.shape == (12, 10, 3)
    assert np.allclose(out[0, 0], rgb[0, 0])
    assert np.allclose(out[11, 9], rgb[5, 4])


def test_onnx_backend_rejects_non_rgb() -> None:
    backend = sr.OnnxSrBackend(scale=2, session=_FakeSession(2), input_name="input")
    with pytest.raises(ValueError):
        backend.upscale(np.zeros((4, 4), dtype=np.float32))


def test_display_accepts_onnx_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    """Le moteur d'affichage `onnx` (modele EDSR-lite livre) doit etre selectionnable."""
    class _Backend:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def upscale(self, rgb: np.ndarray) -> np.ndarray:
            return np.repeat(np.repeat(rgb, 2, axis=0), 2, axis=1)

    monkeypatch.setattr(sr, "OnnxSrBackend", _Backend)
    bands = {k: np.ones((4, 4), dtype=np.float32) for k in ("red", "green", "blue")}
    out, method = sr.upscale_rgb_display(bands, engine="onnx", model_path="housat_sr_x4.onnx", scale=2)
    assert method == "realesrgan"  # etiquette du modele d'affichage applique
    assert out["red"].shape == (8, 8)
