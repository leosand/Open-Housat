# ADR 0009 — Imagerie haute résolution DATÉE (Esri Wayback) : « voir la maison »

Statut : accepté (2026-09-15)

## Contexte

Constat produit (2026-09-15) : dans l'app, l'avant/après reste **illisible** — « on n'arrive même pas à
déterminer une maison ou un bâtiment ». Cause non contournable : **Sentinel-2 = 10 m/pixel** ; une
maison individuelle ≈ 1-2 pixels. **Aucune surrésolution** (ADR 0004-0008) ne crée d'information : la
SR améliore l'aspect, pas la lecture d'une toiture. Le MVP exige de **VOIR le bâti**.

## Solution (vérifiée en données)

**Esri World Imagery Wayback** : imagerie **sub-métrique DATÉE**, gratuite, sans clé. Vérifié sur
l'emprise de démonstration (Douala 9.70/4.04) : **121 dates de 2018-03 à 2026-08** (~mensuel), où
**bâtiments, toitures, rues et véhicules sont nets** au zoom 18.

## Décision

1. **Troisième voie « imagerie réelle »** (à côté de DÉTECTION et AFFICHAGE-SR) : `imagery/wayback.py`
   liste les releases datées et assemble les tuiles d'une emprise → **PNG HR daté**.
2. **Endpoints** : `GET /parcel/wayback/dates?bbox=…` (dates disponibles — sonde la couverture réelle)
   et `GET /parcel/wayback/image?bbox=…&date=…&size=…` (image HR).
3. **Frontend** : panneau « **Vue réelle haute résolution (datée)** » en tête du tableau de bord —
   deux sélecteurs **Avant/Après** sur les dates disponibles → le **vrai avant/après lisible**.
4. **Sentinel-2 reste la MESURE** (NDVI/NDBI/BSI → jalons) ; Wayback est la **LECTURE**. Les deux voies
   ne se contaminent pas.

## Conséquences

- **Le besoin MVP est satisfait** : on voit la maison, et son évolution entre deux dates — sur les
  zones couvertes par Wayback (nombreuses zones urbaines mondiales).
- **Couverture variable** : `available_dates` **sonde** les tuiles (404 ou placeholder = pas de
  couverture) → l'UI n'affiche que les dates réellement disponibles. Une zone non couverte le signale.
- **Licence** : `ATTRIBUTION`/`LICENCE` portées par l'API ; la **redistribution/cache** est restreinte
  → usage écran OK, **rapport vendu à valider** (comme pour Esri World Imagery, ADR 0003).
- Tests `tests/test_wayback.py` (fetcher injecté, sans réseau) ; l'assemblage de tuiles réutilise
  `stitch_xyz` (géométrie Web Mercator déjà testée).

## Alternatives rejetées

| Alternative | Raison |
|---|---|
| Continuer la SR sur Sentinel-2 | Ne crée pas d'information : la maison reste 1-2 px (ADR 0004-0008). |
| Planet NICFI seul | 4,77 m (mieux que S2 mais ~2 px/maison) et **clé requise** ; complémentaire, pas suffisant. |
| Imagerie commerciale (Planet quotidien 3 m, Maxar) | Payante ; hors du cadre « zero dollar ». |
| Google/Bing tuiles | Clé/serveur de tuiles facturé + licence plus restrictive. |

## Mise en œuvre (2026-09-15)

- **Profondeur native vérifiée** : Esri Wayback va jusqu'à **z19 (~0,3 m/px)** à Douala (z20 = 404),
  et z19 est **réellement plus net** que z17 (variance de Laplacien 3988 > 3146) — **pas** de
  l'upsampling.
- **Le facteur limitant était le RENDU, pas la donnée** : `GSD_sortie = étendue_bbox / taille_px`.
  Les 512 px sur 1,1 km donnaient ~2,2 m/px. Corrections : **contrôle de zoom** (réduit l'emprise
  autour du centre) + **taille 1024** → on descend au **bâti** (toitures, ombres, véhicules lisibles).
- **Au-delà du natif : impossible sans invention.** La SR (SwinIR/Real-ESRGAN, diffusion type
  StableSR/SeeSR/ResShift) **hallucine** — interdite comme vérité (V&V).
- **Rendu NATIF (fin de l'upsampling qui floutait)** : `size` omis ⇒ sortie **1 px image = 1 px
  source** (512 px natifs sur 133 m ≈ 0,26 m/px) ; toute `size` fournie est **bornée au natif** (un
  « grossissement vide » 2× était la cause du flou). Repli automatique de zoom si couverture absente.
- **Emprises de bâtiments (OSM/Overpass, ODbL)** : `?buildings=1` superpose les contours — **libre,
  sans clé, redistribuable**, donc utilisable dans un rapport livré (contrairement aux tuiles Esri).
  C'est le levier « identifier le bâtiment » à coût nul.
- **Plafond de zoom corrigé (cause racine du flou résiduel)** : `choose_zoom` plafonnait par défaut à
  **z17 (~1,2 m/px)** — **4× plus grossier** que le natif. C'était **la** cause du flou même après le
  « rendu natif ». Wayback est désormais rendu à **z19 → 0,30 m/px** (133 m ⇒ 449 px ; 67 m ⇒ 224 px ;
  33 m ⇒ 112 px). **Sous ~60 m**, on atteint le plancher physique : réduire encore ne fait que
  rétrécir l'image, pas gagner en détail.
- **Navigation par MOTEUR DE CARTE (MapLibre, déjà au projet)** : le panneau est désormais **deux cartes
  synchronisées** Avant/Après — pan (glisser), zoom (molette/pinch), **clavier**, **clic = centrer**,
  boutons *Recentrer chantier* / *Focus bâti (zoom max)*, fitBounds sur la parcelle, échelle métrique.
  Garde-fou anti-boucle sur la synchro.
- **Rendu plus rapide (tuiles à la demande)** : les tuiles passent par un **proxy same-origin**
  `/parcel/wayback/tile` (pas de CORS, URL Esri gardée côté serveur, `Cache-Control: immutable`) →
  le navigateur ne charge que les **tuiles visibles** ; emprises OSM servies en **GeoJSON**
  (`/parcel/buildings`) comme **couche vectorielle** (plus de rasterisation serveur).

## Limites

Wayback est une **archive Esri** (termes de redistribution restreints) et sa **couverture/date** varie
par zone ; pour les tropiques sans couverture récente, la piste reste **NICFI** (ADR 0003/0006). La
voie imagerie réelle est **visuelle** : elle ne remplace pas la mesure radiométrique des jalons.
