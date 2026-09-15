# Housat

> Verification automatique de chantiers residentiels par imagerie satellite — stack 0 $, Sentinel-2 gratuit + superresolution IA + detection de changements.
> Automated satellite monitoring of individual residential construction sites — $0 stack, free Sentinel-2 + AI super-resolution + change detection.

Replica bout-en-bout du mecanisme GammaEarth (superresolution du Sentinel-2 gratuit) applique a un cas B2C inexplore : le suivi de chantier d'une maison individuelle, avec jalons detectes et alertes — pour les proprietaires en diaspora (~29 $/mois/chantier).

## Pourquoi l'economie tient / Why the math works

| Levier | Cout |
|---|---|
| Imagerie Sentinel-2 L2A (5 jours de revisite) | 0 $ |
| Calcul (GitHub Actions runner / Colab) | 0 $ |
| Stockage (MinIO local / Cloudflare R2 free tier) | 0 $ |
| Alertes (ntfy.sh + SMTP) | 0 $ |
| Cout marginal d'une verification | ~2 $ |
| Prix B2C vise | 29 $/mois/chantier |

## Architecture

```
Sentinel-2 L2A (STAC, Earth Search)  ─┐
                                      ├─> pipeline/  fetch -> SR -> indices -> changement -> jalons -> alertes
Copernicus Data Space (backup)      ─┘        │
                                              v
apps/api (FastAPI + PostGIS)  <──  observations / alertes / rapports
        │
        v
apps/web (Next.js, phase 2)  —  landing SEO/AEO/GEO + dashboard proprietaire
```

## Structure

- `pipeline/` — coeur Python : acquisition, superresolution, detection, jalons, alertes
- `apps/api/` — API produit (FastAPI, SQLModel, erreurs RFC 7807)
- `apps/web/` — vitrine + dashboard (phase 2, Next.js + 5 piliers SEO/AEO/GEO/AIO/SXO)
- `infra/` — Docker Compose (PostGIS, API, worker, MinIO)
- `docs/` — architecture, ADR, analyse concurrentielle, feuille de route 90 jours

## Quickstart (FR-CA)

```bash
cp .env.example .env
pip install -r pipeline/requirements.txt -r apps/api/requirements.txt
docker compose -f infra/docker-compose.yml up -d db minio
python -m housat.worker --once            # traite tous les chantiers actifs
uvicorn main:app --app-dir apps/api       # API sur :8000
```

## Sources d'inspiration (audit GitHub)

- ESAOpenSR/opensr-model + SEN2SR — moteur de superresolution adopte tel quel
- lanha/DSen2 — fallback CPU
- LiheYoung/SenseEarth2020-ChangeDetection — inspiration du module deep de detection
- abhijeet3922/Change-Detection-in-Satellite-Imagery — PCA + k-means adapte

Licence proprietaire — tous droits reserves. Voir `docs/` pour la strategie de commercialisation.
