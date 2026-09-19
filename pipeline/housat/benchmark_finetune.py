"""Fine-tuning d'un petit modele SR satellite (EDSR-lite x4) sur paires appariees.
Fine-tuning of a small satellite SR model (EDSR-lite x4) on paired data.

APPROCHE : on n'a pas de dataset Sentinel-2 <-> 2,5 m apparie telechargeable sans ~1 To. On
construit donc des paires **HR = imagerie fine (Esri) -> LR = degrade 10 m** (moyennage d'aire),
soit EXACTEMENT l'operateur de degradation du protocole d'evaluation. Entrainement et test
utilisent des VILLES DISJOINTES (split geographique) : c'est la garantie anti-fuite.

LIMITE ASSUMEE (a lire avant tout chiffre) : ce ne sont pas de vraies paires multi-capteurs
(Sentinel-2 reel <-> SPOT/VENUS). Le modele apprend a INVERSE l'operateur de degradation
simule ; les chiffres rangent les methodes entre elles sur ce protocole, ils ne valent pas
comme performance absolue sur de la vraie Sentinel-2.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np

SPAN = 0.0115  # ~1,28 km : LR 128 px ~ 10 m/px (façon Sentinel-2)

# Villes de la ceinture tropicale (coherent avec le produit : diaspora Afrique/Caraibes).
CITIES: dict[str, tuple[float, float]] = {
    "abidjan": (-4.02, 5.32),
    "accra": (-0.19, 5.56),
    "yaounde": (11.50, 3.85),
    "kinshasa": (15.31, -4.32),
    "dakar": (-17.45, 14.69),
    "cotonou": (2.43, 6.37),
}


def grid_bboxes(center: tuple[float, float], span: float = SPAN, grid: int = 5) -> list[tuple]:
    """Grille `grid x grid` d'emprises autour d'un centre (diversite spatiale intra-ville)."""
    lon0, lat0 = center
    step = span * 1.15
    out = []
    for i in range(grid):
        for j in range(grid):
            lon = lon0 + (i - (grid - 1) / 2) * step
            lat = lat0 + (j - (grid - 1) / 2) * step
            out.append((round(lon, 5), round(lat, 5), round(lon + span, 5), round(lat + span, 5)))
    return out


# ----------------------------- modele -----------------------------

def _torch():
    import torch

    return torch


def build_model(ch: int = 64, nblocks: int = 8):
    """EDSR-lite x4 : conv -> N blocs residuels -> deux PixelShuffle(2) -> conv. ~1 M params."""
    torch = _torch()
    nn = torch.nn

    class ResidualBlock(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.body = nn.Sequential(nn.Conv2d(ch, ch, 3, padding=1), nn.ReLU(True), nn.Conv2d(ch, ch, 3, padding=1))

        def forward(self, x):
            return x + self.body(x)

    class EDSRLite(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.head = nn.Conv2d(3, ch, 3, padding=1)
            self.body = nn.Sequential(*[ResidualBlock() for _ in range(nblocks)])
            self.up = nn.Sequential(
                nn.Conv2d(ch, ch * 4, 3, padding=1), nn.PixelShuffle(2), nn.ReLU(True),
                nn.Conv2d(ch, ch * 4, 3, padding=1), nn.PixelShuffle(2), nn.ReLU(True),
                nn.Conv2d(ch, 3, 3, padding=1),
            )

        def forward(self, x):
            return self.up(self.body(self.head(x)))

    return EDSRLite()


# ----------------------------- donnees -----------------------------

def build_pairs(cities: list[str], *, grid: int = 5, hr_size: int = 512) -> list[tuple[np.ndarray, np.ndarray]]:
    """Paires (LR 128, HR hr_size) a partir d'Esri — memes operateurs que le protocole d'eval."""
    from PIL import Image

    from housat.benchmark import area_downsample, lanczos_resize
    from housat.imagery.basemap import fetch_basemap

    lr_size = hr_size // 4
    pairs: list[tuple[np.ndarray, np.ndarray]] = []
    for city in cities:
        for bbox in grid_bboxes(CITIES[city], grid=grid):
            data = fetch_basemap(bbox, size=hr_size * 2, provider="esri_world_imagery").data
            native = np.asarray(Image.open(_io(data)).convert("RGB"))
            hr = lanczos_resize(native, hr_size)
            lr = area_downsample(hr, lr_size)
            pairs.append((lr, hr))
    return pairs


def _io(data: bytes):
    import io

    return io.BytesIO(data)


# ----------------------------- entrainement -----------------------------

def train(
    train_cities: list[str],
    *,
    val_cities: list[str] | None = None,
    steps: int = 4000,
    batch_size: int = 8,
    lr: float = 2e-4,
    grid: int = 5,
    device: str | None = None,
    ckpt: Path = Path("benchmarks/models/housat_sr_x4.pt"),
) -> dict:
    torch = _torch()
    dev = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
    train_pairs = build_pairs(train_cities, grid=grid)
    model = build_model().to(dev).train()
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=steps)
    lossf = torch.nn.L1Loss()
    rng = np.random.default_rng(0)

    def to_tensor(a: np.ndarray) -> "torch.Tensor":
        return torch.from_numpy(a.astype(np.float32) / 255.0).permute(2, 0, 1)

    hist: list[float] = []
    t0 = time.perf_counter()
    for step in range(steps):
        idx = rng.integers(0, len(train_pairs), size=batch_size)
        lrs, hrs = [], []
        for i in idx:
            lr_img, hr_img = train_pairs[i]
            if rng.random() < 0.5:
                lr_img, hr_img = lr_img[:, ::-1], hr_img[:, ::-1]
            k = int(rng.integers(0, 4))
            lr_img, hr_img = np.rot90(lr_img, k), np.rot90(hr_img, k)
            lrs.append(to_tensor(np.ascontiguousarray(lr_img)))
            hrs.append(to_tensor(np.ascontiguousarray(hr_img)))
        x = torch.stack(lrs).to(dev)
        y = torch.stack(hrs).to(dev)
        opt.zero_grad(set_to_none=True)
        loss = lossf(model(x), y)
        loss.backward()
        opt.step()
        sched.step()
        hist.append(float(loss.item()))
        if (step + 1) % max(1, steps // 10) == 0:
            print(f"  step {step + 1}/{steps}  L1={np.mean(hist[-steps // 10:]):.4f}", flush=True)

    ckpt.parent.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), ckpt)
    return {
        "device": str(dev),
        "train_pairs": len(train_pairs),
        "steps": steps,
        "final_l1": float(np.mean(hist[-50:])),
        "seconds": time.perf_counter() - t0,
        "ckpt": str(ckpt),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Fine-tuning SR satellite (EDSR-lite x4)")
    p.add_argument("--train-cities", default="abidjan,accra,yaounde,kinshasa")
    p.add_argument("--steps", type=int, default=4000)
    p.add_argument("--batch-size", type=int, default=8)
    p.add_argument("--grid", type=int, default=5)
    p.add_argument("--ckpt", default="benchmarks/models/housat_sr_x4.pt")
    a = p.parse_args(argv)
    res = train(a.train_cities.split(","), steps=a.steps, batch_size=a.batch_size,
                grid=a.grid, ckpt=Path(a.ckpt))
    print("RESULT", res)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
