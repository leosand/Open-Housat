# Plan V&V — Housat MVP-l4

Objectif : demontrer localement la chaine E2E — backfill archive Sentinel-2, jalons M0-M4
(pivots V&V), comparaison avant/apres **sur carte** (MapLibre + OSM) ET au curseur,
**rapports PDF hebdomadaires** persistes et telechargeables.

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

## Rapports PDF hebdomadaires (pipeline/housat/reporting.py)

- reportlab (pur Python) : aucune dependance systeme, compatible images slim non-root
- Semaines ISO strictes (lundi..dimanche) ; generation manuelle POST ou cron lundi
  (.github/workflows/weekly-report.yml, runner gratuit = 0 $)
- Dedup garanti par contrainte UNIQUE (site_id, week_start) ; integrite : sha256 du PDF
  persiste et expose en ETag de telechargement
- Contenu : KPI (jalon, pivot, progression pv_sum semaine — meme regle que /compare),
  images avant/apres (memes PNG que la carte), tableau des observations, alertes,
  methodologie + limites ; aucune IO reseau (aucun appel STAC)

## Tests automatises

| Couche | Fichier | Couverture |
|---|---|---|
| Unitaires detection | pipeline/tests/test_change.py | indices, score adaptatif, jalons, low_confidence |
| Unitaires V&V/pivot | pipeline/tests/test_frames.py | frames, ring, divPV, pivot, M2/M0, PNG, match_shape |
| Unitaires rapports | pipeline/tests/test_reporting.py | semaines ISO, KPI, rendu PDF (%PDF, > 2 Ko), Latin-1 |
| API (TestClient) | apps/api/tests/test_api.py | 201/422/404 RFC 7807, compare (422/404) |
| API rapports (TestClient) | apps/api/tests/test_reports.py | cycle 201/409/GET pdf+ETag, 422 semaines invalides/vides, 404 |
| E2E web (Playwright) | apps/web/e2e/app.spec.ts | accueil, formulaire, erreur sans API (offline) |

## Runbook E2E manuel

1. `docker compose -f infra/docker-compose.yml up --build`
2. http://localhost:8080 — creer un chantier (bbox Douala pre-remplie)
3. Backfill -> observations + images
4. Avant/Apres : choisir deux dates -> la CARTE montre les deux scenes SR superposees a OSM
   (faders), le curseur montre la comparaison pixel ; verifier que la parcelle bleue
   recouvre exactement les overlays (±1 px)
5. « Verifier maintenant », alertes in-app si jalon franchi
6. **Rapport PDF** : « Generer le rapport de la semaine derniere » dans le dashboard ->
   le lien de telechargement apparait (GET /sites/{id}/reports/{lundi}/pdf) ;
   re-cliquer -> 409 « rapport deja genere » (idempotence)

## Criteres d'acceptation MVP-l4

| # | Critere | Seuil |
|---|---|---|
| A1-A9 | inchanges (cf. historique) | cf. commits precedents |
| A10 | **Rapport hebdo fiable et integre** | PDF %PDF genere sans reseau a partir des observations persistees ; 422 si semaine vide/invalide/en cours ; 409 sur doublon ; ETag = sha256 du PDF ; cron lundi documente |

## Limites documentees (dette assumee)

- Overlay positionne par bbox (pas de wrap geodesique fin) — suffisant pour des parcelles ;
  phase 2 : export GeoTIFF georeference + source raster-tiles.
- Rapports : police Helvetica Latin-1 (accents FR ok, glyphes etendus remplaces) ;
  images avant/apres uniquement (pas de serie complete embarquee) ; envoi par courriel = phase 2.
- Tuiles OSM : usage local/test uniquement ; production -> tuiles auto-hebergees ou MapTiler.
- Toiture/finition indifferencees a 2,5 m ; comparaison ancre uniquement ; scenes nuageuses marquees.
