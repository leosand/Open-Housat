"""SR sur PAIRES REELLES multi-capteurs (opensr-test) — evaluation NON optimiste.
Super-resolution on REAL paired multi-sensor data (opensr-test) — non-optimistic evaluation.

Contrairement au protocole « simulated-LR » (LR dérivé d'une HR, donc opérateur de dégradation
partagé train/test), ici LR et HR sont des **prises réelles indépendantes** :
- **NAIP** (US) : HR = NAIP (domaine public) ↔ LR = Sentinel-2 L2A réelle — ×4.
- **SPOT** (Airbus) : HR = SPOT 6/7 — ×4 — **licence NC** (non commerciale).
- **VENUS** (CNES) : ×2 (non évalué ici, facteur différent).

Split **spatial** : les images de test sont des localisations distinctes du train (garantie anti-fuite).
Source : `isp-uv-es/opensr-test` (ESA OpenSR) — https://huggingface.co/datasets/isp-uv-es/opensr-test
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import numpy as np

from housat.benchmark import build_plate, psnr, run_method, ssim, to_u8

# Facteur d'echelle par jeu (HR / LR) : NAIP et SPOT sont x4.
SCALES = {"naip": 4, "spot": 4, "venus": 2}
REFLEX = 10000.0  # reflectance Sentinel-2 echelle uint16


def load_rgb(data_dir: Path, name: str) -> tuple[np.ndarray, np.ndarray]:
    """Charge (LR, HR) RGB normalises [0,1] : (N, H, W, 3). Bandes 0-2 = R,G,B ; 3 = NIR."""
    lr = np.load(data_dir / f"{name}-lr.npy")[:, :3].astype(np.float32) / REFLEX
    hr = np.load(data_dir / f"{name}-hr.npy")[:, :3].astype(np.float32) / REFLEX
    lr = np.clip(np.transpose(lr, (0, 2, 3, 1)), 0, 1)
    hr = np.clip(np.transpose(hr, (0, 2, 3, 1)), 0, 1)
    return lr, hr


def _perceptual_components(kind: str, device):
    """Retourne (lpips_fn, discriminator) selon le type de perte (perceptuelle/adversariale)."""
    import torch

    lpips_fn = None
    disc = None
    if kind in ("perceptual", "perceptual_gan"):
        import lpips

        lpips_fn = lpips.LPIPS(net="alex").to(device).eval()
        for prm in lpips_fn.parameters():
            prm.requires_grad_(False)
    if kind == "perceptual_gan":
        nn = torch.nn

        class PatchDisc(nn.Module):
            def __init__(self, ch: int = 48) -> None:
                super().__init__()

                def blk(i: int, o: int, norm: bool = True) -> list:
                    lay: list = [nn.Conv2d(i, o, 4, 2, 1)]
                    if norm:
                        lay.append(nn.BatchNorm2d(o))
                    lay.append(nn.LeakyReLU(0.2, True))
                    return lay

                self.net = nn.Sequential(*blk(3, ch, False), *blk(ch, ch * 2), *blk(ch * 2, ch * 4),
                                         nn.Conv2d(ch * 4, 1, 4, 1, 1))

            def forward(self, x):
                return self.net(x)

        disc = PatchDisc().to(device)
    return lpips_fn, disc


def train_real(
    lr: np.ndarray,
    hr: np.ndarray,
    *,
    steps: int = 3000,
    batch_size: int = 4,
    lrate: float = 2e-4,
    device: str | None = None,
    loss: str = "l1",
    lambda_perc: float = 0.1,
    lambda_adv: float = 0.01,
    ckpt: Path = Path("benchmarks/models/housat_sr_realpairs.pt"),
) -> dict:
    """Fine-tune EDSR-lite x4 sur paires REELLES. `loss` in {l1, perceptual, perceptual_gan}.

    - `l1` : recopie pixel (PSNR-optimal, rendu legerement lisse).
    - `perceptual` : L1 + `lambda_perc` * LPIPS -> pousse la STRUCTURE percue (SSIM).
    - `perceptual_gan` : + `lambda_adv` * adversariale (PatchGAN) -> realisme max, PSNR plus bas.
    """
    import torch

    from housat.benchmark_finetune import build_model

    dev = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
    model = build_model().to(dev).train()
    lpips_fn, disc = _perceptual_components(loss, dev)
    opt = torch.optim.Adam(model.parameters(), lr=lrate)
    opt_d = torch.optim.Adam(disc.parameters(), lr=lrate) if disc is not None else None
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=steps)
    bce = torch.nn.BCEWithLogitsLoss()
    l1 = torch.nn.functional.l1_loss
    rng = np.random.default_rng(0)

    def tt(a: np.ndarray):
        return torch.from_numpy(np.ascontiguousarray(a)).permute(2, 0, 1)

    t0 = time.perf_counter()
    hist: list[float] = []
    for step in range(steps):
        idx = rng.integers(0, lr.shape[0], size=batch_size)
        xs, ys = [], []
        for i in idx:
            a, b = lr[i], hr[i]
            if rng.random() < 0.5:
                a, b = a[:, ::-1], b[:, ::-1]
            k = int(rng.integers(0, 4))
            xs.append(tt(np.ascontiguousarray(np.rot90(a, k))))
            ys.append(tt(np.ascontiguousarray(np.rot90(b, k))))
        x = torch.stack(xs).to(dev)
        y = torch.stack(ys).to(dev)

        if disc is not None:  # etape discriminateur (apprend a distinguer vrai / surresolu)
            with torch.no_grad():
                fake = model(x)
            opt_d.zero_grad(set_to_none=True)
            loss_d = (bce(disc(y), torch.ones_like(disc(y))) +
                      bce(disc(fake), torch.zeros_like(disc(fake))))
            loss_d.backward()
            opt_d.step()

        opt.zero_grad(set_to_none=True)
        fake = model(x)
        rec = l1(fake, y)
        gen = rec
        if lpips_fn is not None:
            gen = gen + lambda_perc * lpips_fn(fake * 2 - 1, y * 2 - 1).mean()
        if disc is not None:
            gen = gen + lambda_adv * bce(disc(fake), torch.ones_like(disc(fake)))
        gen.backward()
        opt.step()
        sched.step()
        hist.append(float(rec.item()))
        if (step + 1) % max(1, steps // 6) == 0:
            print(f"  step {step + 1}/{steps}  L1={np.mean(hist[-max(1, steps // 6):]):.4f}", flush=True)

    ckpt.parent.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), ckpt)
    return {"device": str(dev), "loss": loss, "steps": steps,
            "final_l1": float(np.mean(hist[-50:])), "seconds": time.perf_counter() - t0,
            "ckpt": str(ckpt)}


def evaluate(lr: np.ndarray, hr: np.ndarray, methods: list[str], device: str) -> list[dict]:
    """PSNR/SSIM/LPIPS moyens par methode sur paires REELLES (une image = une localisation).

    Trois familles de metriques : **PSNR** (fidelite pixel), **SSIM** (structure), **LPIPS**
    (perception, orientee « naturel » — plus BAS = mieux). Objectifs perceptuels et de fidelite
    ne s'optimisent PAS ensemble : c'est cet arbitrage qu'on veut rendre visible.
    """
    import lpips as lpips_lib
    import torch

    size = hr.shape[1]
    lp = lpips_lib.LPIPS(net="alex").to(device).eval()

    def _lpips(a_u8: np.ndarray, b_u8: np.ndarray) -> float:
        ta = torch.from_numpy(a_u8.astype(np.float32) / 127.5 - 1).permute(2, 0, 1)[None].to(device)
        tb = torch.from_numpy(b_u8.astype(np.float32) / 127.5 - 1).permute(2, 0, 1)[None].to(device)
        with torch.no_grad():
            return float(lp(ta, tb).item())

    out = []
    for name in methods:
        ps, ss, lps, notes = [], [], [], ""
        for i in range(lr.shape[0]):
            img, _sec, note = run_method(name, to_u8(lr[i]), size, device)
            if img is None:
                notes = note
                break
            h = to_u8(hr[i])
            ps.append(psnr(img, h))
            ss.append(ssim(img, h))
            lps.append(_lpips(img, h))
        out.append({"method": name, "psnr": round(float(np.mean(ps)), 3) if ps else None,
                    "ssim": round(float(np.mean(ss)), 4) if ss else None,
                    "lpips": round(float(np.mean(lps)), 4) if lps else None, "note": notes})
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="SR paires reelles multi-capteurs (opensr-test)")
    p.add_argument("--data-dir", required=True)
    p.add_argument("--steps", type=int, default=3000)
    p.add_argument("--device", default="cuda")
    p.add_argument("--ckpt", default="benchmarks/models/housat_sr_realpairs.pt")
    p.add_argument("--test-frac", type=float, default=0.25)
    p.add_argument("--loss", default="l1", choices=("l1", "perceptual", "perceptual_gan"))
    p.add_argument("--lambda-perc", type=float, default=0.1)
    p.add_argument("--lambda-adv", type=float, default=0.01)
    p.add_argument("--out", default="benchmarks/results_realpairs")
    args = p.parse_args(argv)
    data_dir = Path(args.data_dir)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    naip_lr, naip_hr = load_rgb(data_dir, "naip")
    n = naip_lr.shape[0]
    perm = np.random.default_rng(0).permutation(n)
    n_test = max(1, int(round(n * args.test_frac)))
    test_ids, train_ids = perm[:n_test], perm[n_test:]
    print(f"NAIP : {n} images | train {len(train_ids)} | test {len(test_ids)} (split spatial)")

    tr = train_real(naip_lr[train_ids], naip_hr[train_ids], steps=args.steps,
                    device=args.device, loss=args.loss, lambda_perc=args.lambda_perc,
                    lambda_adv=args.lambda_adv, ckpt=Path(args.ckpt))
    print("TRAIN", tr)
    os.environ["HOUSAT_FT_CKPT"] = str(Path(args.ckpt).resolve())

    methods = ["bicubic", "swin2sr", "housat_sr"]
    results: dict = {"train": tr, "eval": {}}

    # 1) test held-out NAIP (meme capteur, localisations disjointes)
    results["eval"]["naip_test"] = evaluate(naip_lr[test_ids], naip_hr[test_ids], methods, args.device)
    # 2) generalisation cross-capteur : SPOT (Airbus, NC) entraine sur NAIP (public domain)
    spot_lr, spot_hr = load_rgb(data_dir, "spot")
    results["eval"]["spot_cross_sensor"] = evaluate(spot_lr, spot_hr, methods, args.device)

    for split, rows in results["eval"].items():
        print(f"--- {split} ---")
        for r in rows:
            stat = f"PSNR={r['psnr']} SSIM={r['ssim']}" if r["psnr"] is not None else f"ABSENT ({r['note']})"
            print(f"  {r['method']:<11} {stat}")

    (out_dir / "metrics.json").write_text(json.dumps(results, indent=2), encoding="utf-8")

    # planche : un echantillon de test NAIP
    i = 0
    panels = [("LR reel (S2)", to_u8(naip_lr[test_ids][i]))]
    for name in methods[1:]:
        img, _s, _n = run_method(name, to_u8(naip_lr[test_ids][i]), naip_hr.shape[1], args.device)
        if img is not None:
            panels.append((name, img))
    panels.append(("HR reel (NAIP)", to_u8(naip_hr[test_ids][i])))
    build_plate(panels, out_dir / "plate.png")
    print(f"planche : {out_dir / 'plate.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
