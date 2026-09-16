# ADR 0007 — Surrésolution servie en ONNX, appliquée au pipeline (intégration web commercialisable)

Statut : accepté (2026-09-15)

## Contexte

La recommandation des ADR 0005/0006 doit être **commercialisable** et **utilisable facilement dans
l'application web** du projet `leosand/Housat`. Or :

- le service tourne dans une image **slim sans torch ni GPU** ;
- l'API (`GET /observations/{id}/image`) **sert une image déjà persistée** (`image_png`) ; le front et
  les rapports PDF l'affichent **sans logique propre** ;
- la **licence** contraint l'usage commercial (SPOT = CC BY-NC → modèle non vendable).

## Décision

1. **Servir la SR en ONNX Runtime (CPU)** — ~15 Mo, **sans torch, sans GPU**. `onnxruntime` devient une
   dépendance de service (`pipeline/requirements.txt`). Export fourni : `housat/export_onnx.py`
   (contrat `(1,3,H,W) → (1,3,4H,4W)`), déjà compatible de l'`OnnxSrBackend`.
2. **Appliquer la SR au seul pipeline, voie AFFICHAGE**, et sur les **bandes brutes 10 m** (pas sur les
   bandes de détection déjà ×4 → sinon ×16 et géométrie fausse). Le `image_png` persisté est donc
   SR-amélioré → **le front web et le PDF n'ont rien à changer** (intégration « gratuite »).
3. **Modèle de référence licence-propre** : `housat/models/housat_sr_x4.onnx` (EDSR-lite ×4) entraîné sur
   **NAIP (domaine public US)** → **commercialisable**. **Jamais** sur SPOT (CC BY-NC).
4. **Modèle régional remplaçable** (`SR_MODEL_PATH`) ; **désactivé par défaut**, car un modèle entraîné
   ailleurs peut **dégrader** la scène (ADR 0006 : échec cross-capteur). Activation = 1 variable d'env.
5. **Voie détection inchangée** : radiométrique, aucun modèle perceptuel.

## Conséquences

- **Déployable** : aucune dépendance lourde (ni torch, ni GPU) dans le service ; image slim préservée.
- **Facile** : `SR_MODEL_PATH=housat/models/housat_sr_x4.onnx` suffit ; sinon comportement historique.
- **Licence** : le modèle livré (NAIP) est vendable ; documenter la source HR (libre) de tout modèle
  régional (ex. NICFI pour les tropiques, attribution requise).
- La garantie V&V « voie détection sans modèle perceptuel » est **matérialisée dans le code** (bandes
  brutes pour l'affichage, bandes ×4 pour les indices).
- `housat/export_onnx.py` rend l'export reproductible pour tout nouveau modèle régional.

## Alternatives rejetées

| Alternative | Raison |
|---|---|
| torch dans l'image API/worker | +2 Go, GPU requis ; inutile pour l'inférence ONNX CPU. |
| SR côté navigateur | Exposerait GPU/poids/clés au client ; MapLibre n'a pas à porter l'inférence. |
| Modèle Real-ESRGAN générique | Licence/poids lourds et qualité ≤ bicubique (ADR 0004). |
| SR activée par défaut | Un modèle hors-région peut dégrader l'image (ADR 0006) → opt-in. |

## Limites

Le modèle livré est **US (NAIP)** — démonstration ; la production exige un modèle **régional** entraîné
sur HR **libre** de la zone (tropiques : NICFI). L'affichage SR reste une **voie visuelle**, sans valeur
métrologique (jalons inchangés).
