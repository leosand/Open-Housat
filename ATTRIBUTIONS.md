# Attributions et licences des données et images tierces

> Ce fichier couvre les **sources externes** consommées par Housat. Il existe parce que plusieurs
> licences **exigent** une attribution explicite dans tout livrable, et parce qu'une source dont la
> licence interdit la redistribution ne doit **jamais** se retrouver dans un rapport livré
> (cf `docs/limites-et-honnetete.md` § 4.5).

## Règle de tri (à appliquer avant d'embarquer quoi que ce soit dans un livrable)

1. **Redistribuable = oui** → peut entrer dans un PDF/rapport, **avec** l'attribution ci-dessous.
2. **Redistribuable = non** → **écran uniquement**. Jamais dans un livrable client, jamais en cache
   partagé. Cette règle est portée par le champ `redistributable` du module `pipeline/housat/imagery/basemap.py`.
3. **Redistribuable = inconnu** → traiter comme **non**. L'ignorance n'est pas une autorisation.

## Sources

| Source | Usage dans Housat | Licence | Redistribution | Attribution exigée |
|---|---|---|---|---|
| **Copernicus Sentinel-2 L2A** (via STAC AWS Element84) | Voie **DÉTECTION** : bandes radiométriques, indices NDVI/NDBI/BSI | Copernicus Open Data (libre, commercial inclus) | **Oui** | « Contains modified Copernicus Sentinel data \[année\] » |
| **Esri World Imagery** (ArcGIS `World_Imagery/MapServer`) | Voie **AFFICHAGE** : fond lisible pour toute emprise lat/long | Esri Master Agreement | **Non** | « Esri, Maxar, Earthstar Geographics, and the GIS User Community » |
| **Esri World Imagery Wayback** | Paires LR↔HR datées (`04_pairs_reelles.py`, `--hr-date nearest\|before`) | idem Esri | **Non** | idem ci-dessus |
| **OpenStreetMap** (Overpass API) | Empreintes bâties `ODbL` : masque bâti, pseudo-vérité terrain, IoU | ODbL 1.0 | **Oui** | « © OpenStreetMap contributors » |
| **Google Open Buildings 2.5D Temporal** | Hauteur de bâti et présence bâtie (jalons M0-M4) — **voie en repli tant que l'index de tuiles n'est pas obtenu** | CC-BY-4.0 (données Google Research) | **Oui** | « Open Buildings © Google Research, CC-BY-4.0 » |
| **SEN2NAIP** (`isp-uv-es/opensr-test`, dépôt HuggingFace) | Paires réelles licence propre pour le fine-tuning SR | MIT (code) / CC-BY-4.0 (dataset) | **Oui** | Cf `benchmarks/README.md` |
| **NAIP** (USGS) | Paires réelles HR domaine public | Domaine public US | **Oui** | « USDA-FSA Aerial Photography Field Office » |

## Google Open Buildings 2.5D Temporal — détail de la licence

- **Lien canonique** : https://sites.research.google/gr/open-buildings/temporal
- **Source officielle de publication** : https://data.humdata.org/dataset/google-open-buildings-temporal
- **Licence** : **CC-BY-4.0** — l'attribution est une **obligation**, pas une courtoisie.
- **Date de récupération / de vérification** : **2026-09-19** (structure d'URL et joignabilité
  publique sondées par `HEAD` réel : **HTTP 200**, `application/octet-stream`).
- **Structure de stockage mesurée** :
  `https://storage.googleapis.com/open-buildings-temporal-data/v1/geotiffs/<composite>/tile_<hash>.tif`
- **Limite connue** : aucun index latitude/longitude → tuile n'est publié dans les listes d'URL
  publiques (noms de composite et de tuile opaques). Tant que cet index n'est pas obtenu, le script
  `housat-finedouala-1/08_openbuildings_temporal.py` produit un **repli local explicitement étiqueté**
  (`provenance: local_fallback`, `agreement_status: NON_VERIFIABLE`) — il n'attribue **jamais** ses
  valeurs à Google. Voir `housat-finedouala-1/RAPPORT.md` § 6 et 7.

## Données qui ne quittent jamais le poste de travail

Les images et tenseurs dérivés (`housat-finedouala-1/data/`, `**/*.tif`, `**/*.cog`, `**/checkpoints/`)
sont **exclus de Git** : ce dépôt ne redistribue aucune donnée tierce, seulement du code et des modèles
entraînés (`housat-finedouala-1/models_export/*.onnx`). Voir `.gitignore`.
