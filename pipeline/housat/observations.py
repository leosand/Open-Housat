"""Observations : serialisation des frames + indicateurs V&V phenomenologiques.

Frames : npz compresse float16 (stocke BYTEA) — scene d'ancrage t0 + derniere scene.
Indicateurs (spec MVP-l1) :
  PV  = partie positive du delta d'indice vs t0, tronquee sur l'anneau externe (ring)
  emprise robuste m = { PV > q80(PV>0) }
  progression entre periodes = 100 * pv_sum(t2) / pv_sum(t1), cap 130 %
  pivot qualifie : dPRA > 0.15 ET |moyenne negative| << PRA
"""

from __future__ import annotations

import io

import numpy as np

EPS = 1e-6


def dump_frame(bands: dict[str, np.ndarray]) -> bytes:
    buf = io.BytesIO()
    np.savez_compressed(buf, **{k: v.astype(np.float16) for k, v in bands.items()})
    return buf.getvalue()


def load_frame(data: bytes) -> dict[str, np.ndarray]:
    with np.load(io.BytesIO(data)) as z:
        return {k: z[k].astype(np.float32) for k in z.files}


def match_shape(bands: dict[str, np.ndarray], ref_shape: tuple[int, int]) -> dict[str, np.ndarray]:
    """Aligne les bandes sur la geometrie de l'ancre (bilineaire).
    Corrige le desalignement de grille latent : fenetres de clip decalees d'un pixel
    selon les dates => comparaisons indice-a-indice faussees (bug V&V, cf. verification.md).
    Co-registration geodesique fine = phase 2."""
    from skimage.transform import resize

    out: dict[str, np.ndarray] = {}
    for k, v in bands.items():
        if v.shape != ref_shape:
            out[k] = resize(v, ref_shape, order=1, preserve_range=True,
                            anti_aliasing=False).astype(np.float32)
        else:
            out[k] = v
    return out


def truncate_ring(a: np.ndarray, ring: int = 1) -> np.ndarray:
    out = a.copy()
    out[:ring, :] = 0.0
    out[-ring:, :] = 0.0
    out[:, :ring] = 0.0
    out[:, -ring:] = 0.0
    return out


def pv_div(anchor: np.ndarray, current: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Retourne (PV positive tronquee, div signe) pour un indice."""
    div = (current - anchor).astype(np.float32)
    return truncate_ring(np.clip(div, 0.0, None)), truncate_ring(div)


def robust_frac(pv: np.ndarray, q: float = 0.8) -> float:
    pos = pv[pv > 0]
    if pos.size == 0:
        return 0.0
    return float((pv > np.quantile(pos, q)).mean())


def robust_frac_joint(pvs: list[np.ndarray], q: float = 0.8) -> float:
    masks = []
    for pv in pvs:
        pos = pv[pv > 0]
        masks.append(pv > (np.quantile(pos, q) if pos.size else np.inf))
    return float(np.logical_or.reduce(masks).mean())


def masked_sum(d: np.ndarray, q: float = 0.8) -> float:
    """Somme sur le masque robuste { d > q80(d>0) }."""
    pos = d[d > EPS]
    if pos.size == 0:
        return 0.0
    m = d > np.quantile(pos, q)
    return float(d[m].sum())


def compute_div_progress(div0: np.ndarray, div_t: np.ndarray, cap: float = 1.3) -> float:
    """%age divPV0/divPV_t (cap 130). < 100 => pivot negatif ; >> 100 => croissance + pivot positif."""
    s0, st = masked_sum(div0), masked_sum(div_t)
    if st <= EPS:
        return 0.0
    return 100.0 * min(s0 / st, cap)


def detect_pivot_pv(div: np.ndarray, pv_t: np.ndarray, *, eps: float = 1e-3) -> dict[str, float | bool]:
    """Pivot qualifie : dPRA > 0.15 et queue negative negligeable (|moyenne| << PRA)."""
    pos, neg = div > eps, div < -eps
    dpra = float(div[pos].sum() / max(float(pv_t[pos].sum()), EPS)) if pos.any() else 0.0
    mean_neg = float(div[neg].mean()) if neg.any() else 0.0
    qualifie = bool(dpra > 0.15 and neg.any() and abs(mean_neg) < 0.05)
    return {"dpra": dpra, "mean_neg": mean_neg, "qualifie": qualifie}


def milestone_decision(
    pvs0: list[np.ndarray],
    pvs_t: list[np.ndarray],
    divs: list[np.ndarray],
) -> tuple[int, bool, float]:
    """Decision de jalon avec V&V pivot — retourne (M0..M4, pivot_confirme, croissance)."""
    growth = robust_frac_joint(pvs_t) - robust_frac_joint(pvs0)
    pivots = [bool(detect_pivot_pv(d, pv)["qualifie"]) for d, pv in zip(divs, pvs_t)]
    any_pivot = any(pivots)
    activity = float(np.mean([np.abs(d).mean() for d in divs]))
    if any_pivot and growth > 0.01:
        return 2, True, growth
    if any_pivot:
        return 3, True, growth
    if growth > 0.02:
        return 1, False, growth
    if robust_frac_joint(pvs_t) > 0.25 and activity < 0.01:
        return 4, False, growth
    return 0, False, growth


def image_png_rgb(bands: dict[str, np.ndarray], clip_hi: float = 0.35) -> bytes:
    """Composite RGB PNG (Pillow) pour vignette dashboard."""
    from PIL import Image

    rgb = np.stack([bands["red"], bands["green"], bands["blue"]], axis=-1)
    rgb8 = (np.clip(rgb / clip_hi, 0, 1) * 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(rgb8).save(buf, format="PNG", optimize=True)
    return buf.getvalue()
