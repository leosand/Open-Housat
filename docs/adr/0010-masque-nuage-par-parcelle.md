# ADR 0010 — Masque nuage PAR PARCELLE (SCL) au lieu de la tuile

Statut : accepté (2026-09-16)

## Contexte

La sélection des scènes utilisait `eo:cloud_cover < MAX_CLOUD_COVER` (20 %). Or cette statistique
porte sur **toute la tuile Sentinel-2** (~110 × 110 km). Sur une parcelle de ~180 m, elle est
**sans rapport** : la parcelle peut être parfaitement dégagée alors que la tuile est annoncée à 95 %.

Mesure sur la parcelle de démonstration (Douala, 120 j) : **33 passages** (écart médian **3 j**),
**0 exploitable** au seuil tuile de 20 % — alors que **Sentinel-2 fournit bien la cadence 5-7 j
demandée**. Le verrou n'était donc pas la cadence mais **un filtre mal dimensionné**.

## Décision

1. **Filtrer sur la PARCELLE, pas la tuile** : lire la couche **SCL** (Scene Classification, 20 m,
   catégorielle) et compter la fraction de pixels obscurcis sur l'emprise du chantier.
   Classes inutilisables : `{0 NO_DATA, 1 SATURATED, 3 CLOUD_SHADOW, 8/9 CLOUD, 10 CIRRUS, 11 SNOW}`
   (`imagery/clouds.py`, pur et testé).
2. **Découpler les deux seuils** :
   - `tile_cloud_prefilter` (défaut **90 %**) : simple coupe en amont sur `eo:cloud_cover`, volontairement
     **large** pour ne jamais exclure une scène dont la parcelle serait dégagée ;
   - `max_cloud_cover` (défaut **20 %**) : seuil **produit**, appliqué désormais à la **parcelle**.
3. **Ordre d'acquisition** : le worker lit **le SCL seul d'abord** (1 fichier, 20 m) et ne télécharge
   les 5 bandes **que si la parcelle est dégagée** — le rejet ne coûte donc presque rien.
4. **Rééchantillonnage plus proche voisin** obligatoire (`order=0`) : une couche **catégorielle** ne
   s'interpole jamais (mélanger « nuage » 8 et « végétation » 4 produirait une classe inexistante).
5. **Repli non bloquant** : SCL absent (asset manquant, panne réseau) → la scène est **conservée** et
   un WARNING est tracé. On ne perd jamais une scène à cause d'un problème d'outil.

`check_site` examine jusqu'à **6** scènes récentes et retient la plus **récente dont la parcelle est
dégagée** (le pré-filtre large ne suffit pas à décider).

## Conséquences

- **Beaucoup plus de dates exploitables** sur les zones tropicales (mesuré sur Douala, cf. journal de
  benchmark) : le produit passe d'« aucune scène » à plusieurs dates utilisables.
- Le coût réseau est **réduit** : le SCL (1 fichier) est téléchargé avant les 5 bandes.
- La sémantique du produit est clarifiée : « exploitable » = **la parcelle est visible**.
- `GET /sites/{id}/overpasses?parcel=true` expose le nuage **par parcelle** (borné aux 12 plus
  récentes, car 1 téléchargement par scène) en plus du nuage tuile.

## Limites

Le SCL est **imparfait** (cirrus ténus, ombres partielles) et à **20 m** ; le seuil par parcelle reste
une décision produit (assumé : on privilégie le rappel sur la précision). En saison des pluies, même le
masque par parcelle peut ne rien laisser passer — c'est alors un fait météorologique, pas un défaut
logiciel (d'où l'intérêt du **SAR** en complément).
