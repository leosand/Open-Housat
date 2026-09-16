"""Benchmark de surresolution — protocole reproductible, methodes multiples, metriques.
Super-resolution benchmark — reproducible protocol, multiple methods, metrics.

OBJECTIF : trancher « quelle methode SR, sur quel moteur (CPU/GPU), pour la lisibilite de
l'ante/apres » par la MESURE, pas par l'affirmation.

PROTOCOLE (simulated low-resolution, facteur 4) — standard en SR :
  1. Verite-terrain proxy « HR » = Esri World Imagery de l'emprise, ramene a la grille N
     (~2-3 m/px). ATTENTION : ce n'est PAS une verite absolue (autre capteur/date) — c'est un
     PROXY de detail, identique pour toutes les methodes, donc equitable pour les RANGER.
  2. Entree « LR » = HR degrade a N/4 par moyennage d'aire (echantillonnage ~10 m, façon
     Sentinel-2). C'est ce que le pipeline recoit reellement.
  3. Chaque methode remonte LR -> N (facteur 4). Mesure PSNR/SSIM vs HR proxy.
  4. Colonne « source » = Esri natif (plafond de detail, hors benchmark SR).

Le benchmark mesure la capacite a RECONSTRUIRE du detail, pas la verite d'une scene datée.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from housat.imagery.basemap import fetch_basemap

FACTOR = 4


@dataclass
class MethodRun:
    name: str
    device: str
    available: bool
    seconds: float
    psnr: float | None
    ssim: float | None
    note: str = ""


# ----------------------------- metriques (pures) -----------------------------

def psnr(a: np.ndarray, b: np.ndarray) -> float:
    """PSNR (dB) entre deux images uint8 de meme forme. +inf si identiques."""
    x = a.astype(np.float64)
    y = b.astype(np.float64)
    mse = float(np.mean((x - y) ** 2))
    if mse == 0.0:
        return float("inf")
    return float(10.0 * np.log10((255.0 ** 2) / mse))


def ssim(a: np.ndarray, b: np.ndarray) -> float:
    """SSIM (moyenne), via scikit-image si present, sinon repli global normalise."""
    try:
        from skimage.metrics import structural_similarity

        gray_a = np.asarray(Image.fromarray(a).convert("L"))
        gray_b = np.asarray(Image.fromarray(b).convert("L"))
        return float(structural_similarity(gray_a, gray_b, data_range=255))
    except Exception:  # noqa: BLE001 — repli deterministe sans dependance
        x = a.astype(np.float64) / 255.0
        y = b.astype(np.float64) / 255.0
        mux, muy = x.mean(), y.mean()
        vx, vy = x.var(), y.var()
        cxy = float(((x - mux) * (y - muy)).mean())
        c1, c2 = 0.01 ** 2, 0.03 ** 2
        return float(((2 * mux * muy + c1) * (2 * cxy + c2)) / ((mux ** 2 + muy ** 2 + c1) * (vx + vy + c2)))


# ----------------------------- degradations -----------------------------

def to_u8(img01: np.ndarray) -> np.ndarray:
    """[0,1] float -> uint8 [0,255]."""
    return (np.clip(np.asarray(img01, dtype=np.float32), 0, 1) * 255).round().astype(np.uint8)


def area_downsample(img: np.ndarray, out_size: int) -> np.ndarray:
    """Reduction par moyennage d'aire (echantillonnage realiste, anti-alias)."""
    pil = Image.fromarray(img).resize((out_size, out_size), Image.BOX)
    return np.asarray(pil)


def lanczos_resize(img: np.ndarray, out_size: int) -> np.ndarray:
    return np.asarray(Image.fromarray(img).resize((out_size, out_size), Image.LANCZOS))


# ----------------------------- methodes SR -----------------------------

def _m_nearest(lr: np.ndarray, size: int, device: str) -> np.ndarray:
    return np.asarray(Image.fromarray(lr).resize((size, size), Image.NEAREST))


def _m_bicubic(lr: np.ndarray, size: int, device: str) -> np.ndarray:
    from skimage.transform import resize

    out = resize(lr / 255.0, (size, size, 3), order=3, preserve_range=True, anti_aliasing=False)
    return (np.clip(out, 0, 1) * 255).astype(np.uint8)


def _m_swin2sr(lr: np.ndarray, size: int, device: str) -> np.ndarray:
    """Swin2SR x4 (transformers) — modele SR naturel moderne, CPU ou GPU."""
    import torch
    from transformers import Swin2SRForImageSuperResolution, Swin2SRImageProcessor

    model_id = "caidas/swin2SR-classical-sr-x4-64"
    processor = Swin2SRImageProcessor.from_pretrained(model_id)
    model = Swin2SRForImageSuperResolution.from_pretrained(model_id).to(device).eval()
    inputs = processor(images=Image.fromarray(lr), return_tensors="pt").to(device)
    with torch.no_grad():
        out = model(**inputs).reconstruction
    arr = out.squeeze().float().clamp(0, 1).permute(1, 2, 0).cpu().numpy()
    img = (arr * 255).round().astype(np.uint8)
    # Le processeur PADDE l'entree (fenetres) : la sortie fait (lr + pad) * 4. Sans retirer ce
    # cadre, un resize ecrase l'image et fausse la comparaison (bug V&V corrige 2026-09-15).
    if img.shape[0] != size:
        # Le processeur padde a DROITE/BAS (fenetres) : la region utile est en HAUT-GAUCHE.
        # (Un recadrage centre desalignait l'image et faussait toute metrique — bug V&V corrige.)
        img = img[:size, :size]
    return img


def _m_sen2sr(lr: np.ndarray, size: int, device: str) -> np.ndarray:
    """SEN2SR (ESA OpenSR) x4 — modele SR satellite, faibles bandes (RGB repete en NIR)."""
    import sen2sr

    rgb = lr.astype(np.float32) / 255.0
    stack = np.concatenate([rgb, rgb[..., :1]], axis=-1)  # blue,green,red + nir approx (4 bandes)
    sr = np.asarray(sen2sr.predict_large(stack), dtype=np.float32)
    img = (np.clip(sr[..., :3], 0, 1) * 255).astype(np.uint8)
    if img.shape[0] != size:
        img = np.asarray(Image.fromarray(img).resize((size, size), Image.LANCZOS))
    return img


def _m_onnx_sr(lr: np.ndarray, size: int, device: str) -> np.ndarray:
    """SR ONNX (SwinIR / Nomos / Real-ESRGAN) via onnxruntime — modele fourni par HOUSAT_SR_ONNX."""
    import os

    path = os.getenv("HOUSAT_SR_ONNX", "")
    if not path or not os.path.exists(path):
        raise RuntimeError("HOUSAT_SR_ONNX non fourni (chemin du modele .onnx)")
    import onnxruntime as ort

    want = ["CUDAExecutionProvider", "CPUExecutionProvider"] if device == "cuda" else ["CPUExecutionProvider"]
    sess = ort.InferenceSession(path, providers=[p for p in want if p in ort.get_available_providers()])
    x = (lr.astype(np.float32) / 255.0).transpose(2, 0, 1)[None]
    y = sess.run(None, {sess.get_inputs()[0].name: x})[0][0]
    img = (np.clip(y.transpose(1, 2, 0), 0, 1) * 255).astype(np.uint8)
    if img.shape[0] != size:
        img = np.asarray(Image.fromarray(img).resize((size, size), Image.LANCZOS))
    return img


_FT_CACHE: dict = {}


def _m_housat_sr(lr: np.ndarray, size: int, device: str) -> np.ndarray:
    """Modele SR fine-tune (EDSR-lite x4) — poids fournis par HOUSAT_FT_CKPT."""
    import os

    import torch

    from housat.benchmark_finetune import build_model

    path = os.getenv("HOUSAT_FT_CKPT", "")
    if not path or not os.path.exists(path):
        raise RuntimeError("HOUSAT_FT_CKPT non fourni (poids fine-tunes)")
    key = (path, device)
    if key not in _FT_CACHE:
        model = build_model().to(device)
        model.load_state_dict(torch.load(path, map_location=device))
        model.eval()
        _FT_CACHE[key] = model
    model = _FT_CACHE[key]
    x = torch.from_numpy(lr.astype(np.float32) / 255.0).permute(2, 0, 1)[None].to(device)
    with torch.no_grad():
        y = model(x).clamp(0, 1)[0].permute(1, 2, 0).cpu().numpy()
    img = (y * 255).round().astype(np.uint8)
    return img[:size, :size] if img.shape[0] != size else img


METHODS = {
    "nearest": _m_nearest,
    "bicubic": _m_bicubic,
    "swin2sr": _m_swin2sr,
    "sen2sr": _m_sen2sr,
    "onnx_sr": _m_onnx_sr,
    "housat_sr": _m_housat_sr,
}


def run_method(name: str, lr: np.ndarray, size: int, device: str) -> tuple[np.ndarray | None, float, str]:
    """Execute une methode ; retourne (image|None, secondes, note). Jamais d'exception remontee."""
    t0 = time.perf_counter()
    try:
        img = METHODS[name](lr, size, device)
        return img, time.perf_counter() - t0, ""
    except Exception as exc:  # noqa: BLE001 — l'indisponibilite est un RESULTAT, pas un echec
        return None, time.perf_counter() - t0, f"{type(exc).__name__}: {str(exc)[:160]}"


# ----------------------------- planche visuelle -----------------------------

def build_plate(panels: list[tuple[str, np.ndarray]], out_path: Path) -> None:
    h = max(img.shape[0] for _, img in panels)
    label_h = 22
    total_w = sum(img.shape[1] for _, img in panels) + 6 * (len(panels) + 1)
    plate = Image.new("RGB", (total_w, h + label_h + 12), (24, 24, 28))
    draw = ImageDraw.Draw(plate)
    x = 6
    for label, img in panels:
        pil = Image.fromarray(img)
        plate.paste(pil, (x, label_h + 6))
        draw.text((x + 2, 5), label, fill=(240, 240, 240))
        x += pil.width + 6
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plate.save(out_path)


# ----------------------------- orchestration -----------------------------

def benchmark(
    bbox: tuple[float, float, float, float],
    *,
    size: int = 512,
    methods: list[str] | None = None,
    devices: list[str] | None = None,
    out_dir: Path | None = None,
) -> dict:
    methods = methods or ["nearest", "bicubic", "swin2sr", "sen2sr"]
    devices = devices or ["cpu"]
    out_dir = out_dir or Path("benchmarks/results")
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1-2. verite-terrain proxy (HR) + entree LR (facteur 4)
    native = fetch_basemap(bbox, size=size * 2, provider="esri_world_imagery").data
    hr = lanczos_resize(np.asarray(Image.open(_bytes(native)).convert("RGB")), size)
    lr_size = size // FACTOR
    lr = area_downsample(hr, lr_size)

    lr_panel = np.asarray(Image.fromarray(lr).resize((size, size), Image.NEAREST))
    panels: list[tuple[str, np.ndarray]] = [("LR (~10 m)", lr_panel)]
    runs: list[MethodRun] = []
    for device in devices:
        for name in methods:
            img, sec, note = run_method(name, lr, size, device)
            if img is None:
                runs.append(MethodRun(name, device, False, sec, None, None, note))
                continue
            runs.append(MethodRun(name, device, True, sec, round(psnr(img, hr), 3), round(ssim(img, hr), 4), note))
            panels.append((f"{name} [{device}]", img))
    panels.append(("HR proxy (Esri)", hr))

    build_plate(panels, out_dir / "plate.png")
    Image.fromarray(hr).save(out_dir / "hr_proxy.png")
    Image.fromarray(lr).save(out_dir / "lr_input.png")

    result = {
        "bbox": list(bbox),
        "hr_size": size,
        "lr_size": lr_size,
        "factor": FACTOR,
        "runs": [asdict(r) for r in runs],
    }
    (out_dir / "metrics.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def _bytes(data: bytes):
    import io

    return io.BytesIO(data)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Benchmark surresolution (protocole 4x simule)")
    p.add_argument("--bbox", required=True, help="minLon,minLat,maxLon,maxLat")
    p.add_argument("--size", type=int, default=512)
    p.add_argument("--methods", default="nearest,bicubic,swin2sr,sen2sr")
    p.add_argument("--devices", default="cpu")
    p.add_argument("--out-dir", default="benchmarks/results")
    a = p.parse_args(argv)
    bbox = tuple(float(v) for v in a.bbox.split(","))  # type: ignore[assignment]
    res = benchmark(bbox, size=a.size, methods=a.methods.split(","),
                    devices=a.devices.split(","), out_dir=Path(a.out_dir))
    for r in res["runs"]:
        stat = f"PSNR={r['psnr']} SSIM={r['ssim']} t={r['seconds']:.1f}s" if r["available"] else f"ABSENT ({r['note']})"
        print(f"{r['name']:<12} [{r['device']:<4}] {stat}")
    print(f"\nplanche : {Path(a.out_dir) / 'plate.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
