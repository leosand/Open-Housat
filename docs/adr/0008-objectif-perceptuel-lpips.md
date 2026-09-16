# ADR 0008 — Objectif perceptuel (LPIPS/adversarial) : gains LPIPS, pas SSIM

Statut : accepté (2026-09-15)

## Contexte

Objectif (b) : pousser la qualité **perçue** de l'image avant/après (rendu plus net/convaincant) via
une perte perceptuelle. Hypothèse initiale à tester : « LPIPS/adversarial fera monter le **SSIM** ».
Méthode : `train_real(..., loss="perceptual")` = **L1 + λ·LPIPS** (`lambda_perc=0.1`), et variante
`perceptual_gan` ajoutant un **PatchGAN** (`lambda_adv`). Entraînement sur paires **réelles NAIP**
(22 images, 3000 pas, ~3 min GPU), split spatial, évaluation à **trois familles de métriques**.

## Résultats (3 métriques — NAIP test in-domain / SPOT cross-capteur)

| Méthode | PSNR | SSIM | LPIPS ↓ | (NAIP / SPOT) |
|---|---|---|---|---|
| bicubic | 39,38 | 0,9431 | 0,2947 | NAIP |
| Swin2SR | 40,05 | 0,9507 | 0,2488 | NAIP |
| housat_sr **L1** | **40,44** | **0,9508** | 0,2297 | NAIP |
| housat_sr **perceptuel** | 39,69 | 0,9392 | **0,0881** | NAIP |
| bicubic | 35,21 | 0,8586 | 0,4385 | SPOT |
| Swin2SR | **35,24** | **0,8706** | 0,3807 | SPOT |
| housat_sr L1 | 33,23 | 0,8579 | 0,3784 | SPOT |
| housat_sr **perceptuel** | 32,22 | 0,8318 | **0,1831** | SPOT |

## Décision

1. **L'hypothèse « LPIPS pousse le SSIM » est FAUSSE** — le perceptuel **baisse** PSNR *et* SSIM.
   Explication : PSNR/SSIM mesurent la fidélité à la référence ; LPIPS récompense un rendu « naturel »
   qui **s'écarte** de la référence. Ce sont des notions **distinctes**, non redondantes.
2. **Le perceptuel DOMINE le LPIPS** (~**2,6×** meilleur en in-domain, ~2× cross-capteur) — c'est
   précisément l'objectif (b) : une image **perceptuellement** bien meilleure.
3. **Arbitrage fidélité ↔ perception, mesuré, pas supposé.** Trois optimums différents :
   `L1` → PSNR/SSIM ; `perceptuel` → LPIPS ; `Swin2SR` → compromis **portable** (meilleur cross-capteur).
4. **Voie AFFICHAGE = modèle perceptuel** (le client regarde, ne mesure pas) ; **voie DÉTECTION
   inchangée** (radiométrique). Les deux modèles sont livrés en ONNX :
   `housat_sr_x4.onnx` (perceptuel, défaut affichage) et `housat_sr_l1_x4.onnx` (fidélité).
5. **Endpoint de contrôle `/sr/preview?bbox=…`** : PNG [LR 10 m | SR ONNX | HR natif] — teste la SR
   dans un navigateur, pour toute emprise, sans dépendre des scènes Sentinel-2 ni de la base.

## Conséquences

- Message corrigé : (b) n'améliore pas le SSIM, il améliore le **LPIPS** — et c'est ce qu'on veut pour
  l'affichage. Le rapport de benchmark reflète les **trois** métriques.
- `housat_sr_x4.onnx` (perceptuel) est le modèle d'affichage par défaut du service (ONNX CPU, sans torch).
- Toute nouvelle variante SR = mesurée sur les **trois** métriques (PSNR/SSIM/LPIPS) + deux protocoles.

## Limites

Jeu de test **petit** (8 NAIP / 12 SPOT) ; **LPIPS = AlexNet** entraîné sur photos **naturelles** —
proxy imparfait pour la télédétection ; modèle livré **US (NAIP)** ; le perceptuel **invente** du détail
→ **interdit sur les indices de jalons** (voie détection).
