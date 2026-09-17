#!/usr/bin/env python
"""07 — Entrainement sur VRAIES paires licences propres, sans cle ni habilitation.

Solution alternative a NICFI : le harnais du projet (`benchmark_realpairs`) charge un jeu de paires
**reelles** LR Sentinel-2 <-> HR independant. Son `main()` exige aussi SPOT et VENUS, absents du
depot HuggingFace public (`isp-uv-es/opensr-test`, licence **MIT** ; NAIP = **domaine public USGS**,
30 scenes, LR (30,4,121,121) uint16 -> HR (30,4,484,484), x4).

Ce script reutilise `load_rgb` et `train_real` SANS passer par `main()`, en ne prenant que les
parametres reellement acceptes (introspection) : aucune duplication du harnais, aucun argument devine.

    python housat-finedouala-1/07_realpairs_naip.py --steps 1500
"""

from __future__ import annotations

import argparse
import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from housat.benchmark_realpairs import load_rgb, train_real   # noqa: E402


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--data-dir", type=Path,
                   default=ROOT / "housat-finedouala-1" / "data" / "opensr")
    p.add_argument("--steps", type=int, default=1500)
    p.add_argument("--test-frac", type=float, default=0.25)
    p.add_argument("--ckpt", type=Path,
                   default=ROOT / "housat-finedouala-1" / "checkpoints" / "realpairs_naip.pt")
    args = p.parse_args(argv)

    need = (args.data_dir / "naip-lr.npy", args.data_dir / "naip-hr.npy")
    if not all(f.exists() for f in need):
        print(f"paires NAIP absentes de {args.data_dir} (naip-lr.npy / naip-hr.npy attendus)")
        return 1
    lr, hr = load_rgb(args.data_dir, "naip")
    print(f"paires NAIP : LR {lr.shape} HR {hr.shape} | source = domaine public USGS, dataset MIT")

    # On n'appelle `train_real` qu'avec les parametres qu'il accepte (signature introspectee) :
    # le harnais peut evoluer, ce script ne devine aucun nom d'argument.
    params = inspect.signature(train_real).parameters
    voulus = {"data_dir": args.data_dir, "steps": args.steps, "test_frac": args.test_frac,
              "ckpt": args.ckpt, "sensors": ["naip"], "lr": lr, "hr": hr, "name": "naip"}
    kwargs = {k: v for k, v in voulus.items() if k in params}
    print("parametres transmis :", sorted(kwargs))
    res = train_real(**kwargs)
    print("resultat :", res if not isinstance(res, dict) else
          {k: (round(v, 3) if isinstance(v, float) else v) for k, v in list(res.items())[:12]})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
