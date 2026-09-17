#!/usr/bin/env python
"""02 — Fine-tuning SR x4 Douala (RTX 4070 16 Go), contraintes du prompt appliquees.

**Réutilise** l'existant (ponytail, barreau 2) : `benchmark_finetune.build_pairs` (paires HR proxy ->
LR simulee, le chemin DEJA MESURE : L1, ~8 min GPU, bat Swin2SR), `build_model` (EDSR-lite ~1 M
param.), `grid_bboxes` et `fetch_basemap`. Ce script n'ajoute que ce que le prompt exige et que
`train()` n'a pas : **AMP/FP16, accumulation de gradient, suivi VRAM, et sauvegarde du MEILLEUR
checkpoint uniquement** (contrainte 15 Go), avec PSNR/SSIM de validation.

Deux saisies de paires, honnetement etiquetees :
  synthetic (defaut) : LR = HR proxy sous-echantillonne -> **in-domain**, chiffres optimistes (ADR 0006).
  real               : a venir (LR Sentinel-2 reelles de 01_dataset_douala.py + HR proxy date) ;
                       ADR 0006 predit des scores PLUS BAS en cross-capteur -- ne pas confondre.

Exemple (replis du prompt : petits patchs, batch 2, accumulation x8) :
    python housat-finedouala-1/02_finetune.py --hr-size 256 --batch-size 2 --accum 8 --steps 400
Exemple (valeurs MESUREES ici, plus rapides) :
    python housat-finedouala-1/02_finetune.py --steps 1000
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import numpy as np                                            # noqa: E402
from skimage.metrics import peak_signal_noise_ratio as psnr   # noqa: E402
from skimage.metrics import structural_similarity as ssim     # noqa: E402

from housat.benchmark_finetune import CITIES, build_model, build_pairs   # noqa: E402

DOUALA_CENTRE = (9.705, 4.045)


def ensure_douala() -> str:
    """`build_pairs` s'appuie sur la table CITIES du module existant : on y declare Douala si absente
    (aucune modification du module : on complete sa table, qui est la source unique des emprises)."""
    if "douala" not in CITIES:
        CITIES["douala"] = DOUALA_CENTRE
    return "douala"


def _contours(img: np.ndarray) -> np.ndarray:
    """Magnitude de gradient — meme definition que 05 (support ramene a (H-1, W-1))."""
    g = np.asarray(img, dtype=np.float32).mean(-1)
    gx, gy = np.diff(g, axis=1), np.diff(g, axis=0)
    m = np.zeros_like(g)
    m[:-1, :-1] = 0.5 * (np.abs(gx[:-1, :]) + np.abs(gy[:, :-1]))
    return m


def paires_reelles(dossier: Path, *, gap: float = 0.02):
    """Paires de 04, FILTREES par la sensibilite mesuree en 05 (corr(d=0) maximale et chute >= `gap`).

    Sans ce filtre, on entrainerait sur des paires dont la structure n'est meme pas correlee au bon
    endroit (mesure : la paire a 23 jours d'ecart rendait la metrique AVEUGLE). Dernier fichier
    garde pour la validation : split par SCENE, jamais patch par patch.
    """
    fichiers = sorted(dossier.glob("pairs_*.npz"))
    retenues, ecartees, used = [], [], []
    for f in fichiers:
        z = np.load(f)
        lr, hr = z["lr"], z["hr"]
        c0, c1, c2 = [], [], []
        for i in range(lr.shape[0]):
            g = lr[i] * 255.0
            hr_agg = hr[i].reshape(64, 4, 64, 4, 3).mean((1, 3))
            a = _contours(hr_agg)
            c0.append(np.corrcoef(a.ravel(), _contours(g).ravel())[0, 1])
            for d, acc in ((1, c1), (2, c2)):     # d=1 compte : en 05, la paire « aveugle » avait
                # ORDRE DES OPERATIONS = celui de 05 : on CROPPE les images puis on calcule les
                # contours. Faire l'inverse (contours puis crop, version precedente) decale le
                # support du gradient d'un pixel et produisait un faux desaccord 0,114 vs 0,068 a d=1
                # -- identique a d=0, different des que d>0 : la signature exacte d'un decalage de support.
                # On decale UNIQUEMENT l'image sous test (le LR) : decaler aussi la reference
                # mesurerait leur coherence mutuelle au lieu de la fidelite de l'alignement
                # (constate : d=1 montait a 0,231 au lieu de 0,119).
                gs = np.roll(np.roll(g, d, 0), d, 1)[d:-d, d:-d]
                hs = hr_agg[d:-d, d:-d]
                acc.append(np.corrcoef(_contours(hs).ravel(), _contours(gs).ravel())[0, 1])
        m0, m1, m2 = float(np.mean(c0)), float(np.mean(c1)), float(np.mean(c2))
        # REGLE CALIBREE EN 05 : corr(d=0) doit etre le MAXIMUM et la chute >= gap.
        ok = m0 >= max(m1, m2) and (m0 - max(m1, m2)) >= gap
        mf = f.with_name(f.name.replace("pairs_", "manifest_").replace(".npz", ".json"))
        arch = json.loads(mf.read_text(encoding="utf-8")).get("archive_hr") if mf.exists() else "?"
        print(f"  {f.stem} [archive HR lue : {arch}] : corr d=0 {m0:.3f} | d=1 {m1:.3f} | d=2 {m2:.3f} -> "
              f"{'RETENUE' if ok else 'ECARTEE (metrique non discriminante)'}")
        if ok:
            retenues.extend((lr[i], hr[i]) for i in range(lr.shape[0]))   # cible = HR 256x256, pas
            used.append(f.name)                                            # la version agregee (64)
        else:
            ecartees.append(f.name)
    val = retenues[-1:] if len(retenues) > 1 else []      # dernier fichier = validation
    return retenues[:-1] or retenues, val, used


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--steps", type=int, default=1000)
    p.add_argument("--batch-size", type=int, default=8, help="mesure par defaut ; 2 = repli OOM")
    p.add_argument("--accum", type=int, default=1, help="accumulation de gradient (prompt : 8)")
    p.add_argument("--hr-size", type=int, default=512, help="cote HR ; 256 -> patches LR de 64 px")
    p.add_argument("--grid", type=int, default=5, help="grille d'emprises autour du centre")
    p.add_argument("--val-cities", default="yaounde,kinshasa", help="villes tenues a l'ecart")
    p.add_argument("--val-every", type=int, default=250)
    p.add_argument("--lr", type=float, default=2e-4)
    p.add_argument("--out", type=Path, default=ROOT / "housat-finedouala-1" / "checkpoints")
    p.add_argument("--pairs", choices=("synthetic", "real"), default="synthetic",
                   help="synthetic = paires HR proxy sous-echantillonne (in-domain, ADR 0006 : scores "
                        "optimistes) ; real = paires de 04 (LR Sentinel-2 reelle <-> HR date), "
                        "FILTREES par la sensibilite d'alignement de 05")
    p.add_argument("--pairs-dir", type=Path,
                   default=ROOT / "housat-finedouala-1" / "data" / "pairs")
    p.add_argument("--device", default=None)
    args = p.parse_args(argv)

    import torch
    dev = torch.device(args.device or ("cuda" if torch.cuda.is_available() else "cpu"))
    print(f"device {dev} | AMP {dev.type == 'cuda'} | batch {args.batch_size} x accum {args.accum} "
          f"= effectif {args.batch_size * args.accum} | patches LR {args.hr_size // 4} px")

    city = ensure_douala()
    if args.pairs == "real":
        train_pairs, val_pairs, used = paires_reelles(args.pairs_dir)
        if not train_pairs:
            print("aucune paire retenue par le filtre d'alignement de 05 : relancer 04_pairs_reelles "
                  "avec --hr-source nicfi ou une archive plus proche de la scene")
            return 1
        print(f"paires REELLES retenues : {len(train_pairs)} (train) + {len(val_pairs)} (val) "
              f"sur {len(used)} fichier(s) : {', '.join(used)}")
    else:
        train_pairs = build_pairs([city], grid=args.grid, hr_size=args.hr_size)
        val_pairs = build_pairs(args.val_cities.split(","), grid=2, hr_size=args.hr_size)
        print(f"paires : {len(train_pairs)} entrainement ({city}) | {len(val_pairs)} validation "
              f"({args.val_cities})")

    model = build_model().to(dev).train()
    opt = torch.optim.Adam(model.parameters(), lr=args.lr)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=max(1, args.steps))
    lossf = torch.nn.L1Loss()
    scaler = torch.amp.GradScaler(dev.type, enabled=dev.type == "cuda")
    rng = np.random.default_rng(0)
    args.out.mkdir(parents=True, exist_ok=True)

    def tensor(a: np.ndarray):
        return torch.from_numpy(np.ascontiguousarray(a).astype(np.float32) / 255.0).permute(2, 0, 1)

    @torch.no_grad()
    def evaluate() -> tuple[float, float]:
        model.eval()
        ps, ss = [], []
        for lr_img, hr_img in val_pairs[:8]:
            x = tensor(lr_img).unsqueeze(0).to(dev)
            y = model(x)[0].clamp(0, 1).permute(1, 2, 0).float().cpu().numpy()
            ref = hr_img.astype(np.float32) / 255.0
            ps.append(psnr(ref, y, data_range=1.0))
            ss.append(ssim(ref, y, data_range=1.0, channel_axis=2))
        model.train()
        return float(np.mean(ps)), float(np.mean(ss))

    best = {"psnr": -1.0, "step": 0, "ssim": 0.0}
    hist: list[float] = []
    t0 = time.perf_counter()
    for step in range(args.steps):
        lrs, hrs = [], []
        for i in rng.integers(0, len(train_pairs), size=args.batch_size):
            lr_img, hr_img = train_pairs[i]
            if rng.random() < 0.5:
                lr_img, hr_img = lr_img[:, ::-1], hr_img[:, ::-1]
            k = int(rng.integers(0, 4))
            lrs.append(tensor(np.rot90(lr_img, k)))
            hrs.append(tensor(np.rot90(hr_img, k)))
        x = torch.stack(lrs).to(dev)
        y = torch.stack(hrs).to(dev)
        with torch.amp.autocast(dev.type, enabled=dev.type == "cuda"):
            loss = lossf(model(x), y) / args.accum
        scaler.scale(loss).backward()
        if (step + 1) % args.accum == 0:
            scaler.step(opt)
            scaler.update()
            opt.zero_grad(set_to_none=True)
            sched.step()
        hist.append(float(loss.item()) * args.accum)
        if dev.type == "cuda" and (step + 1) % 100 == 0:
            torch.cuda.empty_cache()

        if (step + 1) % args.val_every == 0 or step + 1 == args.steps:
            vp, vs = evaluate()
            vram = torch.cuda.max_memory_allocated() / 2**30 if dev.type == "cuda" else 0.0
            print(f"  step {step + 1}/{args.steps} L1={np.mean(hist[-args.val_every:]):.4f} "
                  f"| val PSNR {vp:.2f} SSIM {vs:.3f} | VRAM pic {vram:.1f} Go", flush=True)
            if vp > best["psnr"]:      # MEILLEUR checkpoint uniquement (contrainte 15 Go)
                best = {"psnr": vp, "ssim": vs, "step": step + 1}
                torch.save(model.state_dict(), args.out / "best.pt")

    ckpt = args.out / "best.pt"
    rapport = {"device": str(dev), "city": city, "paires_train": len(train_pairs),
               "steps": args.steps, "batch": args.batch_size, "accum": args.accum,
               "hr_size": args.hr_size, "best": best,
               "ckpt": str(ckpt), "ckpt_mo": round(ckpt.stat().st_size / 1e6, 2),
               "secondes": round(time.perf_counter() - t0, 1),
               "pic_vram_go": round(torch.cuda.max_memory_allocated() / 2**30, 2)
               if dev.type == "cuda" else 0.0}
    (args.out / "rapport.json").write_text(json.dumps(rapport, indent=2), encoding="utf-8")
    print("meilleur :", json.dumps(best), f"| checkpoint {rapport['ckpt_mo']} Mo "
          f"| {rapport['secondes']} s | pic VRAM {rapport['pic_vram_go']} Go")
    if args.pairs == "synthetic":
        print("ATTENTION : paires SYNTHETIQUES (in-domain) -> scores optimistes (ADR 0006).")
    else:
        print(f"Paires REELLES filtrees par 05 ({len(train_pairs)} train) — etalons PSNR/SSIM de "
              f"cette echelle non comparables au mode synthetic ; voir 03_eval pour les garde-fous.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
