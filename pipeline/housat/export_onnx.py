"""Export ONNX du modele SR (EDSR-lite) pour un service web CPU sans torch.
ONNX export of the SR model (EDSR-lite) for a torch-free CPU web service.

Pourquoi : le service (worker + API) tourne dans une image slim **sans torch ni GPU**. ONNX Runtime
CPU (~15 Mo) suffit a servir le modele — c'est la voie **commercialisable** (licence du modele = celle
des donnees d'entrainement ; NAIP = domaine public) et **facilement integrable** au web.

Contrat du graphe (compatible `housat.imagery.super_resolution.OnnxSrBackend`) :
  entree  `input`  : float32 (1, 3, H, W) dans [0, 1]
  sortie  `output` : float32 (1, 3, 4H, 4W)
Axes spatiaux dynamiques (toute taille d'entree).
"""

from __future__ import annotations

import argparse
from pathlib import Path


def export(ckpt: str | Path, out: str | Path, *, opset: int = 17) -> Path:
    """Exporte un checkpoint EDSR-lite en ONNX (poids charges sur CPU, opset donne)."""
    import torch

    from housat.benchmark_finetune import build_model

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    model = build_model()
    model.load_state_dict(torch.load(str(ckpt), map_location="cpu"))
    model.eval()
    dummy = torch.rand(1, 3, 64, 64)
    torch.onnx.export(
        model, dummy, str(out),
        input_names=["input"], output_names=["output"],
        dynamic_axes={"input": {0: "n", 2: "h", 3: "w"}, "output": {0: "n", 2: "H", 3: "W"}},
        opset_version=opset,
    )
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Export ONNX d'un modele SR EDSR-lite")
    p.add_argument("--ckpt", required=True, help="checkpoint .pt (torch)")
    p.add_argument("--out", required=True, help="fichier .onnx de sortie")
    p.add_argument("--opset", type=int, default=17)
    a = p.parse_args(argv)
    out = export(a.ckpt, a.out, opset=a.opset)
    print(f"ONNX ecrit : {out} ({Path(out).stat().st_size / 1e6:.2f} Mo)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
