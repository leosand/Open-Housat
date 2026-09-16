"""Rendu d'affichage des composites RGB — voie VISION, distincte de la voie radiometrique.
Display rendering for RGB composites — the VISION track, kept apart from the radiometric one.

Le PNG avant/apres sert a VOIR, pas a MESURER : on peut donc y appliquer un etirement
robuste par percentiles, une correction gamma et un leger rehaussement. Les bandes de
CALCUL (indices NDVI/NDBI/BSI, jalons M0-M4) ne passent JAMAIS par ici : une
surresolutions perceptuelle ne doit pas fabriquer une fausse structure batie (jalons
M2/M3 fausses) — garantie V&V d'inalterabilite du signal de detection.

Correctif 2026-09-17 : l'ancien rendu (`rgb / 0.35` avec clip dur, sans gamma ni
normalisation inter-scenes) produisait des vignettes sombres, plates et delavees sur
sols/toits clairs — la « resolution nulle » percue venait autant du rendu que de l'absence
de modele SR. Etirement 2-98 % + gamma 0.9 : gamme dynamique pleinement utilisee.
"""

from __future__ import annotations

import io

import numpy as np

# Bornes d'etirement par defaut (percentiles) — ignorent les extremes (nuages, ombres dures).
DEFAULT_LO_PCT = 2.0
DEFAULT_HI_PCT = 98.0
# Gamma d'affichage : < 1 eclaircit les tons moyens (Sentinel-2 L2A est sombre en RGB brut).
DEFAULT_GAMMA = 0.9


def stretch_to_uint8(
    rgb: np.ndarray,
    lo_pct: float = DEFAULT_LO_PCT,
    hi_pct: float = DEFAULT_HI_PCT,
    gamma: float = DEFAULT_GAMMA,
) -> np.ndarray:
    """Etire un composite (H, W, 3) vers [0, 255] par percentiles robustes, puis gamma.

    Bornes calculees JOINTEMENT sur les 3 canaux (balance chromatique preservee). Une image
    quasi-uniforme (hi - lo ~ 0) est renvoyee sans division : `(a - lo) / (hi - lo)`
    exploserait sinon. Les NaN/inf (donnees de bord) sont neutralises avant calcul.
    """
    a = np.asarray(rgb, dtype=np.float32)
    finite = np.isfinite(a)
    if not bool(finite.all()):
        a = np.where(finite, a, 0.0)
    lo = float(np.percentile(a, lo_pct))
    hi = float(np.percentile(a, hi_pct))
    if not np.isfinite(lo) or not np.isfinite(hi) or (hi - lo) < 1e-6:
        # Scene sans contraste utile : repli borne, jamais de division par ~0.
        return (np.clip(a, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
    x = np.clip((a - lo) / (hi - lo), 0.0, 1.0)
    if gamma != 1.0:
        x = np.power(x, gamma)
    return (x * 255.0 + 0.5).astype(np.uint8)


def encode_png(rgb_u8: np.ndarray, *, sharpen: bool = True) -> bytes:
    """Encode un composite uint8 (H, W, 3) en PNG. Rehaussement leger optionnel (Pillow)."""
    from PIL import Image, ImageFilter

    img = Image.fromarray(np.asarray(rgb_u8, dtype=np.uint8))
    if sharpen:
        img = img.filter(ImageFilter.UnsharpMask(radius=1.5, percent=70, threshold=3))
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def display_png(
    rgb: np.ndarray,
    *,
    lo_pct: float = DEFAULT_LO_PCT,
    hi_pct: float = DEFAULT_HI_PCT,
    gamma: float = DEFAULT_GAMMA,
    sharpen: bool = True,
) -> bytes:
    """Chaine complete voie VISION : etirement robuste + gamma + rehaussement + encodage PNG."""
    return encode_png(stretch_to_uint8(rgb, lo_pct, hi_pct, gamma), sharpen=sharpen)
