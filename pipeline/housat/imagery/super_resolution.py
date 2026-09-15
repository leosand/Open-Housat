"""Superresolution Sentinel-2 : SEN2SR (ESA OpenSR) en primaire, bicubique en fallback.
Super-resolution: SEN2SR as primary engine, honest bicubic fallback when no GPU/package.
Le fallback est toujours trace (low_confidence) — jamais masque au client.
"""

from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)

try:
    import sen2sr  # type: ignore

    HAS_SEN2SR = True
except ImportError:
    HAS_SEN2SR = False

# Ordre physique Sentinel-2 (B02, B03, B04, B08, B11) — JAMAIS sorted() alphabetique
# (sinon nir/red inverses -> SEN2SR recoit un tenseur incoherent).
BAND_ORDER: tuple[str, ...] = ("blue", "green", "red", "nir", "swir16")


def upscale_bands(
    bands: dict[str, np.ndarray], factor: int = 4
) -> tuple[dict[str, np.ndarray], str]:
    """Superresout chaque bande. Retourne (bandes SR, methode utilisee)."""
    if HAS_SEN2SR:
        keys = [k for k in BAND_ORDER if k in bands]
        stacked = np.stack([bands[k] for k in keys], axis=-1).astype(np.float32)
        sr = sen2sr.predict_large(stacked)
        return {k: sr[..., i] for i, k in enumerate(keys)}, "sen2sr"

    logger.warning("SEN2SR indisponible — fallback bicubique, confiance reduite")
    from skimage.transform import resize

    out = {
        k: resize(v, (v.shape[0] * factor, v.shape[1] * factor), order=3,
                  anti_aliasing=True, preserve_range=True).astype(np.float32)
        for k, v in bands.items()
    }
    return out, "bicubic_fallback"
