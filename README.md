# Housat — MVP-l1 (local, E2E)

> Verification satellite de chantiers residentiels. Cette branche livre le MVP fonctionnel de bout en bout :
> backfill archive Sentinel-2 -> superresolution -> changements vs scene d'ancrage t0 -> jalons M0-M4 (V&V phenomenologique) -> dashboard web. Sans PDF, sans alertes externes, sans paiement (phase suivante).

## Demarrage local (1 commande)

```bash
docker compose -f infra/docker-compose.yml up --build
# Web : http://localhost:8080   |   API : http://localhost:8000/docs
```

1. Creer un chantier (bbox de la parcelle, ex. depuis bboxfinder.com)
2. Lancer le backfill (10 scenes Sentinel-2 recentes, les moins nuageuses)
3. Suivre jalons, progression %, images PNG par observation dans le dashboard
4. « Verifier maintenant » = verification manuelle vs derniers passages Sentinel-2

## Tests et V&V

```bash
pip install -r pipeline/requirements.txt -r apps/api/requirements.txt
python -m pytest pipeline/tests apps/api/tests -q
```

Criteres d'acceptation et runbook E2E : `docs/verification.md`.

## Structure

- `pipeline/` — acquisition STAC (0 $), superresolution SEN2SR (fallback bicubique trace), indices, frames ancrees t0, indicateurs V&V (PV, pivots, divPV), alertes in-app
- `apps/api/` — FastAPI : chantiers (bbox/GeoJSON), backfill 202+polling, check manuel, images PNG, erreurs RFC 7807
- `apps/web/` — React/Vite minimal : creation de chantier, dashboard jalons/progression/images
- `infra/` — Docker Compose : PostGIS, API, web (build static + Caddy), worker manuel
- `docs/` — architecture, ADR stack 0 $, analyse concurrentielle, roadmap, verification
