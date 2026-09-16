#!/usr/bin/env python
"""05 — Calibration du controle d'alignement : ma metrique est-elle seulement SENSIBLE ?

Sans ce test, un « decalage 0,0 px » ne prouve rien : une metrique aveugle renverrait 0,0 px sur des
paires desalignees. On construit donc une **courbe de sensibilite** : on decale volontairement le LR
de delta = 0, 1, 2, 4, 8 px et on mesure la correlation de contours. Si elle chute avec delta, la
metrique discrimine et le rapport precedent (0,0 px) a un sens ; si elle reste plate, il faut la
remplacer avant toute conclusion.

Aucun reseau : travaille sur les paires deja construites par 04 (`data/pairs/*.npz`).

    python housat-finedouala-1/05_calibrer_alignement.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

import numpy as np                                     # noqa: E402

DELTAS = (0, 1, 2, 4, 8)


def contours(img: np.ndarray) -> np.ndarray:
    """Magnitude de gradient (contours) — support ramene a (H-1, W-1) pour gx et gy."""
    g = np.asarray(img, dtype=np.float32).mean(-1)
    gx, gy = np.diff(g, axis=1), np.diff(g, axis=0)
    m = np.zeros_like(g)
    m[:-1, :-1] = 0.5 * (np.abs(gx[:-1, :]) + np.abs(gy[:, :-1]))
    return m


def corr(a: np.ndarray, b: np.ndarray) -> float:
    a, b = a.ravel(), b.ravel()
    if a.std() < 1e-6 or b.std() < 1e-6:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def agreg_hr(hr: np.ndarray, k: int = 4) -> np.ndarray:
    return hr.reshape(hr.shape[0] // k, k, hr.shape[1] // k, k, 3).mean((1, 3))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--pairs", type=Path, default=ROOT / "housat-finedouala-1" / "data" / "pairs")
    p.add_argument("--out", type=Path, default=ROOT / "housat-finedouala-1" / "eval")
    args = p.parse_args(argv)

    fichiers = sorted(args.pairs.glob("pairs_*.npz"))
    if not fichiers:
        print(f"aucune paire dans {args.pairs} : lancer 04_pairs_reelles.py d'abord")
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    rapport = {}
    print(f"{'paire':16s} " + " ".join(f"d={d:<5d}" for d in DELTAS) + " chute  verdict")
    for f in fichiers:
        z = np.load(f)
        lr, hr = z["lr"], z["hr"]
        courbes = []
        for d in DELTAS:
            vals = []
            for i in range(lr.shape[0]):
                # decalage volontaire du LR (diagonale) : la correlation doit chuter si le test voit
                g = np.roll(np.roll(lr[i] * 255.0, d, 0), d, 1)
                if d:                      # bords invalides apres rotation circulaire
                    g = g[d:-d, d:-d]
                    r = agreg_hr(hr[i])[d:-d, d:-d]
                else:
                    g, r = g, agreg_hr(hr[i])
                vals.append(corr(contours(r), contours(g)))
            courbes.append(float(np.nanmean(vals)))
        chute = courbes[0] - max(courbes[1:])
        sensible = chute >= 0.02 and courbes[0] == max(courbes)
        seuil = round(0.6 * courbes[0], 3)
        rapport[f.name] = {"corr_par_delta": dict(zip(map(str, DELTAS), [round(c, 3) for c in courbes])),
                           "chute_max": round(chute, 3), "metrique_sensible": bool(sensible),
                           "seuil_calibre": seuil}
        print(f"{f.stem:16s} " + " ".join(f"{c:<7.3f}" for c in courbes)
              + f" {chute:<6.3f} {'SENSIBLE' if sensible else 'AV E U G L E'}")

    f = args.out / "calibration_alignement.json"
    f.write_text(json.dumps({"deltas_px": list(DELTAS), "rapport": rapport,
                             "regle": "la metrique discrimine si corr(d=0) est le maximum ET que la "
                                      "chute depasse 0,02 ; le seuil d'alignement devient 60 % de "
                                      "corr(d=0), mesure par paire au lieu d'une constante inventee"},
                            indent=2), encoding="utf-8")
    n_sens = sum(1 for v in rapport.values() if v["metrique_sensible"])
    print(f"\n{n_sens}/{len(rapport)} pair(s) avec metrique SENSIBLE -> "
          f"{'le controle de 04 est exploitable' if n_sens == len(rapport) else 'a revoir avant conclusion'}")
    print(f"rapport : {f}")
    return 0 if n_sens == len(rapport) else 2


if __name__ == "__main__":
    raise SystemExit(main())
