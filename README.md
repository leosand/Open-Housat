# 🛰️ Housat — Surveillance satellite et vérification de chantiers résidentiels

[![Statut E2E](https://img.shields.io/badge/Pipeline-E2E%20Actif-06b6d4?style=flat-square&logo=satellite&logoColor=white)](docs/verification.md)
[![Images GHCR](https://img.shields.io/badge/Conteneurs-GHCR%20v0.5.4-blue?style=flat-square&logo=docker&logoColor=white)](https://github.com/leosand/Housat/pkgs/container/housat-api)
[![Donnees Copernicus](https://img.shields.io/badge/Donn%C3%A9es-Sentinel--2%20L2A%20(STAC)-purple?style=flat-square)](https://earth-search.aws.element84.com/v1)
[![Surresolution IA](https://img.shields.io/badge/Surr%C3%A9solution-SEN2SR%202%2C5%20m-emerald?style=flat-square)](https://github.com/ESAOpenSR/opensr-model)
[![Accessibilite WCAG 2.1 AA](https://img.shields.io/badge/Accessibilit%C3%A9-WCAG%202.1%20AA-emerald?style=flat-square)](https://www.w3.org/WAI/WCAG21/quickref/)

> Plateforme de télédétection et d'audit automatisé de chantiers résidentiels individuels : acquisition Sentinel-2, fond satellite haute résolution pour lisibilité, pipeline de détection et reporting technique.

**Démonstration locale :** `http://localhost:8080` (Web) | `http://localhost:8000/docs` (Spécification OpenAPI)

---

## Sommaire

- [Aperçu](#aperçu)
- [Fonctionnalités](#fonctionnalités)
- [Ce que l'outil mesure — et ce qu'il ne peut pas dire](#ce-que-loutil-mesure--et-ce-quil-ne-peut-pas-dire)
- [Architecture technique](#architecture-technique)
- [Mécanisme de détection et V&V phénoménologique](#mécanisme-de-détection-et-vv-phénoménologique)
- [Structure du dépôt](#structure-du-dépôt)
- [Démarrage local rapide](#démarrage-local-rapide)
- [Sources de données et considérations opérationnelles](#sources-de-données-et-considérations-opérationnelles)
- [Assurance qualité et critères d'acceptation](#assurance-qualité-et-critères-dacceptation)
- [Sécurité et gouvernance des données](#sécurité-et-gouvernance-des-données)
- [Feuille de route](#feuille-de-route)
- [Licence et contact](#licence-et-contact)

---

## Aperçu

**Housat** est un projet technique visant la supervision distante, objective et reproductible d'avancement de chantiers résidentiels à partir d'images satellite (Sentinel-2) couplées à des étapes d'amélioration visuelle et de détection de changements.

En combinant les données Copernicus avec des méthodes d'analyse spectrale et des workflows reproductibles, Housat fournit des pipelines automatisés de comparaison temporelle et des rapports techniques.

### Problématique & solution

```text
Chantier distant (ex. Douala, Abidjan, Port-au-Prince)
       │
       ▼
[Constat traditionnel] : Dépendance aux déclarations d'entrepreneurs locaux (asymétrie d'information, litiges).
       │
       ▼
[Approche Housat] : Sentinel-2 (révisite régulière) -> traitement multi-bandes -> détection de changements
                       -> génération de rapports techniques et visualisation cartographique.
```

---

## Fonctionnalités

| Module | Interface / Endpoint | Rôle & capacité opérationnelle |
|---|---|---|
| **Formulaire parcelle** | `/` (Web) & `POST /sites` | Enregistrement de l'emprise (bbox EPSG:4326), validation surfacique, garde anti-doublon (409). |
| **Dessin d'emprise** | `SiteMap` (MapLibre GL JS) | Permet de définir une emprise à analyser via l'UI. |
| **Rétro-analyse** | `POST /sites/{id}/backfill` | Récupération asynchrone des scènes d'archive via STAC, calage sur ancre `t0`. |
| **Vérification instantanée** | `POST /sites/{id}/check` | Interrogation de la scène la plus récente (`mode="latest"`), calcul d'évolutions et détection de franchissement d'étape. |
| **Vue visuelle** | `GET /parcel/wayback/dates`, `GET /parcel/wayback/tile` | Cartographie datée synchronisée avec couches d'archives et calques d'analyse. |
| **Caractérisation d'emprise** | `GET /parcel/buildings` (OSM/ODbL) | Extraction des bâtiments et calculs aggrégés sur l'emprise. |
| **Rapports hebdomadaires** | `GET/POST /sites/{id}/reports/{week}` | Génération de rapports PDF techniques contenant KPI et vues d'observation. |
| **Veille & alertes in-app** | `GET /sites/{id}/alerts` | Journal d'événements interne listant les jalons et changements détectés. |
| **Preuve de l'étape** | `GET /sites/{id}/progress` | Expose le plus haut jalon atteint et métadonnées associées. |

---

## Ce que l'outil mesure — et ce qu'il ne peut pas dire

> Synthèse ; le document de référence est [`docs/limites-et-honnetete.md`](docs/limites-et-honnetete.md).

**Ce qui est mesuré** : l'emprise déclarée (un rectangle). L'étape M0-M4 est la sortie d'un classifieur à seuils sur les indices NDVI/NDBI/BSI comparés à l'image d'ancrage — ce n'est pas une lecture détaillée de bâtiment.

| Limite | Conséquence concrète |
|---|---|
| **10 m par point de mesure** | Une maison individuelle = 1 à 3 points ; la résolution impose des incertitudes. |
| **Pixels mixtes** | Chaque point contient la parcelle et ses environs ; la détection peut être influencée par le contexte proche. |
| **Nuages = saison** | La disponibilité exploitable dépend fortement des conditions météorologiques. |
| **Cadence de l'archive** | La cadence effective varie selon les catalogues et les sources utilisées. |

---

## Architecture technique

### Stack technologique

| Couche | Technologie retenue |
|---|---|
| **Acquisition satellite** | STAC Client / Element84 AWS (Sentinel-2 L2A) |
| **Fond visuel (affichage)** | Fond raster pour contexte visuel |
| **Surrésolution** | Optionnel : méthodes open-source ou fallback bicubique pour affichage |
| **Moteur d'indices** | NumPy + Rasterio + Shapely |
| **Couche applicative API** | FastAPI + SQLModel |
| **Persistance & géomatique** | PostgreSQL + PostGIS / SQLite pour usages locaux |
| **Moteur d'éditique** | ReportLab pour génération PDF |
| **Frontend Web** | React + Vite + MapLibre GL |

### Flux de données de bout en bout

```text
  [ Constellation Sentinel-2 L2A ]
                 │
                 ▼ (STAC catalog search)
   pipeline/housat/worker.py -> fetch_bands(), match_shape(), detection, reporting
                 ▼
         Base de données (sites, observations, frame_store, reports)
                 ▼
        apps/api (FastAPI) -> apps/web (React + MapLibre)
```

---

## Mécanisme de détection et V&V phénoménologique

(Contenu technique inchangé ; voir `pipeline/housat` pour les implémentations mathématiques et `docs/limites-et-honnetete.md` pour les hypothèses.)

---

## Structure du dépôt

(Identique à la version technique ; voir arborescence dans la racine du repo.)

---

## Démarrage local rapide

### Prérequis

- Docker & Docker Compose (optionnel)
- Python 3.11+

### Démarrage en 1 commande (Docker Compose)

```bash
git clone https://github.com/leosand/Housat.git
cd Housat
cp .env.example .env
docker compose -f infra/docker-compose.yml up --build
```

---

## Sources de données et considérations opérationnelles

- Sentinel-2 L2A (Copernicus) via catalogues STAC.
- Respecter les licences des fonds cartographiques externes lorsqu'ils sont utilisés.
- Vérifier la compatibilité des modèles et des checkpoints avec les licences associées avant toute distribution.

---

## Assurance qualité et critères d'acceptation

(Tests unitaires, intégration et E2E sont décrits dans le dépôt ; voir `pipeline/tests` et `apps/api/tests`.)

---

## Sécurité et gouvernance des données

(Principes inchangés : ne pas committer de secrets, stocker les variables sensibles dans l'environnement, etc.)

---

## Feuille de route

La feuille de route du projet se concentre sur des améliorations techniques, la reproductibilité et la robustesse des pipelines.

---

## Licence et contact

- **Propriété intellectuelle :** Informations de propriété et contact maintenues comme dans le repo.
- **Gestionnaire du projet :** [Leonel Sandjong](https://github.com/leosand)

---

<p align="center">
  <b>Housat</b> — Ingénierie spatiale ouverte appliquée à la transparence de la construction résidentielle. 🌍🛰️
</p>
