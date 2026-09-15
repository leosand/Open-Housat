# Changelog

Tous les changements notables de Housat sont documentes ici.
Format : [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) · Versionnage : [SemVer](https://semver.org/lang/fr/).
Horodatage ISO 8601 avec fuseau local (protocole harness-meta).

## [Unreleased]

### Fixed
- **API inimportable (bloquant)** : `Column(..., deferred=True)` n'est pas un argument
  accepte par SQLAlchemy 2.x — `apps/api/models.py` levait `TypeError` des l'import, donc
  `uvicorn main:app` ne demarrait pas et les 14 tests API ne se collectaient pas.
  Forme equivalente et portable : `orm.deferred(Column(...))` (chargement differe conserve).
- **Images API/worker non demarrables (bloquant)** : les wheels manylinux de rasterio (GDAL)
  exigent `libexpat.so.1` a l'execution, absent de `python:3.11-slim` — `import rasterio`
  echouait (`ImportError`) dans les conteneurs. Ajout de `libexpat1` dans `apps/api/Dockerfile`
  et `pipeline/Dockerfile`, avec garde d'import au build.
- **Test faux (V&V)** : `test_milestone_pivot_confirme_m2` utilisait une hausse UNIFORME, qui
  ne peut jamais produire de croissance d'emprise robuste (`{PV > q80(PV>0)}` est vide quand
  tous les pixels actifs partagent la meme valeur) — le test n'avait jamais pu passer.
  Fixture corrigee : emprise batie heterogene sur une ligne de base de terrain nu.
- **Test non representatif (V&V)** : `test_startup_dedup_puis_index_unique` croyait simuler
  une base heritee en supprimant l'index nomme, mais `create_all` materialise aussi la
  contrainte de table (autoindex SQLite), qui rejetait le doublon avant la purge testee.
  La table est desormais reconstruite dans sa forme historique (sans unicite).

### Added
- `scripts/vv_live.ps1` : harnais V&V live executant le runbook E2E documente contre la pile
  Docker et verifiant A1..A10 observables en HTTP (backfill, ancre t0, jalons monotones,
  coherence pivot, `image_bbox`, plafond 130 %, RFC 7807, PDF `%PDF` + `ETag == sha256`,
  idempotence 409).

### Security
- `.env` (copie de `.env.example`) reste ignore par git ; aucun secret en clair.

## [0.5.4] - 2026-09-15

### Added
- MVP-l4 : rapports PDF hebdomadaires persistes (ReportLab), integrite SHA-256 exposee en
  `ETag`, semaines ISO strictes et idempotence (409 sur doublon).
- Comparateur avant/apres : carte MapLibre + OSM, overlays georeferences sur `image_bbox`,
  faders d'opacite et curseur pixel.
- Backfill archive Sentinel-2 (STAC Earth Search) avec dedup amont `(site_id, obs_date)`.
- Moteur V&V phenomenologique : PV tronques (ring), emprise robuste q80, pivots dPRA,
  jalons M0..M4 et alertes in-app monotones.
