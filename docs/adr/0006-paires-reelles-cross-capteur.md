# ADR 0006 — Paires réelles multi-capteurs : le domaine gagne in-domain, échoue cross-capteur

Statut : accepté (2026-09-15)

## Contexte

L'ADR 0005 (fine-tuning sur LR simulé dérivé d'Esri) était **optimiste** : train et test partageaient
l'opérateur de dégradation. Question : le résultat tient-il sur de **vraies paires indépendantes** ?
Exigence : mesurer sur un jeu **réellement apparié**, avec split spatial.

## Méthode

- **Données** : `isp-uv-es/opensr-test` (ESA OpenSR) — LR = Sentinel-2 L2A **réelle**, HR = prises
  **indépendantes** (NAIP domaine public / SPOT Airbus / VENUS CNES), bien co-registrées. NAIP ×4.
- **Split spatial** : 22 images d'entraînement, 8 localisations **held-out** (distinctes).
- **Modèle** : EDSR-lite ×4 (identique), 3000 pas, **~2,5 min GPU**.
- **Comparaison** : bicubic, Swin2SR, housat_sr — sur NAIP held-out **et** sur SPOT (cross-capteur).

## Résultats

| Split | PSNR bicubic | PSNR Swin2SR | **PSNR housat_sr** | SSIM housat_sr |
|---|---|---|---|---|
| NAIP test (in-domain) | 39,38 | 40,05 | **40,44** | **0,9508** (best) |
| SPOT (cross-capteur) | 35,21 | **35,24** | 33,23 | 0,8579 |

## Décision

1. **In-domain, le fine-tuné de domaine est retenu** : il bat bicubique et Swin2SR sur **PSNR et SSIM**
   sur des **paires réelles** → le résultat de l'ADR 0005 est **confirmé sans le biais** de dégradation
   partagée. Gain modéré mais réel.
2. **Cross-capteur, il est rejeté** : entraîné sur NAIP, il **perd** face au bicubique sur SPOT, là où
   **Swin2SR (générique) est le plus robuste**. → **Un modèle de domaine doit être ré-entraîné par
   capteur/région** ; aucun modèle unique ne couvre tous les capteurs.
3. **Licence** : entraîner sur SPOT (CC BY-NC) **interdit l'usage commercial** du modèle. Le modèle de
   production s'entraîne sur des HR **libres** (NAIP, HR ouverte de la région cible).
4. **Métriques** : **ne jamais comparer des valeurs absolues entre protocoles** (Psnr ~19 dB en
   simulated-LR vs ~40 dB ici) — seuls les **classements** le sont.

## Conséquences

- Deux modèles coexistent selon l'usage : **générique portable** (Swin2SR) vs **de domaine précis**
  (housat_sr) — choix par capteur.
- Tout futur modèle SR doit passer **les deux protocoles** (simulated-LR **et** paires réelles) avant
  adoption ; `housat/benchmark_realpairs.py` les rend reproductibles.
- La **voie détection reste radiométrique** (aucun modèle perceptuel) — inchangé.

## Limites

Jeu de test **petit** (30 NAIP / 12 SPOT) ; NAIP **US** (le déploiement tropical exige d'autres HR
libres) ; objectif **L1** (PSNR-optimal, SSIM perfectible) ; VENUS (×2) non évalué.
