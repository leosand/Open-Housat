# housat-finedouala-1 — Fine-tuning SR Douala (branche `finetune-douala`)

> Expérimentation isolée : contenu et scripts d'entraînement et d'évaluation.

## Objectifs

- Étudier l'impact du fine-tuning d'un modèle SR sur des paires LR↔HR proxy pour un site donné.
- Évaluer les métriques PSNR/SSIM et la robustesse cross-site.

## Protocole expérimental

- Construction de paires LR↔HR simulées à partir d'archives HR disponibles.
- Entraînement d'un modèle EDSR-lite sur ensembles de paires ; évaluation sur sites hold-out.
- Vérification de la non-inclusion des données lourdes (rasters, checkpoints) dans Git.

## Résultats et état

(Résultats techniques et artefacts d'évaluation stockés dans ce dossier quand disponibles. Voir les scripts pour reproduire.)
