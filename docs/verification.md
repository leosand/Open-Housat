# Plan V&V — Housat MVP-l3

Objectif : demontrer localement la chaine E2E — backfill archive Sentinel-2, jalons M0-M4
(pivots V&V), comparaison avant/apres **sur carte** (MapLibre + OSM) ET au curseur.

## Indicateurs phenomenologiques (pipeline/housat/observations.py)

- PV_i = clip(delta_i vs t0, 0, +inf), troncature anneau externe (ring=1), i in {NDVI, NDBI, BSI}
- Alignement grille : match_shape() avant TOUT calcul de PV/div (corrige le desalignement latent)
- Emprise robuste : m_i = { PV_i > q80(PV_i > 0) } ; pv_sum = somme masquee jointe des 3 indices
- Progression inter-periodes : 100 x pv_sum(t2)/pv_sum(t1), cap 130 %
- Pivot qualifie : dPRA > 0.15 ET |moyenne(div[-])| < 0.05
- Jalons M0..M4 ; alertes in-app monotones
- **image_bbox (EPSG:4326) persistee par observation** = emprise exacte de la fenetre de clip —
  garantit que l'overlay carte repose la scene aux memes coordonnees que les calculs

## Visualisation (apps/web)

- MapLibre GL JS + tuiles raster OSM (0 $, sans cle, attribution OSM visible)
- Polygone du chantier : fill + contour, fitBounds automatique
- Overlays images (type 'image', coins TL/TR/BR/BL = image_bbox) avec faders d'opacite
  independants Avant/Apres -> fondu croise top-down fidele aux calculs
- Curseur pixel (clip-path) conserve pour la comparaison fine ; tests Playwright offline

## Tests automatises

| Couche | Fichier | Couverture |
|---|---|---|
| Unitaires detection | pipeline/tests/test_change.py | indices, score adaptatif, jalons, low_confidence |
| Unitaires V&V/pivot | pipeline/tests/test_frames.py | frames, ring, divPV, pivot, M2/M0, PNG, match_shape |
| API (TestClient) | apps/api/tests/test_api.py | 201/422/404 RFC 7807, compare (422/404) |
| E2E web (Playwright) | apps/web/e2e/app.spec.ts | accueil, formulaire, erreur sans API (offline) |

## Runbook E2E manuel

1. `docker compose -f infra/docker-compose.yml up --build`
2. http://localhost:8080 — creer un chantier (bbox Douala pre-remplie)
3. Backfill -> observations + images
4. Avant/Apres : choisir deux dates -> la CARTE montre les deux scenes SR superposees a OSM
   (faders), le curseur montre la comparaison pixel ; verifier que la parcelle bleue
   recouvre exactement les overlays (±1 px)
5. « Verifier maintenant », alertes in-app si jalon franchi

## Criteres d'acceptation MVP-l3

| # | Critere | Seuil |
|---|---|---|
| A1-A8 | inchanges (cf. historique) | cf. commits precedents |
| A9 | **Overlay carte fidele** | coins overlay = image_bbox du payload = bbox parcelle (6 dec.), double rendu slider+carte coherent sur les memes dates |

## Limites documentees (dette assumee)

- Overlay positionne par bbox (pas de warp geodesique fin) — suffisant pour des parcelles,<br/>
  phase 2 : export GeoTIFF georeference + source raster-tiles.
- Tuiles OSM : usage local/test uniquement (politique tuiles OSM) ; production -> tuiles auto-hebergees ou MapTiler.
- Toiture/finition indifferencees a 2,5 m ; comparaison ancre uniquement ; scenes nuageuses marquees.
