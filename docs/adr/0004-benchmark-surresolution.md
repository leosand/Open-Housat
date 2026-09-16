# ADR 0004 — Surrésolution : décision par benchmark mesuré

Statut : accepté (2026-09-15)

## Contexte

La question « quelle méthode SR et quel moteur (CPU/GPU/Colab) pour la lisibilité de l'avant/après ? »
était jusqu'ici tranchée par **affirmation**. Exigence : la trancher par la **mesure**, sur données
réelles. Un harness reproductible (`pipeline/housat/benchmark.py`) a été écrit et exécuté.

Protocole : vérité-terrain **proxy** = Esri World Imagery à 512 px (~2-3 m/px) ; entrée **LR** = HR
dégradé à 128 px (~8,7 m/px) par moyennage d'aire ; chaque méthode remonte **×4** ; métriques
**PSNR/SSIM**. Sites : Douala et Port-au-Prince. Détail complet : `benchmarks/README.md`.

## Résultats (mesurés)

| Méthode (Douala) | PSNR | SSIM | Temps |
|---|---|---|---|
| nearest | 17,85 | 0,513 | ~0 s |
| bicubic | **18,70** | 0,559 | 0,6 s |
| **Swin2SR** (cpu → cuda) | 18,65 | **0,653** | 13,9 s → **2,0 s** |
| SwinIR ONNX | 17,38 | 0,541 | 8,9 s |
| Nomos / Real-ESRGAN ONNX | 16,33 | 0,491 | 5,4 s |

Port-au-Prince confirme le classement (Swin2SR SSIM 0,660 vs bicubic 0,563).

## Décision

1. **Bicubique = référence dure.** Aucun modèle testé n'améliore le PSNR ; Swin2SR n'améliore que la
   **structure** (SSIM). La SR n'apporte **pas** de gain de résolution métrologique.
2. **Swin2SR autorisé uniquement sur la voie AFFICHAGE** (cf. ADR 0002). La voie **détection** reste
   **radiométrique et sans modèle perceptuel** : les modèles génériques (SwinIR, Nomos/Real-ESRGAN)
   passent **sous** le bicubique et **fabriquent de la texture** — inacceptable pour un indice de jalons.
3. **GPU = débit, pas qualité.** PSNR/SSIM identiques CPU/GPU ; ×7 sur Swin2SR. Le GPU sert au **lot**.
4. **La source reste le levier principal** (ADR 0003). La SR ne comble qu'une fraction du chemin vers
   la lisibilité.
5. **Colab** = banc d'essai (poids, hyperparamètres), **jamais** un composant de production (sessions
   éphémères, quotas, pas d'état). **Non exécuté ici.**

## Conséquences

- `housat/benchmark.py` et `benchmarks/README.md` deviennent le **protocole de référence** pour toute
  future décision SR ; toute méthode ajoutée doit y être mesurée avant adoption.
- **SEN2SR** (le modèle satellite du projet) n'a **pas** été mesuré : il exige `mlstac`+`cubo` et son
  domaine est la **vraie** imagerie Sentinel-2 (le LR dérivé d'Esri est hors-domaine). À tester sur une
  tuile Sentinel-2 réelle avant tout verdict.
- **Piste la plus prometteuse** pour dépasser le bicubique de façon fiable : **fine-tuning d'un petit SR
  satellite** sur paires appariées (WorldStrat / OpenSR-4x) sur le GPU local.

## Alternatives rejetées

| Alternative | Raison du rejet |
|---|---|
| Déployer Swin2SR/Real-ESRGAN sur la voie détection | PSNR ≤ bicubique et texture fabriquée → jalons faussés (V&V). |
| Conclusion « la SR est inutile » | Faux : Swin2SR améliore la structure (SSIM) — utile à l'affichage. |
| Trancher sans benchmark | C'est l'erreur corrigée par cet ADR. |
| Colab en production | Sessions éphémères/quota : pas de service reproductible. |

## Limites assumées

Vérité-terrain **proxy** (Esri ≠ vérité absolue), **SEN2SR non mesuré**, **pas de fine-tuning**, RGB ×4
sur 2 sites. Chiffres valides pour **ranger** les méthodes, pas comme performance absolue.
