#!/usr/bin/env python
"""01 — Dataset Douala : scenes Sentinel-2 L2A **qualifiees par parcelle** + masque bati OSM.

Ne reinvente rien (echelle ponytail, barreau 2) : reutilise `housat.imagery.sentinel2` (STAC,
telechargement, SCL), `housat.imagery.clouds` (nuage par parcelle, ADR 0010),
`housat.imagery.buildings` (empreintes OSM ODbL) et `housat.built_dataset` (rasterisation + tuilage).

Ce que ce script fait : telecharger N scenes peu nuageuses **sur la parcelle** (et non sur la tuile),
les empiler en tableaux alignes, rasteriser le masque bati sur LA MEME grille, et journaliser la
taille de chaque artefact. Il ne fait **ni entrainement ni inference**.

Exemple (ilot Housat, 1 scene, verification rapide) :
    python housat-finedouala-1/01_dataset_douala.py \
        --bbox 9.7042,4.0442,9.7058,4.0458 --end 2025-03-01 --limit 1
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))          # importe le paquet housat sans packaging

import numpy as np                                   # noqa: E402

from housat.built_dataset import built_fraction, built_mask   # noqa: E402
from housat.imagery import clouds                    # noqa: E402
from housat.imagery.buildings import fetch_buildings, footprint_stats  # noqa: E402
from housat.imagery.sentinel2 import StacContext, fetch_bands, fetch_scl  # noqa: E402

DOUALA_METROPOLE = (9.60, 3.95, 9.85, 4.15)
ILOT_VALIDATION = (9.7042, 4.0442, 9.7058, 4.0458)


def parse_bbox(txt: str) -> tuple[float, float, float, float]:
    vals = [float(v) for v in txt.split(",")]
    if len(vals) != 4 or vals[0] >= vals[2] or vals[1] >= vals[3]:
        raise argparse.ArgumentTypeError("bbox = minLon,minLat,maxLon,maxLat (min < max)")
    return vals[0], vals[1], vals[2], vals[3]


def polygon_of(bbox: tuple[float, float, float, float]) -> dict:
    minlon, minlat, maxlon, maxlat = bbox
    ring = [[minlon, minlat], [maxlon, minlat], [maxlon, maxlat], [minlon, maxlat], [minlon, minlat]]
    return {"type": "Polygon", "coordinates": [ring]}


def taille(p: Path) -> str:
    return f"{p.stat().st_size / 1e6:.1f} Mo"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--bbox", type=parse_bbox, default=DOUALA_METROPOLE,
                   help="minLon,minLat,maxLon,maxLat (defaut : metropole de Douala)")
    p.add_argument("--end", type=date.fromisoformat, default=date(2025, 3, 1),
                   help="fin de la fenetre seche (YYYY-MM-DD), defaut 2025-03-01")
    p.add_argument("--window-days", type=int, default=120, help="largeur de la fenetre (defaut 120)")
    p.add_argument("--max-tile-cloud", type=float, default=90.0,
                   help="pre-filtre LARGE sur le nuage tuile (defaut 90 %%, cf. ADR 0010)")
    p.add_argument("--max-parcel-cloud", type=float, default=20.0,
                   help="seuil DECISIONNAIRE, juge sur la PARCELLE (SCL, defaut 20 %%)")
    p.add_argument("--limit", type=int, default=12, help="nombre max de scenes retenues")
    p.add_argument("--out", type=Path, default=ROOT / "housat-finedouala-1" / "data")
    args = p.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    poly = polygon_of(args.bbox)
    ctx = StacContext()
    print(f"emprise {args.bbox} | fenetre seche finissant le {args.end} ({args.window_days} j)")

    # Masque bati OSM (ODbL) : la MEME grille pour toutes les dates.
    polys = fetch_buildings(args.bbox)
    st = footprint_stats(polys, args.bbox)
    print(f"OSM : {len(polys)} empreintes | surface batie {st['built_frac'] * 100:.1f} %")

    scenes = ctx.search_scenes(poly, max_cloud=args.max_tile_cloud,
                               window_days=args.window_days, limit=40, end=args.end)
    print(f"candidats (pre-filtre tuile {args.max_tile_cloud:.0f} %) : {len(scenes)}")

    manifest: list[dict] = []
    for sc in scenes:
        if len(manifest) >= args.limit:
            break
        try:                                   # nuage PAR PARCELLE : le seul critere decisionnaire
            scl = fetch_scl(ctx, poly, sc)
            pct = clouds.parcel_cloud_pct(scl) if scl is not None else float("nan")
        except Exception as exc:  # noqa: BLE001 — SCL indisponible : on conserve la scene
            print(f"  {sc.acquired} : SCL indisponible ({type(exc).__name__}) — scene conservee")
            pct = float("nan")
        if pct == pct and pct > args.max_parcel_cloud:
            print(f"  {sc.acquired} : ecartee — nuages PARCELLE {pct:.0f} % "
                  f"> {args.max_parcel_cloud:.0f} % (tuile {sc.cloud_cover:.0f} %)")
            continue

        bands = fetch_bands(ctx, poly, sc)
        shape = bands["red"].shape
        mask = built_mask(polys, args.bbox, shape)          # 1re scene : la grille de reference
        npz = args.out / f"lr_{sc.acquired}.npz"
        np.savez_compressed(npz, **bands)
        manifest.append({"date": sc.acquired.isoformat(), "tile_cloud": round(sc.cloud_cover, 1),
                         "parcel_cloud": None if pct != pct else round(pct, 1),
                         "shape": list(shape), "file": npz.name})
        print(f"  {sc.acquired} : retenue — nuages parcelle "
              f"{'n/d' if pct != pct else f'{pct:.0f} %'} (tuile {sc.cloud_cover:.0f} %) | "
              f"grille {shape} | {taille(npz)}")

    if not manifest:
        print("AUCUNE scene retenue : elargir --max-parcel-cloud ou changer de saison.")
        return 1

    mask_file = args.out / "built_mask.npz"
    np.savez_compressed(mask_file, mask=mask)
    frac = built_fraction(mask)
    print(f"masque bati : {mask_file.name} {taille(mask_file)} | {frac * 100:.1f} % de pixels batis "
          f"(vecteur OSM {st['built_frac'] * 100:.1f} % -> "
          f"{'aligne' if abs(frac - st['built_frac']) < 0.10 else 'ECART A EXPLIQUER'})")

    mf = args.out / "manifest.json"
    mf.write_text(json.dumps({"bbox": args.bbox, "end": args.end.isoformat(),
                              "max_parcel_cloud": args.max_parcel_cloud,
                              "grid_shape": manifest[0]["shape"], "scenes": manifest},
                             indent=2, ensure_ascii=False), encoding="utf-8")
    total = sum(f.stat().st_size for f in args.out.glob("*"))
    print(f"manifest : {len(manifest)} scene(s) | total disque {total / 1e6:.1f} Mo "
          f"(budget 15 Go) | {mf.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
