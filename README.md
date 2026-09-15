# Housat — MVP (local, E2E)

> Verification satellite de chantiers residentiels : backfill archive Sentinel-2 -> superresolution
> -> changements vs ancre t0 -> jalons M0-M4 (V&V pivots) -> dashboard web avec **carte MapLibre/OpenStreetMap**
> et **avant/apres** (faders d'opacite georeferences sur carte + curseur pixel).
> Sans PDF, sans alertes externes, sans paiement (phase suivante).

## Demarrage local (1 commande)

```bash
docker compose -f infra/docker-compose.yml up --build
# Web : http://localhost:8080   |   API : http://localhost:8000/docs
```

Images pre-construites : ghcr.io/leosand/housat-{api,web,worker} (tag v* -> release.yml).

## Parcours

1. Creer un chantier (bbox de la parcelle — bboxfinder.com)
2. Lancer le backfill (10 scenes Sentinel-2 recentes)
3. Jalons, progression %, images par date ; alertes in-app sur franchissement
4. **Avant/Apres** : choisir deux dates ->
   - **carte OSM top-down** : polygone du chantier + scenes super-resolues georeferencees
     (coins = image_bbox exacte), faders d'opacite Avant/Apres
   - **curseur pixel** pour la comparaison fine
5. « Verifier maintenant » = verification ponctuelle vs ancre t0

## Tests et V&V

```bash
python -m pytest pipeline/tests apps/api/tests -q          # unitaires + API (0 reseau)
cd apps/web && npm install && npm run test:e2e             # Playwright (offline)
```

Criteres d'acceptation A1-A9 et runbook E2E : `docs/verification.md`.

## Stack visu (pourquoi)

MapLibre GL JS + tuiles raster OpenStreetMap : 0 $, aucune cle API, open source,
support natif des sources image georeferencees (coins TL/TR/BR/BL). Mapbox/Google rejetes (cle + cout),
Esri imagery rejete en fond par defaut (licence commerciale).

## Structure

- `pipeline/` — STAC (0 $), match_shape, SEN2SR (fallback trace), indices, frames t0, V&V, image_bbox
- `apps/api/` — FastAPI : bbox validee, backfill 202+polling, /compare, image_bbox expose, RFC 7807
- `apps/web/` — React/Vite + MapLibre : creation chantier, carte, comparateur, tests Playwright
- `infra/` — Docker Compose : PostGIS, API, web (Caddy), worker manuel
- `docs/` — architecture, ADR, analyse concurrentielle, roadmap, verification
