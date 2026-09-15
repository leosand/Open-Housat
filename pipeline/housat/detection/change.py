"""Detection de changements bi-temporelle sur indices spectraux.
Bi-temporal change detection on spectral indices (NDVI/NDBI/BSI).
Fallback non-supervise PCA + k-means inspire de abhijeet3922/Change-Detection-in-Satellite-Imagery.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

_EPS = 1e-6


def ndvi(b: dict[str, np.ndarray]) -> np.ndarray:
    return (b["nir"] - b["red"]) / (b["nir"] + b["red"] + _EPS)  # vegetation


def ndbi(b: dict[str, np.ndarray]) -> np.ndarray:
    return (b["swir16"] - b["nir"]) / (b["swir16"] + b["nir"] + _EPS)  # bati / built-up


def bsi(b: dict[str, np.ndarray]) -> np.ndarray:
    num = (b["swir16"] + b["red"]) - (b["nir"] + b["blue"])
    den = (b["swir16"] + b["red"]) + (b["nir"] + b["blue"]) + _EPS
    return num / den  # sol nu / bare soil — utile pour la phase fondation


def feature_stack(b: dict[str, np.ndarray]) -> np.ndarray:
    """Empile (H, W, 3) : NDVI, NDBI, BSI — base du score de changement."""
    return np.stack([ndvi(b), ndbi(b), bsi(b)], axis=-1)


@dataclass
class ChangeResult:
    score: float            # fraction de pixels changes [0,1]
    changed_pixels: int
    total_pixels: int
    delta_ndbi_mean: float  # progression du bati (positif = construction)
    delta_bsi_mean: float   # positif = sol nu apparait (fondations)
    method: str


def change_score(
    prev: dict[str, np.ndarray],
    curr: dict[str, np.ndarray],
    *,
    threshold_sigma: float = 2.0,
) -> ChangeResult:
    """Score robuste : magnitude du delta de features, seuil = mu + k*sigma adaptatif au site.
    Seuil adaptatif = mitigation des faux positifs saisonniers (cf. architecture.md).
    """
    d = np.linalg.norm(feature_stack(curr) - feature_stack(prev), axis=-1)
    thresh = float(d.mean() + threshold_sigma * d.std())
    mask = d > thresh
    total = int(d.size)
    changed = int(mask.sum())
    return ChangeResult(
        score=changed / max(total, 1),
        changed_pixels=changed,
        total_pixels=total,
        delta_ndbi_mean=float(ndbi(curr).mean() - ndbi(prev).mean()),
        delta_bsi_mean=float(bsi(curr).mean() - bsi(prev).mean()),
        method="adaptive_sigma",
    )


def pca_kmeans_change(prev: dict[str, np.ndarray], curr: dict[str, np.ndarray], n_blocks: int = 25) -> np.ndarray:
    """Masque binaire de changement non supervise (PCA + k-means sur blocs) — secours/validation croisee.
    Unsupervised binary change mask, adapte de la methode PCA/k-means classique.
    """
    from sklearn.cluster import KMeans
    from sklearn.decomposition import PCA

    diff = np.abs(feature_stack(curr) - feature_stack(prev)).mean(axis=-1)
    h, w = diff.shape
    gh = max(1, h // n_blocks)
    gw = max(1, w // n_blocks)
    blocks = [
        diff[i : i + gh, j : j + gw].ravel()
        for i in range(0, h - gh + 1, gh)
        for j in range(0, w - gw + 1, gw)
    ]
    X = np.stack(blocks)
    Xp = PCA(n_components=min(3, X.shape[1])).fit_transform(X)
    labels = KMeans(n_clusters=2, n_init=10, random_state=42).fit_predict(Xp)
    # Le cluster « changement » = celui a la magnitude moyenne la plus forte
    means = [diff_blocks_mean for diff_blocks_mean in (X[labels == k].mean() for k in range(2))]
    changed_label = int(np.argmax(means))
    mask = (labels == changed_label).reshape(h // gh, w // gw)
    return mask
