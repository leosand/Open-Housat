#!/usr/bin/env python
"""06 — Comparateur avant/apres AUTO-PORTANT (LR 10 m <-> SR <-> HR archive) pour l'experimentation.

Pourquoi un HTML autonome et pas tout de suite le composant React : le viewer de production compare
deux cartes datees, et le travail web doit etre valide par build + e2e. Ici on obtient la MEME
demonstration en une commande, sans dependance, sans serveur, sans risque pour `main` — et surtout
**sans mentir sur la resolution** : la mention « x4 neuronal -> 2,5 m effectif, jamais 1 m reel » est
imprimee dans l'image de sortie, pas en petit dans un coin.

Entrees : les paires de 04 (`data/pairs/*.npz`) — LR reel + HR archive, deja alignees et verifiees.
Sortie  : `apercu/comparateur.html` (images en base64, aucun fichier externe).

    python housat-finedouala-1/06_apercu_html.py
"""

from __future__ import annotations

import argparse
import base64
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

import numpy as np                                     # noqa: E402
from PIL import Image, ImageDraw                       # noqa: E402


def b64(arr: np.ndarray, scale: int = 3) -> str:
    """Array uint8 (H, W, 3) -> PNG base64, agrandi par facteur ENTIER (nearest : pas de flou ajoute)."""
    img = Image.fromarray(arr).resize(
        (arr.shape[1] * scale, arr.shape[0] * scale), Image.NEAREST)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def png_bytes(arr: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG")
    return buf.getvalue()


def bandeau(largeur: int, hauteur: int, texte: str, couleur=(255, 255, 255)) -> str:
    """Bandeau d'etiquettes fondu dans l'image : la mention de resolution ne peut pas etre oubliee."""
    img = Image.new("RGB", (largeur, hauteur), (17, 24, 39))
    d = ImageDraw.Draw(img)
    d.text((8, max(2, hauteur // 2 - 6)), texte, fill=couleur)
    return base64.b64encode(png_bytes(np.asarray(img))).decode("ascii")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--pairs", type=Path, default=ROOT / "housat-finedouala-1" / "data" / "pairs")
    p.add_argument("--out", type=Path, default=ROOT / "housat-finedouala-1" / "apercu")
    p.add_argument("--index", type=int, default=0, help="numero de patch a afficher")
    p.add_argument("--zoom", type=int, default=3, help="agrandissement ENTIER (nearest)")
    args = p.parse_args(argv)

    fichiers = sorted(args.pairs.glob("pairs_*.npz"))
    if not fichiers:
        print(f"aucune paire dans {args.pairs} : lancer 04_paires_reelles d'abord")
        return 1
    z = np.load(fichiers[-1])
    i = min(args.index, z["lr"].shape[0] - 1)
    lr, hr = z["lr"][i], z["hr"][i]
    sr = np.asarray(Image.fromarray(lr).resize(
        (lr.shape[1] * 4, lr.shape[0] * 4), Image.BICUBIC))     # etalon : bicubique x4

    # Realignement des trois vues sur la meme taille d'affichage.
    hr_d = np.asarray(Image.fromarray(hr).resize((lr.shape[1] * 4, lr.shape[0] * 4), Image.BILINEAR))
    args.out.mkdir(parents=True, exist_ok=True)
    L, W = lr.shape[0], lr.shape[1]
    # MEME echelle au sol pour les trois vues : le LR est agrandi d'un facteur ENTIER (nearest, donc
    # sans flou ajoute) jusqu'a la taille du HR/SR — sinon on compare des echelles differentes et la
    # demonstration ne veut rien dire.
    eff = 10.0 / 4.0
    img_lr = b64(lr, 4)
    img_sr = b64(sr, 1)
    img_hr = b64(hr_d, 1)
    lbl_lr = bandeau(W * 4, 22, f"Mesure LR - Sentinel-2 natif 10 m ({W} x {L} px)")
    lbl_sr = bandeau(W * 4, 22, f"SR x4 - {eff:.1f} m effectif (reconstruction IA)")
    lbl_hr = bandeau(W * 4, 22, "Lecture - archive datee (usage interne)")

    html = f"""<!doctype html><meta charset="utf-8"><title>Housat — comparateur SR (experimentation)</title>
<style>
 body{{font:14px system-ui;background:#0b1220;color:#e5e7eb;margin:0;padding:16px}}
 h1{{font-size:16px;margin:0 0 4px}} .avert{{color:#fbbf24;margin:0 0 12px}}
 .row{{display:flex;gap:12px;flex-wrap:wrap}}
 figure{{margin:0;flex:1 1 300px;max-width:420px}} figcaption{{font-size:12px;color:#9ca3af}}
 .row img{{display:block;width:100%}}
 .slider{{position:relative;width:min(420px,100%);margin-top:14px}}
 .slider img{{display:block;width:100%}} .top{{position:absolute;inset:0}}
 input[type=range]{{width:100%}}
</style>
<h1>Comparateur avant/apres — patch {i} de {fichiers[-1].name}</h1>
<p class="avert">x4 neuronal -&gt; <b>2,5 m effectif</b>. Le &laquo; 1 m &raquo; serait un affichage :
aucune resolution optique reelle n'est gagnee.</p>
<div class="row">
 <figure><img src="data:image/png;base64,{lbl_lr}"><img src="data:image/png;base64,{img_lr}">
  <figcaption>Mesure : Sentinel-2 natif, 10 m par point.</figcaption></figure>
 <figure><img src="data:image/png;base64,{lbl_sr}"><img src="data:image/png;base64,{img_sr}">
  <figcaption>Sortie SR (ici bicubique x4, l'etalon que tout modele doit battre — ADR 0004).</figcaption></figure>
 <figure><img src="data:image/png;base64,{lbl_hr}"><img src="data:image/png;base64,{img_hr}">
  <figcaption>Lecture : archive datee. Usage interne (licence non redistribuable).</figcaption></figure>
</div>
<div class="slider">
 <img src="data:image/png;base64,{img_lr}">
 <img class="top" id="top" src="data:image/png;base64,{img_hr}" style="clip-path:inset(0 0 0 50%)">
 <input type="range" min="0" max="100" value="50" oninput="document.getElementById('top').style.clipPath='inset(0 0 0 '+this.value+'%)'">
</div>
<p class="avert">Curseur : LR a gauche, HR archive a droite — c'est l'ecart que la SR doit combler.</p>
"""
    f = args.out / "comparateur.html"
    f.write_text(html, encoding="utf-8")
    print(f"comparateur : {f} ({f.stat().st_size / 1e6:.2f} Mo) | patch {i} de {fichiers[-1].name}")
    print("ouvrir : start housat-finedouala-1/apercu/comparateur.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
