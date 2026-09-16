# ADR 0005 — Fine-tuning d'un SR satellite : le domaine bat le générique

Statut : accepté (2026-09-15)

## Contexte

L'ADR 0004 (benchmark) a montré qu'aucun modèle générique ne battait le bicubique sur PSNR, et que
seul Swin2SR améliorait la structure (SSIM). Question restante : un **modèle adapté au domaine**
(petit SR entraîné sur paires satellite) fait-il mieux ? Exigence : le **mesurer** sur sites held-out.

## Méthode

- **Données** : pas de dataset Sentinel-2↔2,5 m apparié téléchargeable sans ~1 To. Paires construites
  **HR = Esri fine → LR = dégradé 10 m** (moyennage d'aire), soit **le même opérateur** que le protocole
  d'évaluation. **Split géographique** : entraînement `abidjan, accra, yaounde, kinshasa` ; test
  **held-out** `Douala`, `Port-au-Prince`.
- **Modèle** : EDSR-lite ×4 (~1 M params, conv → 8 blocs résiduels → 2× PixelShuffle(2) → conv).
- **Entraînement** : L1, Adam, 4000 pas, batch 8 — **~8 min sur RTX 4070 Ti SUPER (GPU)**.

## Résultats (held-out)

| Site | Métrique | bicubic | Swin2SR | housat_sr (fine-tuné) |
|---|---|---|---|---|
| Douala | PSNR | 18,70 | 18,65 | **19,02** |
| Douala | SSIM | 0,559 | **0,653** | 0,613 |
| Port-au-Prince | PSNR | 17,49 | 17,38 | **17,89** |
| Port-au-Prince | SSIM | 0,563 | **0,660** | 0,621 |

Temps : 0,4 s GPU (vs 1,4 s Swin2SR) — ~3,5× plus rapide.

## Décision

1. **Le fine-tuning satellite est retenu** : seul à battre le bicubique sur **PSNR ET SSIM**, et bat
   Swin2SR sur **PSNR**. Un petit modèle **de domaine** (8 min GPU) dépasse un gros modèle générique.
2. **Voie affichage** : `housat_sr` (PSNR) ou Swin2SR (piqué/SSIM) selon l'objectif. **Voie détection
   inchangée : radiométrique, sans modèle perceptuel.**
3. **Le GPU est justifié** : il **entraîne** le modèle (8 min) et **sert** l'inférence (×7).
4. `housat/benchmark_finetune.py` + `benchmarks/README.md` = protocole reproductible ; toute nouvelle
   variante SR doit y être mesurée avant adoption.

## Limites (traçables)

- **Même opérateur de dégradation en train et en test** → le modèle inverse cet opérateur ; le split
  par villes limite la fuite de **contenu**, pas de **dégradation**. Chiffres **optimistes** pour ce
  protocole ; pas valables tels quels sur de la vraie Sentinel-2.
- Vérité-terrain **proxy** (Esri). **SEN2SR non mesuré**. Objectif **L1** → PSNR-optimal, SSIM perfectible.

## Prochaine étape

Fine-tuner sur **vraies paires appariées** (OpenSR-4x / WorldStrat) + **objectif perceptuel**
(SSIM / LPIPS / adversarial) pour un gain **non optimiste** et un meilleur SSIM.

## Alternatives rejetées

| Alternative | Raison |
|---|---|
| Rester sur modèles génériques | SwinIR/Nomos < bicubique ; Swin2SR n'améliore que le SSIM. |
| Télécharger WorldStrat pour ce tour | ~To ; coût disproportionné avant preuve de concept — faite ici à moindre coût. |
| Déployer `housat_sr` sur la voie détection | Toute SR perceptuelle contamine l'indice → jalons faussés (V&V). |
