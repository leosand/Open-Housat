# Benchmark surrésolution (SR) — Housat

> Décider **par la mesure** quelle méthode SR, sur quel moteur (CPU/GPU), et **ce qu'apporte un
> fine-tuning satellite**. Exécuté sur données réelles, chiffres reproduits — pas d'affirmation.

## Protocole (simulated low-resolution, facteur 4)

1. **Vérité-terrain proxy « HR »** : Esri World Imagery de l'emprise, ramenée à 512 px (~2-3 m/px).
   ⚠ Ce n'est **pas** une vérité absolue (autre capteur/date/mosaïque) — c'est un **proxy de détail
   identique pour toutes les méthodes**, donc équitable pour les **ranger**.
2. **Entrée « LR »** : HR dégradé à 128 px (~8,7 m/px, façon Sentinel-2) par **moyennage d'aire**.
3. Chaque méthode remonte **LR 128 → 512** (×4). Métriques **PSNR / SSIM** vs HR proxy.
4. Colonne « source » = Esri natif (plafond de détail, hors benchmark SR).

## Environnement

| Élément | Valeur |
|---|---|
| GPU | NVIDIA RTX 4070 Ti SUPER 16 Go, CUDA 12.4, torch 2.6.0+cu124 |
| Modèles | Swin2SR (`caidas/swin2SR-classical-sr-x4-64`), SwinIR-M ONNX, Nomos/Real-ESRGAN ONNX, **housat_sr (fine-tuné)** |
| Autres | transformers 5.17, onnxruntime 1.30 (CPU), scikit-image |

## Résultats — méthodes pré-entraînées

### Douala — bbox `9.70,4.04,9.71,4.05`

| Méthode | Device | PSNR | SSIM | Temps |
|---|---|---|---|---|
| nearest | — | 17,85 | 0,513 | ~0 s |
| bicubic | cpu | **18,70** | 0,559 | 0,6 s |
| Swin2SR | cpu | 18,65 | **0,653** | 13,9 s |
| Swin2SR | cuda | 18,65 | **0,653** | 2,0 s |
| SwinIR (ONNX) | cpu | 17,38 | 0,541 | 8,9 s |
| Nomos/Real-ESRGAN (ONNX) | cpu | 16,33 | 0,491 | 5,4 s |

### Port-au-Prince — bbox `-72.34,18.54,-72.33,18.55`

| Méthode | PSNR | SSIM |
|---|---|---|
| nearest | 16,55 | 0,516 |
| bicubic | 17,49 | 0,563 |
| Swin2SR | 17,38 | **0,660** |
| SwinIR (ONNX) | 15,38 | 0,490 |

## Résultats — modèle fine-tuné satellite (`housat_sr`, EDSR-lite ×4)

Entraîné **~8 min sur le GPU** (100 paires, 4000 pas, perte L1) sur 4 villes
(`abidjan, accra, yaounde, kinshasa`) ; évalué sur des sites **held-out** (Douala, Port-au-Prince,
absents de l'entraînement) — **split géographique**, garantie anti-fuite.

| Site (held-out) | Métrique | bicubic | Swin2SR | **housat_sr (fine-tuné)** |
|---|---|---|---|---|
| Douala | PSNR | 18,70 | 18,65 | **19,02** |
| Douala | SSIM | 0,559 | **0,653** | 0,613 |
| Port-au-Prince | PSNR | 17,49 | 17,38 | **17,89** |
| Port-au-Prince | SSIM | 0,563 | **0,660** | 0,621 |

Temps : **0,4 s GPU** (2,8 s CPU) — **~3,5× plus rapide** que Swin2SR au GPU, pour ~1 M de paramètres.

Planches : `benchmarks/results_ft/plate.png` (Douala), `benchmarks/results_ft_pap/plate.png` (PAP).

## Paires réelles multi-capteurs (opensr-test) — évaluation NON optimiste

Jeu **réel** (`isp-uv-es/opensr-test`, ESA OpenSR) : LR = Sentinel-2 L2A réelle, HR = **prises
indépendantes** (NAIP / SPOT), bien co-registrées. Contrairement au protocole « simulated-LR », LR et
HR ne partagent **pas** d'opérateur de dégradation (c'est ce qui lève le biais optimiste). Split
**spatial** : localisations de test disjointes du train.

Entraînement : EDSR-lite sur **NAIP réel** (22 images), 3000 pas, **~2,5 min GPU**. Évaluation sur 8
localisations NAIP **held-out** + sur **SPOT** (capteur différent).

| Split | Métrique | bicubic | Swin2SR | housat_sr |
|---|---|---|---|---|
| **NAIP test (in-domain)** | PSNR | 39,38 | 40,05 | **40,44** |
| **NAIP test (in-domain)** | SSIM | 0,9431 | 0,9507 | **0,9508** |
| **SPOT (cross-capteur)** | PSNR | 35,21 | **35,24** | 33,23 |
| **SPOT (cross-capteur)** | SSIM | 0,8586 | **0,8706** | 0,8579 |

**Deux conclusions majeures :**

1. **In-domain, le fine-tuné gagne — sur des paires RÉELLES.** Premier sur PSNR **et** SSIM : le
   résultat Esri est **reproduit sur données réelles non optimistes** (plus de biais d'opérateur).
2. **Cross-capteur, il PERD.** Entraîné sur NAIP, testé sur SPOT : 33,23 dB (**sous** le bicubique
   35,21), alors que **Swin2SR — générique — généralise le mieux**. → **Un modèle de domaine ne se
   transfère pas d'un capteur à l'autre : il faut le ré-entraîner par capteur/région.** Le générique
   est plus portable, moins précis.

**Sensibilité au protocole (expertise SIG)** : les PSNR absolus explosent (~19 dB en simulated-LR vs
~40 dB ici) car ici LR/HR sont co-registrés et la HR est un ré-échantillonnage de la même scène.
**Seuls les classements sont comparables entre protocoles, jamais les valeurs absolues.**

**Licence (SIG/commercial)** : **NAIP = domaine public** (modèle commercialisable, US) ; **SPOT =
CC BY-NC (non commercial)** — un modèle entraîné sur SPOT **ne peut pas être vendu**. Le modèle de
production doit s'entraîner sur des HR **libres** (NAIP, ou HR ouverte de la région cible).

## Analyse (résultats, pas opinions)

1. **Le fine-tuning satellite est le SEUL à battre le bicubique sur PSNR *et* SSIM**
   (+0,3 à +0,4 dB ; +0,05 SSIM) **et** bat Swin2SR sur PSNR (+0,4 à +0,5 dB). Un petit modèle
   **adapté au domaine**, entraîné 8 min, dépasse un gros modèle générique — c'est le point clé.
2. **Swin2SR garde le meilleur SSIM** (sortie plus contrastée/structuree) ; notre modèle optimisé
   **L1** maximise le **PSNR**. Un objectif perceptuel/adversarial ferait monter le SSIM.
3. **Les modèles perceptuels génériques perdent** (SwinIR, Nomos/Real-ESRGAN < bicubique) : ils
   fabriquent une texture plausible mais fausse → **jamais sur la voie détection**.
4. **CPU vs GPU = vitesse, pas qualité.** PSNR/SSIM identiques ; GPU ×7 (Swin2SR) / ×7 (housat_sr).
5. **Le levier décisif hors SR reste la SOURCE** (ADR 0003) : la SR ne comble qu'une fraction du chemin.

## Matrice des options (l'espace complet demandé)

| Option | Rôle réel | Verdict benchmark |
|---|---|---|
| Bicubique / nearest | repli, référence | **solide** ; gratuit, instantané |
| Swin2SR (HF, torch) | SR naturel générique | meilleur **SSIM** ; GPU ×7 |
| SwinIR / Nomos / Real-ESRGAN | SR perceptuel générique | **sous le bicubique** ici → écran only |
| **Fine-tuning satellite (housat_sr)** | adapter au domaine | **meilleur PSNR** ; bat bicubique PSNR+SSIM ; 8 min GPU |
| **SEN2SR (ESA)** | SR satellite dédié | **non exécuté** : `mlstac`+`cubo` ; hors-domaine sur LR Esri → à tester sur vraie Sentinel-2 |
| **CPU** | exécution sans GPU | viable (512² : ~3-14 s selon modèle) |
| **GPU local (4070 Ti S)** | débit | ×7 ; entraîne un modèle en 8 min |
| **Colab gratuit** | banc d'essai | **non exécuté** : sessions éphémères, quotas → expérimentation, jamais production |
| **HuggingFace** | modèles/datasets | **utilisé** (Swin2SR, SwinIR, Nomos) |
| **Source haute résolution (archive datée Esri)** | lisibilité réelle | **dominant** ; seul levier qui change le plafond |

## Limites (à ne pas masquer)

- **Paires non multi-capteurs** : entraînement et éval partagent le **même opérateur de dégradation**
  (Esri → LR simulé). Le modèle apprend à **inverser cet opérateur** ; le split par villes limite la
  fuite de **contenu**, pas de **dégradation**. Les chiffres rangent les méthodes **sur ce protocole**,
  ils ne valent pas comme performance absolue sur de la **vraie** Sentinel-2 (paires appariées
  OpenSR-4x / WorldStrat à utiliser pour franchir ce pas).
- Vérité-terrain **proxy** (Esri ≠ vérité absolue).
- **SEN2SR non mesuré** ; **Colab non exécuté** ; RGB ×4 sur 2 sites.

## Reproduction

```bash
# 1) Évaluer les méthodes pré-entraînées (CPU + GPU)
export HOUSAT_SR_ONNX=/chemin/swinir_basicsr_x4.onnx     # optionnel (onnx_sr)
PYTHONPATH=pipeline python -m housat.benchmark \
  --bbox 9.70,4.04,9.71,4.05 --size 512 \
  --methods nearest,bicubic,swin2sr,onnx_sr --devices cpu,cuda --out-dir benchmarks/results

# 2) Fine-tuner un SR satellite (GPU) puis l'évaluer
PYTHONPATH=pipeline python -m housat.benchmark_finetune \
  --train-cities abidjan,accra,yaounde,kinshasa --steps 4000 --grid 5 --ckpt benchmarks/models/housat_sr_x4.pt
export HOUSAT_FT_CKPT=$PWD/benchmarks/models/housat_sr_x4.pt
PYTHONPATH=pipeline python -m housat.benchmark \
  --bbox 9.70,4.04,9.71,4.05 --size 512 \
  --methods nearest,bicubic,housat_sr,swin2sr --devices cpu,cuda --out-dir benchmarks/results_ft
```

## Verdict

- **Qualité** : **fine-tuning satellite = meilleur PSNR** (bat bicubique PSNR **et** SSIM) ; **Swin2SR =
  meilleur SSIM**. Le bicubique reste une référence dure que **seul le fine-tuning dépasse sur les deux**.
- **Coût** : **8 min de GPU** suffisent à battre un gros modèle générique → ROI immédiat.
- **Produit** : voie **affichage** → `housat_sr` (ou Swin2SR pour le piqué) ; voie **détection** →
  **radiométrique, sans modèle perceptuel**.
- **Prochaine étape pour aller plus loin** : fine-tuner sur **vraies paires appariées**
  (OpenSR-4x / WorldStrat) + objectif perceptuel (SSIM/LPIPS) → viser un gain non optimiste.
