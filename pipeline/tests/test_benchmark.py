"""Tests des briques pures du benchmark SR (metriques, degradations) — sans torch ni reseau.
Pure benchmark pieces (metrics, degradations) — no torch, no network.
"""

import numpy as np
from housat.benchmark import area_downsample, lanczos_resize, psnr, ssim


def test_psnr_identical_is_infinite() -> None:
    a = np.zeros((8, 8, 3), np.uint8)
    assert psnr(a, a) == float("inf")


def test_psnr_decreases_as_error_grows() -> None:
    a = np.full((8, 8, 3), 100, np.uint8)
    close = np.full((8, 8, 3), 101, np.uint8)
    far = np.full((8, 8, 3), 180, np.uint8)
    assert psnr(a, close) > psnr(a, far)


def test_ssim_identical_is_one() -> None:
    a = np.tile(np.arange(64, dtype=np.uint8).reshape(8, 8)[..., None], (1, 1, 3))
    assert abs(ssim(a, a) - 1.0) < 1e-6


def test_ssim_bounded_and_ordered() -> None:
    rng = np.random.default_rng(0)
    a = rng.integers(0, 256, (16, 16, 3), dtype=np.uint8)
    same = ssim(a, a)
    noisy = ssim(a, np.clip(a.astype(int) + rng.integers(-60, 60, a.shape), 0, 255).astype(np.uint8))
    assert -1.0 <= noisy <= same <= 1.0 + 1e-6


def test_area_downsample_half_and_mean_preserved() -> None:
    a = np.full((16, 16, 3), 200, np.uint8)
    out = area_downsample(a, 8)
    assert out.shape == (8, 8, 3)
    assert abs(int(out.mean()) - 200) <= 1


def test_lanczos_resize_upsamples_shape() -> None:
    a = np.zeros((4, 4, 3), np.uint8)
    out = lanczos_resize(a, 16)
    assert out.shape == (16, 16, 3)
