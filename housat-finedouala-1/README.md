# `housat-finedouala-1/` — Fine-tuning SR Douala (branche `finetune-douala`)

> Expérimentation **isolée** : rien ici ne part sur `main` sans PR explicite.
> Ce dossier contient le code, les configs, le README et les tests ; **les données, checkpoints
> intermédiaires et rasters n'entrent jamais dans Git** (voir `.gitignore`).

## 0. Verdict sur les hypothèses du prompt de départ

Chaque hypothèse a été confrontée à une **mesure**, pas à une opinion. Ce qui est validé est
incorporé ; ce qui est faux est remplacé ; ce qui est trop prudent est conservé en repli.

| # | Hypothèse du prompt | Verdict | Preuve / décision |
|---|---|---|---|
| 1 | Branche dédiée `finetune-douala` | **Incorporée** | Créée depuis `main` = `6881ac0` (et non `2764f8c8`) : les 2 commits suivants contiennent le **correctif OSM** (réessai sur réponse vide) dont le masque bâti dépend, et `pipeline/housat/built_dataset.py` déjà testé |
| 2 | Tout le neuf dans `housat-finedouala-1/` | **Incorporée** | Isole l'expérimentation du paquet de production. Le socle générique `pipeline/housat/built_dataset.py` **reste** dans `pipeline/` (déjà dans `main`, testé par la CI) : on l'importe au lieu de le dupliquer |
| 3 | Patchs 48-64 px @10 m, batch 2, accumulation ×8 | **Trop prudent → repli OOM** | Le harnais **déjà mesuré** ici tourne à **batch 8** sur des patches **128 px LR** (4000 pas, ~8 min GPU, 100 paires) et bat Swin2SR. On garde donc ces valeurs par défaut et les vôtres comme plan de repli |
| 4 | AMP/FP16 + `empty_cache()` + gradient checkpointing optionnel | **Incorporée** | Ce sont de bonnes pratiques, déjà partiellement présentes dans `benchmark_finetune.py` ; le checkpointing reste **optionnel** (jamais activé sans OOM mesuré) |
| 5 | Stockage ≤ 15 Go, données hors Git | **Incorporée** | Budget recalculé : **44 Mo brut par date** (4 bandes × 2 octets × 2 500 × 2 200 px à 10 m), **~530 Mo pour 12 dates**, ~185-250 Mo en COG LZW → large. `.gitignore` durci sur le modèle demandé |
| 6 | Emprise = métropole `[9.60, 3.95, 9.85, 4.15]` | **Incorporée (meilleure que mon îlot)** | 25 × 22 km = **286 542 empreintes OSM** mesurées, soit **~1 340 patches de 64 px par date**. L'îlot Housat (178 m, 18 × 18 px) ne peut pas entraîner : il devient **zone de validation tenue à l'écart** |
| 7 | **8-12 scènes sèches 2023-2026, nuages < 10-15 %** | ❌ **FAUSSE → remplacée** | Mesure STAC (Douala 10 km, nov-fév) : 2017-18 → 23 scènes dont **6** < 15 % ; 2022-23 → 25 dont **3** ; 2024-25 → 17 dont **1** ; **2025-26 → 23 dont ZÉRO sous 30 % (min 34 %)**. « 8-12 scènes sèches 2023-2026 » **n'existe pas** |
| 8 | Nuages < 10-15 % (critère tuile) | ❌ **Remplacée** | ADR 0010 : `eo:cloud_cover` porte sur **toute la tuile (~110 km)** et écarte des scènes dont la parcelle est dégagée (mesuré : 0 → 2 dates exploitables en passant au **SCL par parcelle**). Le critère décisionnaire est **par parcelle**, pas la tuile |
| 9 | Réutiliser `benchmark_finetune.py`, `benchmark_realpairs.py`, `export_onnx.py` | **Incorporée (rung 2 de l'échelle ponytail)** | Interfaces vérifiées : `build_pairs(cities, grid, hr_size)`, `build_model(ch=64, nblocks=8)`, `train(...)`, `export(ckpt, out, opset=17)` — signatures inchangées, **rien de neuf à inventer** |
| 10 | ONNX final ×4, < 10 Mo | **Déjà conforme** | `pipeline/housat/models/housat_sr_x4.onnx` et `housat_sr_l1_x4.onnx` = **3 567 642 octets** chacun (3,57 Mo), exportables via `export_onnx.py` |
| 11 | « visualisation avant/après améliorée » | **Intention incorporée, objet changé** | Le composant de comparaison d'images que suppose le prompt **n'existe plus** (supprimé : deux vignettes 10 m illisibles). Le nouveau comparateur part de la **sortie SR** + l'imagerie HR datée, avec la mention obligatoire « **×4 neuronal → 2,5 m effectif**, jamais 1 m réel » |
| 12 | IoU bâti vs empreintes | **Incorporée + renforcée** | Supervisé par les empreintes **OSM (ODbL)** ; **split spatial** (ADR 0006 : in-domain gagne, cross-capteur échoue → validation sur zone jamais vue) |

## 1. Fenêtre temporelle retenue (corrigée par la mesure)

| Saison sèche (nov → fév) | Scènes | < 15 % (tuile) | Usage |
|---|---|---|---|
| 2017-2018 | 23 | **6** | référence historique (change detection) |
| 2022-2023 | 25 | **3** | référence intermédiaire |
| 2024-2025 | 17 | **1** | millésime récent |
| 2025-2026 | 23 | **0** (min 34 %) | **à ne pas écarter** : qualification **par parcelle (SCL)** obligatoire avant décision |

Cible : **8-12 scènes** réparties sur ces saisons, **qualifiées par parcelle** (`max_cloud_cover = 20 %`
sur le SCL, cf. ADR 0010), jamais sur le nuage tuile.

## 2. Ce que fait (et ne fait pas) l'expérimentation

- **Objectif 1 — SR ×4 (2,5 m)** : fine-tuning d'EDSR-lite (déjà **batteur** de Swin2SR ici : PSNR
  19,02 vs 18,65 sur Douala, 0,4 s/tuile GPU, ~1 M paramètres) sur paires LR↔HR proxy.
- **Objectif 2 — contours de bâtiment** : segmentation supervisée par les empreintes OSM rasterisées
  (preuve d'alignement déjà obtenue : **49,8 % vecteur ↔ 50,4 % raster** sur scène réelle).
- **Objectif 3 — dalle vs toit** : trajectoire spectrale temporelle (BSI/NDBI/NDVI) **arbitrée par
  l'imagerie HR datée** — une image isolée ne tranche pas.
- **Hors périmètre, déclaré non fiable** : parcellaire individuel sous ~20 m de côté, hauteurs de
  bâtiment, toute donnée opposable juridiquement ; le « 1 m » reste un **affichage**.

## 3. Garde-fous de fiabilité (non négociables)

PSNR/SSIM/**SAM** (angle spectral < 5-10°), **cohérence NDVI** après agrégation à 10 m (±5-10 %),
**test de texture sur masque d'eau** (zéro hallucination tolérée sur le Wouri), **IoU bâti** sur
zone tenue à l'écart, carte d'incertitude si le modèle le permet, taille de chaque artefact loggée.

## 4. État

- [x] Hypothèses vérifiées et arbitrées (ce fichier)
- [x] Budget disque calculé, `.gitignore` durci (aucune donnée versionnée — vérifié)
- [x] `01_dataset_douala.py` — qualifié **par parcelle (SCL)**, exécuté (2024-12-01 retenue : 12 % parcelle / 9 % tuile)
- [x] `02_finetune.py` — AMP + accumulation + meilleur checkpoint, **exécuté sur GPU** (pic VRAM 0,09 Go, ckpt 3,57 Mo)
- [x] `03_eval.py` — exécuté : **SAM 0,45° OK** · **NDVI écart 35 % → échec** (une SR ×4 déplace le NDVI : les indices de la voie SR ne sont **pas** comparables à ceux du natif) · eau **non concluant** (0 pixel) · 3 mensonges de métrique corrigés
- [x] `04_pairs_reelles.py` — paires LR↔HR réelles + contrôle d'**alignement structurel** (contours + décalage)

### Mesure d'alignement sur trois saisons sèches (Akwa, 1 km, patchs 64 px)

| Scène LR | Archive HR | Écart | Corr. contours | Décalage |
|---|---|---|---|---|
| 2017-11-03 (tuile 49 %) | 2017-10-25 | 9 j | **0,192** | 0,0 px |
| 2022-11-07 (tuile 41 %) | 2022-11-02 | **5 j** | **0,227** | 0,0 px |
| 2024-12-11 (tuile 60 %) | 2024-11-18 | 23 j | **0,114** | 0,0 px |

**Enseignement** : la géométrie n'est **jamais** décalée (0,0 px partout — le mapping ×4 et la projection
sont justes) ; c'est la **proximité temporelle** qui gouverne la corrélation (5 j > 9 j > 23 j).
Le levier n'est donc pas la géométrie mais **la date** : scène peu nuageuse + archive au plus près
(piste de fond : mosaïques **NICFI** mensuelles, module `planet_nicfi` déjà présent).

**Réserve assumée** : mon seuil de 0,3 n'est **pas calibré** (aucun contrôle positif mesuré) — il
marque « DOUTEUX » là où le plafond cross-capteur réel est inconnu. À calibrer avant toute conclusion.

- [ ] Calibrer le seuil d'alignement (contrôle positif/négatif) puis brancher `02 --pairs real`
- [ ] Export ONNX via `export_onnx.py` · comparateur avant/après autour de la sortie SR (branche, pas `main`)
