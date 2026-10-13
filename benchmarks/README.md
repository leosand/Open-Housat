# Benchmark surrésolution (SR) — Housat

> Protocole d'évaluation technique des méthodes de sur-résolution sur jeux de référence et paires LR↔HR.

## Protocole (simulated low-resolution, facteur 4)

1. **Vérité-terrain proxy « HR »** : Esri World Imagery de l'emprise, ramenée à 512 px (~2-3 m/px).
2. **Entrée « LR »** : HR dégradé à 128 px (~8,7 m/px, façon Sentinel-2) par moyennage d'aire.
3. Chaque méthode remonte **LR 128 → 512** (×4). Métriques **PSNR / SSIM** vs HR proxy.

## Environnement

| Élément | Valeur |
|---|---|
| GPU | NVIDIA RTX 4070 Ti SUPER 16 Go, CUDA 12.4 |
| Modèles | Swin2SR, SwinIR, Real-ESRGAN, housat_sr (expérimental) |
| Autres | scikit-image, onnxruntime |

## Résultats — méthodes pré-entraînées

(Exemples chiffrés et tableaux disponibles dans le répertoire `benchmarks/results`.)

## Résultats — modèle fine-tuné satellite (`housat_sr`, EDSR-lite ×4)

(Les résultats présentés sont issus d'expérimentations menées sur jeux de test ; consulter les scripts d'évaluation pour reproduire.)

## Matrice des options

| Option | Rôle réel | Verdict benchmark |
|---|---|---|
| Bicubique / nearest | repli, référence | solide ; gratuit, instantané |
| Swin2SR | SR générique | bon compromis SSIM / qualité |
| SwinIR / Real-ESRGAN | SR perceptuel générique | méthodes perceptuelles orientées rendu |
| Fine-tuning satellite (housat_sr) | adapter au domaine | approche expérimentale requérant évaluation par site |

## Limites (à ne pas masquer)

- Les protocoles d'évaluation varient et influencent fortement les métriques absolues ; privilégier les classements relatifs.
- Les paires LR↔HR issues de sources différentes doivent être manipulées avec prudence.

## Reproduction

Instructions pour lancer les benchmarks et reproduire les évaluations techniques se trouvent dans `benchmarks/`.

## Verdict

Analyse technique des méthodes et recommandations d'utilisation selon le protocole choisi.
