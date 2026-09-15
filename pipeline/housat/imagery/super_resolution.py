"""Superresolution Sentinel-2 : SEN2SR (ESA OpenSR) en primaire, bicubique en fallback.
Super-resolution: SEN2SR as primary engine, honest bicubic fallback when no GPU/package.

Correctifs V&V (2026-09-15) :
- grille unifiee : toutes les bandes sont ramenées sur la grille SR du rouge.
  swir16 est 20 m (vs 10 m pour RGB/NIR) : sans reechantillonnage ici, les indices
  NDBI/BSI melangent des grilles incompatibles (crash broadcast sur donnees reelles).
- SEN2SR ne recoit que les 4 bandes supportees a 10 m (B02, B03, B04, B08) ;
  swir16 (B11, 20 m) est toujours upscalee separément — jamais envoyee au modele.
- ordre physique explicite (jamais sorted() alphabetique : nir/red seraient inverses).
Le fallback est toujours trace (bicubique) — jamais masque au client.
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

# Ordre physique Sentinel-2 10 m (B02, B03, B04, B08) — seul jeu supporte par SEN2SR.
SR_BANDS: tuple[str, ...] = ("blue", "green", "red", "nir")
# Bandes 20 m (B11) : upsamplees hors modele, sur la meme grille cible.
LR_BANDS: tuple[str, ...] = ("swir16",)

# Ordre physique complet (pour diagnostic/tests) — JAMAIS sorted().
BAND_ORDER: tuple[str, ...] = ("blue", "green", "red", "nir", "swir16")


def _resize_to(a: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    """Reechantillonnage bilineaire/cubique preserve-range vers `shape`."""
    from skimage.transform import resize

    return resize(a, shape, order=3, anti_aliasing=True,
                  preserve_range=True).astype(np.float32)


def upscale_bands(
    bands: dict[str, np.ndarray], factor: int = 4
) -> tuple[dict[str, np.ndarray], str]:
    """Superresout et aligne toutes les bandes sur la grille SR de la reference (red).

    Retourne (bandes SR, methode utilisee). Invariant : toutes les bandes de sortie
    ont la meme forme — condition indispensable au calcul d'indices multi-bandes.
    """
    # Note V&V : "or" est interdit ici — un ndarray n'a pas de verite booleenne.
    ref = bands["red"] if "red" in bands else next(iter(bands.values()))
    target = (ref.shape[0] * factor, ref.shape[1] * factor)

    if HAS_SEN2SR:
        keys = [k for k in SR_BANDS if k in bands]
        stacked = np.stack([bands[k] for k in keys], axis=-1).astype(np.float32)
        sr = sen2sr.predict_large(stacked)
        out = {k: sr[..., i] for i, k in enumerate(keys)}
        sr_shape = out[keys[0]].shape
        for k in bands:  # bandes 20 m (swir16) : bicubique vers la grille SR
            if k not in out:
                out[k] = _resize_to(bands[k], sr_shape)
        return out, "sen2sr"

    logger.warning("SEN2SR indisponible — fallback bicubique, confiance reduite")
    out = {k: (_resize_to(v, target) if v.shape != target else v.astype(np.float32))
           for k, v in bands.items()}
    return out, "bicubic_fallback"
