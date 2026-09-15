# Housat — MVP (local, E2E)

> Verification satellite de chantiers residentiels : backfill archive Sentinel-2 ->
> superresolution -> changements vs scene d'ancrage t0 -> jalons M0-M4 (V&V phenomenologique) ->
> dashboard web avec **comparaison avant/apres entre periodes** (curseur coulissant).
> Sans PDF, sans alertes externes, sans paiement (phase suivante).

## Demarrage local (1 commande)

```bash
docker compose -f infra/docker-compose.yml up --build
# Web : http://localhost:8080   |   API : http://localhost:8000/docs
```

Option sans build (apres un tag vX.Y.Z) :
`ghcr.io/leosand/housat-api|web|worker` — voir .github/workflows/release.yml.

1. Creer un chantier (bbox de la parcelle, ex. depuis bboxfinder.com)
2. Lancer le backfill (10 scenes Sentinel-2 recentes, les moins nuageuses)
3. Jalons, progression %, images PNG par date ; alertes in-app sur franchissement
4. **Avant/Apres** : deux selecteurs de date + curseur coulissant sur les images
   super-resolues, pixel-alignees (match_shape), avec delta de jalon et progression de periode
5. « Verifier maintenant » = verification ponctuelle vs ancre t0

## Tests et V&V

```bash
python -m pytest pipeline/tests apps/api/tests -q          # unitaires + API (0 reseau)
cd apps/web && npm install && npm run test:e2e             # Playwright (offline)
```

Criteres d'acceptation A1-A8 et runbook E2E : `docs/verification.md`.

## Structure

- `pipeline/` — STAC (0 $), match_shape (alignement grille), SEN2SR (fallback bicubique trace),
  indices, frames ancerees t0, indicateurs V&V (PV, pv_sum, pivots), alertes in-app monotones
- `apps/api/` — FastAPI : bbox validee, backfill 202+polling, check, /compare avant-apres,
  images PNG, RFC 7807
- `apps/web/` — React/Vite : creation chantier, dashboard, comparateur avant/apres, tests Playwright
- `infra/` — Docker Compose : PostGIS, API, web (Caddy), worker manuel
- `docs/` — architecture, ADR stack 0 $, analyse concurrentielle, roadmap, verification
