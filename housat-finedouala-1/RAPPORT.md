# `finetune-douala` — journal de la branche : résultats, risques, connaissances, pistes

> Branche d'**expérimentation** SR/supervision, jamais fusionnée dans `main`. Tout ce qui suit a été
> **exécuté** : aucun chiffre n'est estimé, chacun vient d'une commande dont la sortie est citée.
> Données, checkpoints et corpus sont **hors Git** (~5,8 Go sur disque, ignorés).

---

## 1. Objet et périmètre

| Objectif | État |
|---|---|
| **1. Surrésolution ×4** (10 m → 2,5 m effectif) | ✅ entraînée, évaluée, exportée ONNX |
| **2. Contours de bâtiment** (supervision OSM) | ✅ supervision **prouvée alignée** (49,8 % vecteur ↔ 50,4 % raster), segmenteur non écrit |
| **3. Dalle vs toit** | ⏳ méthode arrêtée (trajectoire spectrale BSI/NDBI/NDVI **arbitrée par imagerie HR datée**), non implémentée |

**Hors périmètre, déclaré non fiable** : parcellaire individuel sous ~20 m, hauteurs de bâtiment, toute
donnée opposable juridiquement. Le « 1 m » reste un **affichage** : une SR ×4 de 10 m vaut **2,5 m**.

## 2. Livrables (branche `finetune-douala`)

| Fichier | Rôle |
|---|---|
| `01_dataset_douala.py` | Dataset S2 : scènes qualifiées **par parcelle (SCL)**, masque bâti **OSM rasterisé** sur la grille du LR |
| `02_finetune.py` | Fine-tuning : **AMP/FP16**, accumulation, suivi VRAM, **meilleur checkpoint seul**, `--pairs synthetic\|real` (filtre d'alignement calibré appliqué) |
| `03_eval.py` | Garde-fous : **SAM**, **cohérence NDVI**, **texture sur l'eau**, étalon bicubique ; `--sr bicubic\|onnx` |
| `04_pairs_reelles.py` | Paires **LR Sentinel-2 réelle ↔ HR datée** ; `--hr-source wayback\|nicfi`, `--hr-date nearest\|before` |
| `05_calibrer_alignement.py` | **La métrique d'alignement est-elle sensible ?** courbe de décalage forcé 0→8 px |
| `06_apercu_html.py` | Comparateur **LR ↔ SR ↔ HR** auto-portant (HTML, aucune dépendance) |
| `07_realpairs_naip.py` | Entraînement sur paires **licence propre** (HF `opensr-test`, MIT + NAIP domaine public) sans passer par un `main()` inadapté |
| `models_export/housat_sr_best_x4.onnx` | **3,57 Mo, ×4 vérifié par inférence** (1,3,121,121) → (1,3,484,484) |
| `models_export/housat_sr_prod_x4.onnx`, `housat_sr_finedouala_x4.onnx` | Exports antérieurs (400 ROI ; Douala/Esri) |

## 3. Résultats mesurés

### 3.1 SR ×4 sur paires réelles licence propre (corpus `SEN2NAIP`, CC-BY-4.0, split 80/20 spatial)

| Run | Corpus | Pas | bicubique | Swin2SR | **housat_sr** |
|---|---|---|---|---|---|
| A | 30 scènes (HF `opensr-test`) | 5 000 | 41,33 / 0,957 / 0,274 | 42,04 / 0,962 / 0,227 | **42,67 / 0,965 / 0,182** |
| B | 400 ROI | 10 000 | 9,17 / 0,257 / 0,828 | 9,21 / 0,264 / 0,787 | **23,21 / 0,648 / 0,598** |
| C | 1 000 ROI | 30 000 | 8,83 / 0,254 / 0,817 | 8,88 / 0,261 / 0,775 | **23,49 / 0,645 / 0,556** |

*(PSNR / SSIM / LPIPS — évaluation sur les ROI **jamais vus**.)*

**Lecture** : le fine-tuné **écrase** un état de l'art pré-entraîné (+14,6 dB au run C). Mais entre B et C,
**+0,28 dB pour ×3 de calcul** → **le plateau est atteint** ; le LPIPS continue de progresser
(0,598 → 0,556). **Le levier restant est l'architecture, pas le volume ni le temps GPU.**

### 3.2 Garde-fous physiques (`03_eval.py`, scènes tenues à l'écart)

| Site | Scène | SAM (≤ 10°) | NDVI (≤ 10 %) | Eau (texture ≤ 1,5) |
|---|---|---|---|---|
| Douala (îlot 178 m) | 2024-12-01 | 0,45° ✅ | **35,4 % ❌** | 0 px → **non concluant** |
| Chicago (Loop + lac) | 2024-12-05 | 1,71° ✅ | **7,11 % ✅** | **121 428 px, 0,743 ✅** |

Enseignement : **le seuil NDVI ±10 % est atteignable**, mais il est **dépendant du site** (tissu dense
tropical vs hiver tempéré). Le test d'eau n'a de sens **que** si l'emprise contient de l'eau.

### 3.3 OSM à Douala — correction d'une erreur de mesure

Un premier relevé annonçait **0 bâtiment** : c'était une **réponse vide d'Overpass saturé** (200 + zéro
élément) acceptée comme un fait. Mesure refaite : **65 polygones** sur l'îlot de 178 m (49,8 % bâti),
**136 070** sur 10 km, **286 542** sur la métropole.

### 3.4 Disponibilité réelle des scènes sèches (Douala, nuage tuile)

| Saison | Scènes | < 15 % |
|---|---|---|
| 2017-11 → 2018-02 | 23 | **6** |
| 2022-11 → 2023-02 | 25 | **3** |
| 2024-11 → 2025-02 | 17 | **1** |
| **2025-11 → 2026-02** | 23 | **0** (min 34 %) |

→ L'hypothèse « 8-12 scènes sèches 2023-2026, nuages < 15 % » du prompt initial est **irréaliste** ;
le critère décisionnaire est **le SCL par parcelle** (ADR 0010), pas la tuile.

## 4. Risques (à traiter avant toute suite)

| # | Risque | Gravité | Parade |
|---|---|---|---|
| 1 | **Aucun checkpoint intermédiaire** : un run long perdu = tout perdu (vécu : run 6 h arrêté à ~1 h) | 🔴 | ajouter checkpoints périodiques + reprise **avant** tout run > 1 h |
| 2 | **Corpus majoritairement américain** (NAIP) : les +14 dB ne sont **pas** transposables à Douala | 🔴 | paires datées Douala (habilitation NICFI) ou accepter une évaluation par garde-fous seulement |
| 3 | **Esri = non redistribuable** : les paires `04` sont **internes** ; aucun modèle publié entraîné dessus sans validation juridique | 🟠 | utiliser `SEN2NAIP`/`opensr-test` (CC-BY-4.0 / domaine public) pour tout artefact publié |
| 4 | **Clé API Planet exposée** dans une conversation → compromission | 🔴 | **rotation** sur insights.planet.com (elle n'était écrite que dans `.env`, gitignoré) |
| 5 | **Seuil d'alignement 0,3 non calibré** (aucun contrôle positif/négatif) | 🟠 | la règle `corr(d=0)` max + chute ≥ 0,02 le remplace ; à valider sur un jeu étiqueté |
| 6 | **NiFi/Big Data ?** non — mais 180 Go pour `SEN2NAIP/synthetic` vs **plafond 15 Go** | 🟠 | n'extraire que des ROI (fait : 1 500 ROI ≈ 2,9 Go) |
| 7 | `train_real` **n'accepte pas** de reprise ni de scheduler exposé (signature figée) | 🟡 | passer nos hyperparamètres par introspection (déjà fait) plutôt que forker |
| 8 | **Plateau d'architecture** (~1 M paramètres EDSR-lite) | 🟠 | modèle plus gros / perceptuel-GAN, pas plus d'itérations |

## 5. Difficultés rencontrées → résolutions (le cœur de la connaissance)

| Difficulté | Cause réelle | Résolution |
|---|---|---|
| Écran de sélection vide (pendant des semaines) | MapLibre : `loaded()` est faux **tant que des tuiles chargent**, et `once('load')` **ne se reproduit jamais** → couche perdue en silence | `onStyleReady()` : `isStyleLoaded()` sinon `once('idle')` |
| « 100 % de nuages » sur 20 dates d'affilée | `rio_mask(filled=True, nodata=0)` : le **remplissage hors emprise** vaut `NO_DATA` → compté obscurci | `filled=False` + valeurs valides seulement (`compressed()`) |
| Emprise de maison inexploitable | SCL à **20 m** : une emprise de 16 × 8 m ne couvre **aucun centre de pixel** | `_scl_window` : voisinage **60 m** minimum pour le test nuage, **mesure** sur l'emprise exacte |
| Faux désaccord **0,114 vs 0,068** entre deux scripts | ① fichier d'entrée **changé entre les deux mesures** ; ② ordre **contour/crop** inversé ; ③ mon 1ᵉʳ correctif décalait **les deux** images | afficher l'**identité d'entrée** (archive lue) + cropper **puis** contours + décaler **seulement** le LR |
| `--bbox -87.64,…` refusé | argparse prend une valeur commençant par `-` pour une option | forme `--bbox=-87.64,41.87,-87.60,41.90` (**toute bbox de l'hémisphère ouest**) |
| `expected input[4,121,4,121] to have 3 channels` | passage en **CHW 4 bandes** au lieu du contrat **HWC 3 canaux /10 000** du harnais | répliquer `load_rgb` à l'identique (transpose + clip) |
| Sortie JSON illisible / `UnicodeEncodeError` cp1252 | `float32` numpy non sérialisable ; console Windows sans `→` | casts explicites ; ASCII dans les logs |
| Push **refusé** par GitHub | 466 Mo de sauvegardes harness committées dans un commit **local jamais poussé** | `.gitignore` durci (`.harness/backups/`, `data/`, `checkpoints/*.pt`, `*.tif`, `*.cog`) + branche reconstruite |
| **GitGuardian rouge** malgré un correctif | le scan lit **tout le diff de la PR**, pas le dernier commit | réécrire la branche (`reset --soft` + `force-with-lease`) : aucun commit ne doit contenir le secret |
| Job CI planifié rouge **tous les jours** | `secrets.DATABASE_URL` **inexistant** → URL vide → `Could not parse SQLAlchemy URL` | base de **service PostGIS** (`POSTGRES_HOST_AUTH_METHOD=trust`, aucun mot de passe) + schéma produit créé avant `reports` |
| Métriques SR qui se contredisent selon le script | trois implémentations du même indicateur | **une seule définition** de référence, et l'identité d'entrée imprimée avec le chiffre |

## 6. Connaissances capturées (fiches vault, `30-knowledge/`)

1. `map.loaded()` n'est pas « le chargement est fini » — `once('load')` ne se reproduit jamais.
2. `rasterio.mask(filled=True, nodata=0)` compte le remplissage hors emprise comme donnée.
3. SCL Sentinel-2 à 20 m : une emprise de maison ne couvre aucun centre de pixel.
4. Overpass/OSM : fiabilité réelle mesurée et repli d'endpoints.
5. Scan de secrets en CI : il analyse **tout le diff de la PR**, pas le dernier commit.

*Note interne (hors branche) : 3 notes supplémentaires restent en brouillon sur d'autres projets.*

## 7. Pistes à explorer (priorisées par rapport valeur/effort)

1. **Checkpoints périodiques + reprise** dans `train_real` (30 lignes) — **prérequis** à tout run long.
2. **Architecture plus profonde** (le plateau est mesuré) : EDSR/SwinIR plus gros, puis test perceptuel.
3. **ROI SEN2NAIP supplémentaires** : 2 851 disponibles, 1 500 convertis (≈ 2,9 Go) → marge ×2.
4. **Habilitation NICFI** (administratif) : seule voie vers des paires **Douala datées** de qualité.
5. **Segmentation bâti** (objectif 2) : U-Net sur le masque OSM — supervision déjà **vérifiée alignée**.
6. **Tête dalle/toit** (objectif 3) : trajectoire temporelle + arbitrage HR datée.
7. **Intégration produit** : déposer le meilleur `.onnx` dans `pipeline/housat/models/` (voie affichage) ;
   l'évaluation `03` peut devenir un **contrôle de non-régression en CI**.
8. **Comparateur** : alimenter `06` avec le modèle ONNX (aujourd'hui il affiche le bicubique comme étalon).

## 8. Reproductibilité (commandes exactes)

```bash
# dataset S2 + masque bâti OSM (qualifié par parcelle)
python housat-finedouala-1/01_dataset_douala.py --end 2025-03-01 --limit 12

# entraînement (paires réelles, filtre d'alignement calibré appliqué)
python housat-finedouala-1/02_finetune.py --pairs real --steps 30000 --batch-size 8

# garde-fous physiques (SAM / NDVI / eau) — attention à la forme « = » pour l'hémisphère ouest
python housat-finedouala-1/03_eval.py --bbox=-87.66,41.86,-87.60,41.93 --sr bicubic

# paires réelles LR↔HR (archive la plus proche, deux sens)
python housat-finedouala-1/04_pairs_reelles.py --bbox=9.695,4.035,9.725,4.065 --end 2025-03-01

# la métrique d'alignement est-elle sensible ?
python housat-finedouala-1/05_calibrer_alignement.py

# comparateur visuel LR ↔ SR ↔ HR (HTML auto-portant)
python housat-finedouala-1/06_apercu_html.py && start housat-finedouala-1/apercu/comparateur.html

# corpus licence propre (CC-BY-4.0) + entraînement sans passer par main()
python housat-finedouala-1/07_realpairs_naip.py --steps 5000

# export ONNX (script existant, signature inchangée) + vérification d'inférence
PYTHONPATH=pipeline python -m housat.export_onnx --ckpt <ckpt.pt> --out models_export/x.onnx
```

## 9. Évolutivité (ce que la branche permet déjà)

- **Modèle remplaçable sans code** : même signature ONNX que la production (3,57 Mo, ×4).
- **Supervision propre et publiable** : `SEN2NAIP` (CC-BY-4.0) / `opensr-test` (MIT + NAIP domaine public)
  → un modèle **publié** est juridiquement possible, contrairement au chemin Esri.
- **Mesure avant adoption** : tout modèle candidat passe `03_eval.py` (SAM/NDVI/eau) + le comparatif
  `evaluate` sur split spatial — les deux sont scriptés et rejouables.
- **Ajouter un capteur/corpus** = une variable `--data-dir` (le harnais charge `<name>-lr.npy`/`-hr.npy`).
