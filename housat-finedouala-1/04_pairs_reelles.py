#!/usr/bin/env python
"""04 — Paires REELLES (LR Sentinel-2 reelle <-> HR d'archive datee) : la brique qui manquait.

Pourquoi c'est indispensable : l'ADR 0006 a mesure que l'entrainement « in-domain » (LR = HR
sous-echantillonne) donne des scores OPTIMISTES et ne tient pas en cross-capteur. Les paires de
`02_finetune.py` sont synthétiques ; celles-ci sont **reelles des deux cotes**.

Methode (aucune reprojection necessaire) : les deux sources sont demandees **sur la meme emprise**
lon/lat, donc le LR (N px) et le HR Proxy (4N px) partagent exactement la meme grille — un patch LR
(r0, c0, 64) correspond au bloc HR (4r0, 4c0, 256). On verifie l'alignement par correlation entre le
HR agrege a 10 m et le LR reel, et on l'ecrit dans le manifeste.

Avertissement consigne : la mosaique d'archive n'est PAS une acquisition du meme jour que la scene
Sentinel-2 (elle est datee, mais composite) — c'est la limite intrinseque des paires cross-capteur.

Exemple :
    python housat-finedouala-1/04_pairs_reelles.py --bbox 9.70,4.04,9.71,4.05 --end 2025-03-01 \
        --patch 64 --max-patches 8
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import numpy as np                                            # noqa: E402
from PIL import Image                                          # noqa: E402

from housat.built_dataset import tiles                        # noqa: E402
from housat.imagery import clouds                             # noqa: E402
from housat.imagery.sentinel2 import StacContext, fetch_bands, fetch_scl   # noqa: E402
from housat.imagery.wayback import fetch_wayback, latest_date_at_or_before  # noqa: E402


def parse_bbox(txt: str) -> tuple[float, float, float, float]:
    v = [float(x) for x in txt.split(",")]
    if len(v) != 4 or v[0] >= v[2] or v[1] >= v[3]:
        raise argparse.ArgumentTypeError("bbox = minLon,minLat,maxLon,maxLat")
    return v[0], v[1], v[2], v[3]


def to_u8(a: np.ndarray) -> np.ndarray:
    return np.clip(a * 255.0, 0, 255).astype(np.uint8)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--bbox", type=parse_bbox, default=(9.70, 4.04, 9.71, 4.05))
    p.add_argument("--end", type=date.fromisoformat, default=date(2025, 3, 1))
    p.add_argument("--patch", type=int, default=64, help="cote du patch LR (HR = 4x)")
    p.add_argument("--max-patches", type=int, default=200)
    p.add_argument("--min-std", type=float, default=0.02, help="ignore les patchs quasi uniformes")
    p.add_argument("--out", type=Path, default=ROOT / "housat-finedouala-1" / "data" / "pairs")
    args = p.parse_args(argv)

    minlon, minlat, maxlon, maxlat = args.bbox
    ring = [[minlon, minlat], [maxlon, minlat], [maxlon, maxlat], [minlon, maxlat], [minlon, minlat]]
    poly = {"type": "Polygon", "coordinates": [ring]}
    ctx = StacContext()

    sc = None
    for cand in ctx.search_scenes(poly, max_cloud=90.0, window_days=120, limit=20, end=args.end):
        scl = fetch_scl(ctx, poly, cand)
        pct = clouds.parcel_cloud_pct(scl) if scl is not None else float("nan")
        if pct != pct or pct <= 20.0:
            sc = cand
            break
    if sc is None:
        print("aucune scene sous 20 % de nuages PARCELLE dans la fenetre")
        return 1

    lr = fetch_bands(ctx, poly, sc)
    lr_rgb = np.stack([lr["red"], lr["green"], lr["blue"]], axis=-1)
    h, w = lr["red"].shape
    hr_date = latest_date_at_or_before(args.bbox, sc.acquired.isoformat())
    if hr_date is None:
        print("aucune imagerie d'archive datee <= scene : paire impossible")
        return 1
    hr_png = fetch_wayback(args.bbox, hr_date, size=4 * max(h, w))
    hr = np.asarray(Image.open(io.BytesIO(hr_png)).convert("RGB"), dtype=np.uint8)
    # `fetch_wayback` renvoie un carre : on recadre au ratio EXACT 4x de la grille LR, sinon la
    # correspondance bloc HR <-> pixel LR derive sur l'axe le plus court (448/111 = 4,036 !).
    hr = hr[: 4 * h, : 4 * w]
    print(f"scene LR {sc.acquired} (nuages tuile {sc.cloud_cover:.0f} %) | grille {h}x{w} | "
          f"archive HR {hr_date} | {hr.shape[0]}x{hr.shape[1]} px")

    args.out.mkdir(parents=True, exist_ok=True)
    lrs, hrs, corrs, fens = [], [], [], []
    for r0, r1, c0, c1 in tiles((h, w), size=args.patch):
        if len(lrs) >= args.max_patches:
            break
        lr_p = lr_rgb[r0:r1, c0:c1]
        hr_p = hr[r0 * 4:r1 * 4, c0 * 4:c1 * 4]
        attendu = (lr_p.shape[0] * 4, lr_p.shape[1] * 4)
        if hr_p.shape[:2] != attendu or lr_p.shape[0] < 8 or hr_p.shape[0] < 32:
            continue
        if float(np.std(lr_p)) < args.min_std:
            continue
        # Alignement : HR agrege a 10 m (moyenne de blocs 4x4) vs LR reel, luminance moyenne.
        k = hr_p.shape[0] // lr_p.shape[0]
        agg = hr_p[: lr_p.shape[0] * k, : lr_p.shape[1] * k].reshape(
            lr_p.shape[0], k, lr_p.shape[1], k, 3).mean((1, 3))
        a = agg.mean(-1).ravel()
        bb = (lr_p.mean(-1) * 255.0).ravel()
        corr = float(np.corrcoef(a, bb)[0, 1]) if a.std() > 1 and bb.std() > 1 else float("nan")
        lrs.append(to_u8(lr_p))
        hrs.append(hr_p)
        corrs.append(corr)
        fens.append([r0, r1, c0, c1])

    if not lrs:
        print("aucun patch exploitable (emprise trop petite pour --patch ?)")
        return 1
    med = float(np.nanmedian(corrs))
    npz = args.out / f"pairs_{sc.acquired}.npz"
    np.savez_compressed(npz, lr=np.stack(lrs), hr=np.stack(hrs))
    mf = args.out / f"manifest_{sc.acquired}.json"
    mf.write_text(json.dumps({"scene_lr": sc.acquired.isoformat(), "archive_hr": hr_date,
                              "bbox": args.bbox, "patch_lr": args.patch,
                              "n_patches": len(lrs), "corr_mediane_hr_vs_lr": round(med, 3),
                              "alignement": "OK" if med >= 0.3 else "DOUTEUX (verifier)",
                              "limite": "mosaique d'archive != acquisition du meme jour",
                              "fenetres": fens}, indent=2), encoding="utf-8")
    print(f"{len(lrs)} paires -> {npz.name} ({npz.stat().st_size / 1e6:.2f} Mo) | "
          f"corr HR/LR mediane {med:.3f} -> "
          f"{'ALIGNE' if med >= 0.3 else 'DOUTEUX : a verifier avant tout entrainement'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
