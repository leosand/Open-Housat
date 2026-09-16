# ADR 0003 — Fond visuel haute résolution pour la lisibilité de toute emprise

Statut : accepté (2026-09-15T18:53:59-04:00)

## Contexte

Un comparateur avant/après d'un carré tiré au hasard de lat/long s'est révélé **illisible** (port de
Douala). Diagnostic empirique : la seule source d'image était **Sentinel-2 à 10 m/pixel**, soit
~1–2 pixels pour une maison individuelle. Aucune surrésolution (Palier 0/1, ADR 0002) ne peut
compenser un facteur **15–30×** : le rendu embellit, il ne crée pas d'information.

Preuve du levier réel : la **même emprise** lat/long servie par une source à haute résolution
(Esri World Imagery) est parfaitement lisible — immeubles, rues, toitures distincts. Vérifié sur
trois emprises réparties sur trois contextes (Douala portuaire, Port-au-Prince, périurbain rural
du Cameroun).

Deux contraintes encadrent la solution :

1. **Couverture « toute emprise »** : la source visuelle doit répondre pour n'importe quelle bbox
   lat/long, pas seulement une zone pilote.
2. **Licence** : un rapport PDF est **redistribué** à des clients. Une source gratuite à la
   visualisation (Esri, Google) n'est **pas** librement embarquable dans un livrable commercial.

## Décision

Découpler **ce qu'on voit** (voie AFFICHAGE) de **ce qu'on mesure** (voie DÉTECTION) :

- **Voie DÉTECTION** : Sentinel-2 + indices (NDVI/NDBI/BSI) → jalons M0-M4. **Inchangée** (physique).
- **Voie AFFICHAGE** : un **fond visuel haute résolution** par emprise lat/long, fourni par une
  **cascade de fournisseurs** (`pipeline/housat/imagery/basemap.py`), chacun portant sa
  `attribution`, sa `licence` et un drapeau `redistributable`.

Mise en œuvre :

- `fetch_basemap(bbox, size=1024, provider=...)` retourne l'image **et sa provenance** ; la bbox est
  validée (ordre, bornes). Fournisseur injectable → testable sans réseau.
- CLI `python -m housat.imagery.basemap --bbox minLon,minLat,maxLon,maxLat --out f.jpg` : produit un
  carré lisible pour **n'importe quelle** emprise.
- Carte web (`apps/web/src/MapView.tsx`) : fond par défaut = **Esri World Imagery** (sans clé) au lieu
  d'OSM ; attribution conservée. Le Sentinel-2 reste en **overlay** au-dessus.

## Conséquences

- **Lisibilité « pour toujours, toute emprise »** couverte par le fond (voie affichage), indépendamment
  de la qualité Sentinel-2.
- **Le fond haute résolution n'est pas une paire temporelle** : Esri World Imagery est une mosaïque
  (date non garantie). Le **avant/après daté** reste Sentinel-2 (détection) ; le fond sert de
  **contexte lisible**. Pour un avant/après **daté et lisible** dans les tropiques, le fournisseur
  **`planet_nicfi`** (PlanetScope 4,77 m, mosaïques **mensuelles datées**, gratuit, attribution) est
  intégré à la cascade : assemblage de tuiles XYZ côté **serveur** (`PLANET_API_KEY`, **jamais** au
  navigateur — exigence du tile service Planet).
- **Rapports PDF** : `esri_world_imagery` est marqué `redistributable=False` → ne **pas** l'embarquer
  tel quel dans un rapport vendu. **Décision produit (2026-09-15) : NICFI.** Le fournisseur
  `planet_nicfi` (`redistributable=True`) est la source retenue pour les rapports — il ne reste qu'à
  fournir `PLANET_API_KEY` + `NICFI_MOSAIC`. La carte web conserve Esri (visualisation seule).

## Mise en œuvre (2026-09-15)

- `imagery/basemap.py` — deux fournisseurs : `esri_world_imagery` (mono-requête, écran) et
  `planet_nicfi` (assemblage de tuiles XYZ + recadrage bbox, serveur). Géométrie Web Mercator
  (`choose_zoom`, `tile_range`, `stitch_xyz`) pure et testée hors ligne.
- CLI : `python -m housat.imagery.basemap --bbox … --provider planet_nicfi`.
- **Non vérifié en live** faute de clé : le chemin réseau NICFI est couvert par des tests à
  `fetcher` injecté ; la validation contre le service réel reste à faire une fois la clé fournie.
- Le module est **autonome** (aucune écriture implicite, aucun réseau au build) : la conformité zero-
  dollar (ADR 0001) est préservée (le fond est une lecture à la demande, non une dépendance payante).

## Alternatives rejetées

| Alternative | Raison du rejet |
|---|---|
| Surrésoudre Sentinel-2 pour rendre l'image lisible | Impossible : facteur 15-30× d'information manquante (hallucination, pas de résolution). |
| Embarquer Esri/Google tel quel dans le PDF | Violation de licence (redistribution restreinte). |
| Google/Mapbox uniquement | Exige une clé + facturation → incompatible « zero dollar » au démarrage. |
| Attendre un fournisseur commercial unique | Bloque ; la cascade permet d'ajouter NICFI/NAIP sans refonte. |
