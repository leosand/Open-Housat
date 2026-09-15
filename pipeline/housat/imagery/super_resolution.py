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


@dataclass_placeholder = None


def upscale_bands(
    bands: dict[str, np.ndarray], factor: int = 4
) -> tuple[dict[str, np.ndarray], str]:
    """Superresout chaque bande. Retourne (bandes SR, methode utilisee).
    Upscale every band; returns (sr_bands, method) pour tracabilite dans l'observation.
    """
    if HAS_SEN2SR:
        stacked = np.stack([bands[k] for k in sorted(bands)], axis=-1).astype(np.float32)
        sr = sen2sr.predict_large(stacked)  # API ESA OpenSR (poids telecharges au 1er appel)
        out = {k: sr[..., i] for i, k in enumerate(sorted(bands))}
        return out, "sen2sr"

    logger.warning("SEN2SR indisponible — fallback bicubique, confiance reduite")
    from skimage.transform import resize  # scikit-image via scikit-learn stack

    out = {
        k: resize(v, (v.shape[0] * factor, v.shape[1] * factor), order=3, anti_aliasing=True).astype(np.float32)
        for k, v in bands.items()
    }
    return out, "bicubic_fallback"
