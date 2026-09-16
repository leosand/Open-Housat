"""Superresolution Sentinel-2 — moteurs enfichables, degradation honnete et tracee.
Super-resolution of Sentinel-2 — pluggable engines, honest and logged degradation.

Deux voies distinctes (garantie V&V d'inalterabilite du signal de detection) :

- **Voie DETECTION** (`upscale_bands`) : reechantillonne les bandes radiometriques servant
  aux indices NDVI/NDBI/BSI et aux jalons M0-M4. Moteur satellite physique SEN2SR (ESA
  OpenSR) si installe, sinon repli **bicubique** honnete (`bicubic_fallback`) — jamais de
  modele perceptuel ici, qui fabriquerait une fausse structure batie.
- **Voie AFFICHAGE** (`upscale_rgb_display`) : composite RGB du PNG avant/apres. Peut
  utiliser un modele perceptuel (Real-ESRGAN ONNX, GPU/CPU) sans consequence metrologique.

Selection par moteur : `HOUSAT_SR_ENGINE` (detection) et `HOUSAT_DISPLAY_SR_ENGINE`
(affichage). `auto` = meilleur moteur disponible, sinon repli bicubique trace.

Correctifs V&V (2026-09-15) : grille unifiee sur la grille SR du rouge (swir16 20 m n'est
jamais envoye au modele) ; ordre physique explicite (jamais `sorted()` : nir/red inverses).
Correctif 2026-09-17 : SEN2SR reellement activable (import paresseux, inference protegee) ;
echec d'inference -> repli bicubique au lieu d'un crash worker ; voie d'affichage GPU ajoutee.
"""

from __future__ import annotations

import logging

import numpy as np

from housat.config import settings

logger = logging.getLogger(__name__)

# Ordre physique Sentinel-2 10 m (B02, B03, B04, B08) — seul jeu supporte par SEN2SR.
SR_BANDS: tuple[str, ...] = ("blue", "green", "red", "nir")
# Bandes 20 m (B11) : upsamplees hors modele, sur la meme grille cible.
LR_BANDS: tuple[str, ...] = ("swir16",)
# Ordre physique complet (pour diagnostic/tests) — JAMAIS sorted().
BAND_ORDER: tuple[str, ...] = ("blue", "green", "red", "nir", "swir16")

# Moteurs voie detection / affichage (valeurs acceptees par la configuration).
SR_ENGINES: tuple[str, ...] = ("auto", "sen2sr", "bicubic")
DISPLAY_SR_ENGINES: tuple[str, ...] = ("auto", "realesrgan", "onnx", "bicubic")

_sen2sr_module: object | None = None
_sen2sr_probed = False


def _sen2sr() -> object | None:
    """Import paresseux et memoise de `sen2sr` (evite de charger torch a l'import du module)."""
    global _sen2sr_module, _sen2sr_probed
    if not _sen2sr_probed:
        _sen2sr_probed = True
        try:
            import sen2sr  # type: ignore
        except Exception:  # noqa: BLE001 — paquet absent ou backend torch indisponible
            _sen2sr_module = None
        else:
            _sen2sr_module = sen2sr
    return _sen2sr_module


def sen2sr_available() -> bool:
    """True si le paquet SEN2SR est importable (modele reel de surresolution satellite)."""
    return _sen2sr() is not None


def resolve_engine(preferred: str | None = None) -> str:
    """Resout le moteur de DETECTION : `sen2sr` si disponible et demande, sinon `bicubic`."""
    name = (preferred or settings.sr_engine or "auto").lower()
    if name in ("auto", "sen2sr") and sen2sr_available():
        return "sen2sr"
    return "bicubic"


def _resize_to(a: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    """Reechantillonnage bilineaire/cubique preserve-range vers `shape`."""
    from skimage.transform import resize

    return resize(a, shape, order=3, anti_aliasing=True,
                  preserve_range=True).astype(np.float32)


def _sen2sr_upscale(bands: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Surresout les bandes 10 m via SEN2SR et aligne les bandes 20 m sur la grille SR."""
    model = _sen2sr()
    if model is None:
        raise RuntimeError("paquet sen2sr indisponible")
    keys = [k for k in SR_BANDS if k in bands]
    if not keys:
        raise RuntimeError("aucune bande 10 m supportee par SEN2SR (B02/B03/B04/B08)")
    stacked = np.stack([bands[k] for k in keys], axis=-1).astype(np.float32)
    sr = np.asarray(model.predict_large(stacked), dtype=np.float32)  # type: ignore[attr-defined]
    out = {k: sr[..., i] for i, k in enumerate(keys)}
    sr_shape = out[keys[0]].shape
    for k in bands:  # bandes 20 m (swir16) : bicubique vers la grille SR
        if k not in out:
            out[k] = _resize_to(bands[k], sr_shape)
    return out


def upscale_bands(
    bands: dict[str, np.ndarray], factor: int = 4, engine: str | None = None
) -> tuple[dict[str, np.ndarray], str]:
    """Surresout et aligne les bandes de DETECTION sur la grille SR de la reference (red).

    Retourne (bandes SR, methode utilisee). Invariant : toutes les bandes de sortie ont la
    meme forme — condition indispensable au calcul d'indices multi-bandes. Un echec
    d'inference SEN2SR (memoire, modele) degrade en bicubique au lieu de rompre le worker.
    """
    # Note V&V : "or" est interdit ici — un ndarray n'a pas de verite booleenne.
    ref = bands["red"] if "red" in bands else next(iter(bands.values()))
    target = (ref.shape[0] * factor, ref.shape[1] * factor)

    if resolve_engine(engine) == "sen2sr":
        try:
            return _sen2sr_upscale(bands), "sen2sr"
        except Exception:  # noqa: BLE001 — panne modele != panne service : repli trace
            logger.warning("SEN2SR a echoue pendant l'inference — repli bicubique", exc_info=True)

    logger.warning("surresolution neuronale indisponible — fallback bicubique, confiance reduite")
    out = {k: (_resize_to(v, target) if v.shape != target else v.astype(np.float32))
           for k, v in bands.items()}
    return out, "bicubic_fallback"


class OnnxSrBackend:
    """Backend ONNX Runtime pour un modele SR perceptuel de type Real-ESRGAN (voie AFFICHAGE).

    Inference par tuiles (memoire GPU/CPU bornee). Entree/sortie NCHW float dans [0, 1].
    La `session` peut etre injectee : la logique de tiling/padding est ainsi testable sans
    poids reels (le modele lui-meme n'est jamais committe — poids non libres / volumineux).
    """

    def __init__(
        self,
        model_path: str | None = None,
        *,
        scale: int = 4,
        tile: int = 256,
        fp16: bool = False,
        providers: list[str] | None = None,
        session: object | None = None,
        input_name: str | None = None,
    ) -> None:
        self.scale = int(scale)
        self.tile = int(tile)
        self.fp16 = bool(fp16)
        self.providers = providers or ["CUDAExecutionProvider", "CPUExecutionProvider"]
        self._model_path = model_path
        self._session = session
        self._input_name = input_name

    def _ensure_session(self) -> object:
        if self._session is not None:
            return self._session
        if not self._model_path:
            raise RuntimeError("aucun modele ONNX fourni (sr_model_path vide)")
        import onnxruntime as ort  # import paresseux : onnxruntime est optionnel

        avail = ort.get_available_providers()
        providers = [p for p in self.providers if p in avail] or ["CPUExecutionProvider"]
        self._session = ort.InferenceSession(self._model_path, providers=providers)
        return self._session

    def _infer(self, nchw: np.ndarray) -> np.ndarray:
        sess = self._ensure_session()
        name = self._input_name or sess.get_inputs()[0].name  # type: ignore[attr-defined]
        x = nchw.astype(np.float16) if self.fp16 else nchw.astype(np.float32)
        out = sess.run(None, {name: x})[0]  # type: ignore[attr-defined]
        return np.asarray(out, dtype=np.float32)

    def upscale(self, rgb: np.ndarray) -> np.ndarray:
        """Surresout un composite (H, W, 3) par tuiles -> (H*scale, W*scale, 3)."""
        arr = np.asarray(rgb, dtype=np.float32)
        if arr.ndim != 3 or arr.shape[2] != 3:
            raise ValueError("upscale attend un tableau (H, W, 3)")
        h, w, _ = arr.shape
        s, t = self.scale, self.tile
        out = np.zeros((h * s, w * s, 3), dtype=np.float32)
        for y in range(0, h, t):
            for x in range(0, w, t):
                tile = arr[y:y + t, x:x + t]
                th, tw = tile.shape[:2]
                # Padding au multiple de l'echelle : certains modeles exigent des dims divisibles.
                ph, pw = (-th) % s, (-tw) % s
                if ph or pw:
                    tile = np.pad(tile, ((0, ph), (0, pw), (0, 0)), mode="edge")
                nchw = np.transpose(tile, (2, 0, 1))[None]
                pred = np.transpose(self._infer(nchw)[0], (1, 2, 0))[:th * s, :tw * s]
                out[y * s:(y + th) * s, x * s:(x + tw) * s] = pred
        return out


def upscale_rgb_display(
    bands: dict[str, np.ndarray],
    *,
    engine: str | None = None,
    model_path: str | None = None,
    scale: int | None = None,
) -> tuple[dict[str, np.ndarray], str]:
    """Voie AFFICHAGE : surresout le composite RGB avant/apres (modele perceptuel optionnel).

    Sans modele configure (`sr_model_path` vide), renvoie le composite inchange
    (`display_passthrough`) : la surresolution d'affichage n'est jamais obligatoire.
    """
    if not all(k in bands for k in ("red", "green", "blue")):
        raise ValueError("composite RGB incomplet (red/green/blue requis)")
    name = (engine or settings.display_sr_engine or "auto").lower()
    path = settings.sr_model_path if model_path is None else model_path
    s = int(scale or settings.sr_scale)
    rgb = np.stack([bands["red"], bands["green"], bands["blue"]], axis=-1).astype(np.float32)

    if name in ("auto", "realesrgan", "onnx") and path:
        try:
            sr = OnnxSrBackend(path, scale=s, tile=settings.sr_tile).upscale(rgb)
            return {"red": sr[..., 0], "green": sr[..., 1], "blue": sr[..., 2]}, "realesrgan"
        except Exception:  # noqa: BLE001 — degradation honnete et tracee, jamais silencieuse
            logger.warning("modele SR d'affichage indisponible — passage direct", exc_info=True)
    return {"red": rgb[..., 0], "green": rgb[..., 1], "blue": rgb[..., 2]}, "display_passthrough"
