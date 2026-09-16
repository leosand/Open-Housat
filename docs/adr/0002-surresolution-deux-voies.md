# ADR 0002 — Surrésolution à deux voies cloisonnées (détection vs affichage)

Statut : accepté (2026-09-15T18:41:43-04:00)

## Contexte

Le comparateur avant/après et les rapports PDF montrent des images Sentinel-2 « super-résolues ».
Constat d'audit : le paquet `sen2sr` n'était **ni dans `requirements.txt`, ni dans le venv, ni dans
l'image Docker** — donc `HAS_SEN2SR=False` en production et **le pipeline ne faisait qu'un bicubique
4×** de pixels à 10 m. Le README annonçait « 2,5 m par inférence neuronale » : écart documentation /
réalité. S'ajoutait un rendu PNG par clip dur (`rgb / 0.35`), sans étirement ni gamma, produisant des
vignettes sombres et plates — la « résolution nulle » perçue venait autant du rendu que de l'absence
de modèle.

Deux contraintes s'opposent :

1. **Qualité visuelle** : on veut des images lisibles (modèle perceptuel type Real-ESRGAN, GPU local
   RTX 4070 Ti SUPER 16 Go, disponible et gratuit).
2. **Inaltérabilité V&V** : les jalons M0-M4 reposent sur des indices radiométriques (NDVI/NDBI/BSI).
   Un modèle perceptuel **invente** de la structure (toits, murs). L'appliquer aux bandes de calcul
   fabriquerait de fausses fondations → jalons faux → rapports scellés mais mensongers.

## Décision

Cloisonner la surrésolution en **deux voies indépendantes** :

| Voie | Fonction | Moteurs autorisés | Sortie |
|---|---|---|---|
| **Détection** | Réechantillonne les bandes radiométriques servant aux indices | `sen2sr` (satellite, physique), sinon `bicubic` honnête | bandes alignées + `sr_method` |
| **Affichage** | Compose le PNG avant/après (dashboard, carte, PDF) | `realesrgan` ONNX (perceptuel, optionnel), sinon passage direct | PNG |

- **Aucune bande de calcul ne traverse la voie affichage** ; aucune image perceptuelle ne nourrit un
  indice. Garanti par construction (fonctions distinctes `upscale_bands` / `upscale_rgb_display`).
- La voie affichage est **optionalisée** : sans modèle configuré (`SR_MODEL_PATH` vide), elle est un
  passage direct — l'image du dashboard reste fonctionnelle sans GPU ni paquet lourd.
- La voie détection **dégrade en bicubique** si SEN2SR est absent *ou si son inférence échoue*
  (mémoire/modele) : une panne de modèle ne doit pas rompre le worker.
- Sélection par variables d'environnement : `SR_ENGINE` (détection), `DISPLAY_SR_ENGINE` (affichage).

Le rendu PNG applique un **étirement robuste par percentiles 2-98 % + gamma 0,9 + léger rehaussement**
(`imagery/rendering.py`), indépendant des valeurs brutes de détection.

## Conséquences

- Les poids Real-ESRGAN (~64 Mo) **ne sont pas committés** (taille / licence) : l'utilisateur fournit
  un `.onnx` et renseigne `SR_MODEL_PATH`. `pipeline/requirements-sr.txt` documente les dépendances
  optionnelles, **hors image slim** (ADR 0001 « zero dollar » respecté).
- Le contrat de `upscale_bands` et le libellé `bicubic_fallback` sont **conservés** (non-régression).
- `sr_method` continue d'alimenter la confiance (`sen2sr` → 0,8 ; sinon 0,55) : le client sait
  toujours laquelle des deux voies a produit l'image.
- **Limite assumée** : à 10 m/pixel Sentinel-2, une maison individuelle reste ~1-2 pixels ; la voie
  affichage embellit, elle ne crée pas d'information métrologique. Pour une **vraie** hausse de
  résolution, la piste suivante est une source à plus haute résolution (Planet NICFI 4,77 m — gratuite
  dans la ceinture tropicale) et/ou SAR Sentinel-1 — hors périmètre du présent ADR.

## Alternatives rejetées

| Alternative | Raison du rejet |
|---|---|
| Real-ESRGAN sur les bandes de détection | Hallucination de structure → jalons faussés (atteinte à l'inaltérabilité V&V). |
| SEN2SR obligatoire dans l'image slim | Ajoute torch (~2 Go) à un conteneur « zero dollar » ; échec GPU non souhaité en CI. |
| Rendu perceptuel intégré à `image_png_rgb` | Couplage couche modèle ↔ rendu ; rend la fonction intestable sans poids. |
| Rester en bicubique seul | Le rendu corrigé améliore déjà fortement la lisibilité ; SEN2SR/ONNX restent activables. |
