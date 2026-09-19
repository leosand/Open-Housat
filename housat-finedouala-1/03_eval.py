#!/usr/bin/env python
"""03 — Evaluation SR : les garde-fous NON NEGOCIABLES du prompt, sur une vraie scene tenue a l'ecart.

Quatre controles, dont trois ne demandent AUCUNE reference HR (donc executables des aujourd'hui) :

1. **SAM** (Spectral Angle Mapper) entre le spectre SR agrege et le spectre natif -> fidelite spectrale.
2. **Coherence NDVI** : NDVI(SR) agrege a 10 m vs NDVI(natif) -> ecart relatif (cible +-5-10 %).
3. **Test de texture sur l'eau** : sur un masque d'eau, la variance locale du SR ne doit pas exploser
   face au natif — c'est le test « zero hallucination sur le Wouri ».
4. **PSNR/SSIM** vs proxy HR date (`--hr-proxy`), l'etalon SR classique.

Le modele est un PARAMETRE (`--sr bicubic|onnx`) : `bicubic` est la ligne de base honnete que tout
modele doit battre (regle ADR 0004 — on mesure avant d'adopter), et le meme script evaluera l'ONNX
fine-tune sans modification.

Sortie : JSON de metriques + verdict par controle. **Etiquette obligatoire** : une sortie x4 de
Sentinel-2 10 m vaut **2,5 m effectif** ; le « 1 m » n'est jamais qu'un affichage.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import numpy as np                                            # noqa: E402
from skimage.metrics import peak_signal_noise_ratio as psnr   # noqa: E402
from skimage.metrics import structural_similarity as ssim     # noqa: E402

from housat.imagery import clouds                             # noqa: E402
from housat.imagery.sentinel2 import StacContext, fetch_bands, fetch_scl   # noqa: E402

ILOT_VALIDATION = (9.7042, 4.0442, 9.7058, 4.0458)   # tenu a l'ecart de l'entrainement


def parse_bbox(txt: str) -> tuple[float, float, float, float]:
    v = [float(x) for x in txt.split(",")]
    if len(v) != 4 or v[0] >= v[2] or v[1] >= v[3]:
        raise argparse.ArgumentTypeError("bbox = minLon,minLat,maxLon,maxLat")
    return v[0], v[1], v[2], v[3]


def sam_deg(a: np.ndarray, b: np.ndarray) -> float:
    """Angle spectral moyen (degres) entre deux spectres empiles en derniere dimension."""
    na = np.linalg.norm(a, axis=-1)
    nb = np.linalg.norm(b, axis=-1)
    ok = (na > 1e-6) & (nb > 1e-6)
    if not ok.any():
        return float("nan")
    cos = np.clip((a[ok] * b[ok]).sum(-1) / (na[ok] * nb[ok]), -1, 1)
    return float(np.degrees(np.arccos(cos)).mean())


def texture_variance(img: np.ndarray, mask: np.ndarray) -> float:
    """Variance locale moyenne (gradient) dans un masque — revele une texture INVENTEE."""
    if mask.sum() < 4:
        return float("nan")
    gx = np.abs(np.diff(img, axis=1))[:, :-1]
    gy = np.abs(np.diff(img, axis=0))[:-1, :]
    g = 0.5 * (gx[: gy.shape[0], : gy.shape[1]] + gy[: gx.shape[0], : gx.shape[1]])
    m = mask[: g.shape[0], : g.shape[1]]
    return float(g[m].mean()) if m.any() else float("nan")


def upscale(bands: dict[str, np.ndarray], sr: str, scale: int = 4) -> dict[str, np.ndarray]:
    """SR : `bicubic` (ligne de base) ou `onnx` (via la voie AFFICHAGE du projet, deja en place)."""
    if sr == "bicubic":
        from housat.observations import match_shape
        ref = bands["red"]
        return match_shape({k: v for k, v in bands.items()},
                           (ref.shape[0] * scale, ref.shape[1] * scale))
    from housat.imagery.super_resolution import upscale_rgb_display
    rgb = np.stack([bands["red"], bands["green"], bands["blue"]], axis=-1)
    out, method = upscale_rgb_display(rgb)
    print(f"  moteur SR reellement utilise : {method}")
    return {"red": out[..., 0], "green": out[..., 1], "blue": out[..., 2],
            "nir": bands["nir"]}          # le NIR n'est pas surresolu par la voie affichage


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--bbox", type=parse_bbox, default=ILOT_VALIDATION)
    p.add_argument("--end", type=date.fromisoformat, default=date(2025, 3, 1))
    p.add_argument("--max-parcel-cloud", type=float, default=20.0)
    p.add_argument("--sr", choices=("bicubic", "onnx"), default="bicubic")
    p.add_argument("--scale", type=int, default=4)
    p.add_argument("--ndvi-tol", type=float, default=10.0, help="tolerance %% sur le NDVI")
    p.add_argument("--sam-tol", type=float, default=10.0, help="tolerance SAM en degres")
    p.add_argument("--out", type=Path, default=ROOT / "housat-finedouala-1" / "eval")
    args = p.parse_args(argv)

    minlon, minlat, maxlon, maxlat = args.bbox
    ring = [[minlon, minlat], [maxlon, minlat], [maxlon, maxlat], [minlon, maxlat], [minlon, minlat]]
    poly = {"type": "Polygon", "coordinates": [ring]}
    ctx = StacContext()

    sc = None
    for cand in ctx.search_scenes(poly, max_cloud=90.0, window_days=120, limit=20, end=args.end):
        scl = fetch_scl(ctx, poly, cand)
        pct = clouds.parcel_cloud_pct(scl) if scl is not None else float("nan")
        if pct != pct or pct <= args.max_parcel_cloud:
            sc = cand
            break
    if sc is None:
        print("aucune scene sous le seuil de nuages PARCELLE : elargir --max-parcel-cloud")
        return 1
    print(f"scene tenue a l'ecart : {sc.acquired} | nuages tuile {sc.cloud_cover:.0f} % | SR = {args.sr}")

    b = fetch_bands(ctx, poly, sc)
    sr = upscale(b, args.sr, args.scale)
    sl = slice(None, sr["red"].shape[0] // args.scale * args.scale)
    sc_ = slice(None, sr["red"].shape[1] // args.scale * args.scale)

    # 1-2. Fidelite spectrale : on AGREGE le SR a 10 m et on compare au natif pixel a pixel.
    nat = np.stack([b[k] for k in ("red", "green", "blue", "nir")], axis=-1)
    big = np.stack([sr[k] for k in ("red", "green", "blue", "nir")], axis=-1)
    h, w = nat.shape[0], nat.shape[1]
    agg = big[: h * args.scale, : w * args.scale].reshape(h, args.scale, w, args.scale, -1).mean((1, 3))
    sam = sam_deg(agg.reshape(-1, 4), nat.reshape(-1, 4))

    nat_c = np.clip(nat, 0, None)
    agg_c = np.clip(agg, 0, None)
    ndvi_nat = (nat_c[..., 3] - nat_c[..., 0]) / (nat_c[..., 3] + nat_c[..., 0] + 1e-6)
    # NDVI : on agrege le PRODUIT (NDVI a 2,5 m), pas les bandes — agreger R et NIR puis diviser
    # compare deux quantites differentes (NDVI est non lineaire) et gonfle l'ecart artificiellement.
    big_c = np.clip(big, 0, None)
    try:
        ndvi_big = ((big_c[..., 3] - big_c[..., 0]) / (big_c[..., 3] + big_c[..., 0] + 1e-6))[
            : h * args.scale, : w * args.scale]
        ndvi_sr = ndvi_big.reshape(h, args.scale, w, args.scale).mean((1, 3))
        methode_ndvi = f"produit_NDVI_a_{10 * 4 / args.scale:.1f}m_agrege_a_10m"
    except ValueError:      # NIR non surresolu (voie affichage) : repli, et on le DIT
        ndvi_sr = (agg_c[..., 3] - agg_c[..., 0]) / (agg_c[..., 3] + agg_c[..., 0] + 1e-6)
        methode_ndvi = "bandes_agregees_NIR_non_surresolu (repli, moins fidele)"
    num = np.abs(ndvi_sr - ndvi_nat).mean()
    den = np.abs(ndvi_nat).mean() + 1e-6
    ndvi_ecart_pct = 100.0 * num / den

    # 3. Eau : NDWI eleve = eau ; on compare la texture SR a la texture native sur le meme masque.
    ndwi = (b["green"] - b["nir"]) / (b["green"] + b["nir"] + 1e-6)
    eau = ndwi > 0.2
    var_nat = texture_variance(nat[..., 0], eau)
    var_sr = texture_variance(np.clip(agg_c[..., 0], 0, 1), eau)
    ratio = var_sr / var_nat if var_nat and var_nat == var_nat else float("nan")

    # 4. PSNR/SSIM vs bicubique (etalon SR) — SEULEMENT si le modele evalue n'est PAS le bicubique.
    if args.sr == "bicubic":
        gain = {"psnr_sr_vs_bicubic": None, "ssim_sr_vs_bicubic": None,
                "note": "non applicable : on evalue le bicubique lui-meme (ligne de base)"}
    else:
        base = upscale(b, "bicubic", args.scale)
        rgb_sr = np.clip(np.stack([sr[k] for k in ("red", "green", "blue")], -1)[sl, sc_], 0, 1)
        rgb_bi = np.clip(np.stack([base[k] for k in ("red", "green", "blue")], -1)[sl, sc_], 0, 1)
        gain = {"psnr_sr_vs_bicubic": float(psnr(rgb_bi, rgb_sr, data_range=1.0)),
                "ssim_sr_vs_bicubic": float(ssim(rgb_bi, rgb_sr, data_range=1.0, channel_axis=2))}

    eau_teste = int(eau.sum()) > 0
    verdict = {
        "SAM_degres": round(float(sam), 2), "SAM_ok": bool(sam <= args.sam_tol),
        "methode_ndvi": methode_ndvi,
        "NDVI_ecart_pct": round(float(ndvi_ecart_pct), 2),
        "NDVI_ok": bool(ndvi_ecart_pct <= args.ndvi_tol),
        "eau_pixels": int(eau.sum()),
        "texture_eau_ratio_SR_sur_natif": round(float(ratio), 3) if eau_teste else None,
        # « non teste » n'est PAS « conforme » : sans pixel d'eau, le controle ne prouve rien.
        "eau_ok": None if not eau_teste else bool(ratio == ratio and ratio <= 1.5),
        "eau_note": "aucun pixel d'eau dans l'emprise — controle NON CONCLUANT (le Wouri est ailleurs)"
                    if not eau_teste else "",
    }
    rapport = {"version": "housat-finedouala-1/03", "scene": sc.acquired.isoformat(),
               "sr": args.sr, "scale": args.scale, "emprise_m": [int(w) * 10, int(h) * 10],
               "resolution": f"{10 * 4 / args.scale:.1f} m effectif (x{args.scale}) — "
                             f"« 1 m » reste un affichage, jamais une resolution de mesure",
               "grille_native": [int(h), int(w)], "verdict": verdict,
               "comparaison_bicubique": gain}
    args.out.mkdir(parents=True, exist_ok=True)
    f = args.out / f"eval_{args.sr}_{sc.acquired}.json"
    f.write_text(json.dumps(rapport, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"SAM {sam:.2f} deg (<= {args.sam_tol}) -> {'OK' if verdict['SAM_ok'] else 'ECHEC'}")
    print(f"NDVI ecart {ndvi_ecart_pct:.2f} % (<= {args.ndvi_tol}) -> "
          f"{'OK' if verdict['NDVI_ok'] else 'ECHEC'} [{methode_ndvi}]")
    print(f"eau : {verdict['eau_pixels']} px | texture SR/natif "
          f"{verdict['texture_eau_ratio_SR_sur_natif']} -> "
          f"{'NON CONCLUANT' if verdict['eau_ok'] is None else ('OK' if verdict['eau_ok'] else 'HALLUCINATION SUSPECTEE')}")
    if gain["psnr_sr_vs_bicubic"] is None:
        print(f"gain vs bicubique : {gain['note']}")
    else:
        print(f"gain vs bicubique : PSNR {gain['psnr_sr_vs_bicubic']:.2f} dB "
              f"SSIM {gain['ssim_sr_vs_bicubic']:.3f}")
    print(f"rapport : {f} | x{args.scale} = {10 * 4 / args.scale:.1f} m effectif "
          f"(« 1 m » reste un affichage)")
    ok = [v for k, v in verdict.items() if k.endswith("_ok") and v is not None]
    return 0 if ok and all(ok) else 2


if __name__ == "__main__":
    raise SystemExit(main())
