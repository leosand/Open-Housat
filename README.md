# 🛰️ Housat — Surveillance satellite et vérification de chantiers résidentiels

[![Statut E2E](https://img.shields.io/badge/Pipeline-E2E%20Actif-06b6d4?style=flat-square&logo=satellite&logoColor=white)](docs/verification.md)
[![Images GHCR](https://img.shields.io/badge/Conteneurs-GHCR%20v0.5.4-blue?style=flat-square&logo=docker&logoColor=white)](https://github.com/leosand/Housat/pkgs/container/housat-api)
[![Donnees Copernicus](https://img.shields.io/badge/Donn%C3%A9es-Sentinel--2%20L2A%20(STAC)-purple?style=flat-square)](https://earth-search.aws.element84.com/v1)
[![Surresolution IA](https://img.shields.io/badge/Surr%C3%A9solution-SEN2SR%202%2C5%20m-emerald?style=flat-square)](https://github.com/ESAOpenSR/opensr-model)
[![Accessibilite WCAG 2.1 AA](https://img.shields.io/badge/Accessibilit%C3%A9-WCAG%202.1%20AA-emerald?style=flat-square)](https://www.w3.org/WAI/WCAG21/quickref/)
[![Licence Proprietaire](https://img.shields.io/badge/Licence-Propri%C3%A9taire-slate?style=flat-square)](LICENSE)

> Plateforme de télédétection et d'audit automatisé de chantiers résidentiels individuels : acquisition Sentinel-2 sans frais d'entrée, fond satellite haute résolution pour une lisibilité universelle, surrésolution neuronale optionnelle (SEN2SR), qualification phénoménologique de pivots de construction (M0–M4), comparateur cartographique MapLibre et génération autonome de rapports PDF hebdomadaires vérifiables par empreinte cryptographique.

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
- [Sources de données et équation économique](#sources-de-données-et-équation-économique)
- [Assurance qualité et critères d'acceptation](#assurance-qualité-et-critères-dacceptation)
- [Sécurité et gouvernance des données](#sécurité-et-gouvernance-des-données)
- [Feuille de route 90 jours](#feuille-de-route-90-jours)
- [Licence et contact](#licence-et-contact)

---

## Aperçu

**Housat** répond à un défi économique et logistique majeur rencontré par les membres de la diaspora africaine et caribéenne : la supervision distante, objective et infalsifiable de la construction de maisons individuelles, sans intermédiaire sur place susceptible de produire de faux rapports de complaisance.

En combinant les données ouvertes du programme européen Copernicus avec des réseaux neuronaux de surrésolution spectrale et un moteur de détection de changements par hystérèse, Housat fournit un audit d'élévation physique rigoureux pour un coût marginal machine inférieur à **0,10 $ par vérification**, autorisant une tarification B2C grand public à **29 $/mois par chantier**.

### Problématique & solution

```text
Chantier distant (ex. Douala, Abidjan, Port-au-Prince)
       │
       ▼
[Constat traditionnel] : Dépendance aux déclarations d'entrepreneurs locaux (asymétrie d'information, litiges).
       │
       ▼
[Approche Housat]       : Orbite héliosynchrone (Sentinel-2, révisite 5 j) -> Surrésolution 10 m -> 2,5 m
                          -> Détection géométrique des fondations, élévations et toitures
                          -> Preuve hebdomadaire PDF scellée par SHA-256 + visualisation cartographique.
```

---

## Fonctionnalités

| Module | Interface / Endpoint | Rôle & capacité opérationnelle |
|---|---|---|
| **Formulaire parcelle** | `/` (Web) & `POST /sites` | Enregistrement de l'emprise (bbox EPSG:4326), validation surfacique (< 2 km²), garde anti-doublon (409). Défaut = **parcelle individuelle de 22 m** (~0,0002°), pas un îlot. |
| **Dessin d'emprise** | `SiteMap` (MapLibre GL JS) | « Dessiner une emprise à analyser » : clic maintenu + glissement → rectangle orange, relâche = emprise fixée sur les deux cartes synchronisées (déplacement de carte suspendu pendant le dessin), puis « Créer un chantier sur cette emprise ». |
| **Rétro-analyse** | `POST /sites/{id}/backfill` | Récupération asynchrone (HTTP 202) des scènes d'archive les moins nuageuses via STAC, calage sur ancre $t_0$ ; lancée automatiquement à la création d'un chantier depuis la carte. |
| **Vérification instantanée** | `POST /sites/{id}/check` | Interrogation de la scène la plus récente (`mode="latest"`), calcul d'évolutions et franchissement d'étape. |
| **Vue réelle haute résolution (lecture)** | `GET /parcel/wayback/dates`, `GET /parcel/wayback/tile` | Deux cartes datées synchronisées (imagerie d'archive Esri Wayback, ~0,30 m/px) avec tuiles proxifiées *same-origin* (l'URL Esri reste côté serveur, cache immuable) — c'est **la voie de lecture** : c'est là qu'on voit une maison. |
| **Caractérisation d'emprise** | `GET /parcel/buildings` (OSM/ODbL) | Bâtiments du carré, part bâtie **coupée à l'emprise** (shapely), `unavailable` si Overpass n'a pas répondu. Retiré de l'IHM (couverture nulle à Douala, service intermittent) mais conservé côté API. |
| **Rapports hebdomadaires** | `GET/POST /sites/{id}/reports/{week}` | Moteur ReportLab pur Python : KPI en langage client (« Où en est votre maison ? — étape N sur 5 »), vue HR, table d'observations, empreinte SHA-256 en en-tête `ETag`. La semaine proposée est celle de la **dernière observation**, jamais une semaine vide. |
| **Veille & alertes in-app** | `GET /sites/{id}/alerts` | Journal d'événements **monotone** : « Étape franchie : … » sans régression parasite. |
| **Preuve de l'étape** | `GET /sites/{id}/progress` | Expose **le plus haut jalon atteint** + sa preuve : `milestone_date`, `milestone_emprise` (% du carré modifié), `milestone_pv` (indice de changement), `anchor_date` (image d'ancrage). |

### Interactions utilisateur

- **Déduplication amont sans coût réseau :** Une scène d'archive ou un passage déjà analysé n'est ni re-téléchargé ni re-surrésolu (`status="duplicate"`).
- **Contrôle d'intégrité cryptographique :** Chaque rapport PDF généré est signé par son empreinte SHA-256 stockée en base et exposée dans l'en-tête HTTP `ETag`.
- **Régression d'étape neutralisée :** Les alertes **et** l'étape affichée sont strictement monotones ($M_t \ge \max(M_{<t})$) : une scène ultérieure sans changement ne « redescend » plus l'affichage à « terrain nu » (ADR 0013).
- **Vocabulaire client :** le client lit « étape », « indice de changement », « % du carré modifié » ; le jargon (`pv_sum`, `pivot_confirme`, `sr_method`) est replié dans « Détails techniques ». Table de correspondance : [`docs/glossaire.md`](docs/glossaire.md).
- **Accessibilité universelle :** Rôles ARIA explicites (`role="application"` pour la carte, `role="alert"` pour les retours API), gestion du contraste et adaptation à `prefers-reduced-motion`.

---

## Ce que l'outil mesure — et ce qu'il ne peut pas dire

> Synthèse ; le document de référence est [`docs/limites-et-honnetete.md`](docs/limites-et-honnetete.md).

**Ce qui est mesuré** : l'**emprise déclarée** (un rectangle), en entier. **Jamais un bâtiment désigné
nommément.** L'étape M0-M4 est la sortie d'un **classifieur à seuils** sur les indices NDVI/NDBI/BSI
comparés à l'**image d'ancrage** — ce n'est pas une lecture d'image, et ce n'est pas un modèle de
vision (U-Net siamois prévu en phase 2).

| Limite | Conséquence concrète |
|---|---|
| **10 m par point de mesure** | Une maison individuelle = **1 à 3 points**. Aucune surrésolution ne compense un facteur 15-30× : le bâti **se lit** sur l'imagerie d'archive (0,3-0,5 m), il **se mesure** sur Sentinel-2. Les deux voies ne se confondent jamais dans l'IHM. |
| **Pixels mixtes** | Sur une emprise de maison, chaque point contient la parcelle **et ses voisines** : l'étape peut rester « terrain nu » alors que les travaux avancent. Mesure discriminante à partir d'environ **30 m** de côté. |
| **Nuages = saison** | À Douala, **0 passage exploitable sur 33** en saison des pluies, même avec le masque par parcelle : c'est la météorologie, pas un défaut logiciel (SAR = piste, non implémentée). |
| **Cadence de l'archive** | Esri Wayback ≈ **mensuel** (dernière release vérifiée : **2026-08-05**). La cadence **5-7 j** demandée est celle de Sentinel-2 (écart médian mesuré : **3 j**). |
| **Fiabilité** | `0,55` en repli bicubique (SEN2SR non installé → ×0,7) : l'IHM l'affiche avec sa cause. |
| **Un seul processus API** | Un backfill affame le proxy de tuiles (0,5-2,1 s/tuile, rendu complet ≈ 3 s hors backfill). Correctif identifié : service `worker` séparé. |
| **Licence Esri** | Tuiles non redistribuables : affichage/lecture en ligne uniquement ; tout embarquement dans un livrable client reste **à valider juridiquement**. |

---

## Architecture technique

### Stack technologique

| Couche | Technologie retenue | Justification d'ingénierie (décision CTO) |
|---|---|---|
| **Acquisition satellite** | STAC Client / Element84 AWS | Entrées Sentinel-2 L2A gratuites, sans quota restrictif et sans clé d'API. |
| **Fond visuel (affichage)** | Esri World Imagery / Planet NICFI | Lisibilité de **toute** emprise lat/long : haute résolution à l'écran (Esri) ; NICFI 4,77 m **daté et redistribuable** pour les rapports. Sentinel-2 = détection, fond = contexte. |
| **Surrésolution** | SEN2SR (détection) · EDSR-lite ONNX (affichage) | Deux voies cloisonnées : **détection** (SEN2SR satellite ou bicubique honnête) et **affichage** (`housat_sr`, EDSR-lite ×4 servi en **ONNX Runtime CPU, sans torch**, modèle régional remplaçable — ADR 0007). Rendu PNG par étirement 2-98 % + gamma + léger rehaussement. |
| **Moteur d'indices** | NumPy + Rasterio + Shapely | Calcul vectoriel des réflectances (NDVI, NDBI, BSI), troncature d'anneau périphérique et masquage robuste. |
| **Couche applicative API** | FastAPI + SQLModel | Typage strict Python 3.11, sérialisation Pydantic v2, erreurs standardisées RFC 7807 (`application/problem+json`). |
| **Persistance & géomatique** | PostgreSQL 16 + PostGIS / SQLite | Stockage géométrique, unicité `(site_id, obs_date)`, colonnes binaires en chargement différé (`deferred=True`). |
| **Moteur d'éditique** | ReportLab 4.2 | Rendu PDF vectoriel pur Python sans dépendances système C (rejet de WeasyPrint pour incompatibilité avec conteneurs légers). |
| **Frontend Web** | React 18 + Vite + MapLibre GL | Bundle léger, fond satellite haute résolution sans abonnement tiers (Esri World Imagery) ; le Sentinel-2 reste en overlay géoréférencé. |
| **Infrastructure & orchestration** | Docker Compose multi-étapes + Caddy | Déploiement en une seule commande, conteneurs non-root sécurisés (UID 1000), reverse proxy Caddy ultra-performant. |

### Flux de données de bout en bout

```text
  [ Constellation Sentinel-2 L2A ]
                 │
                 ▼ (STAC catalog search - 0 $)
   ┌──────────────────────────────────────────────┐
   │         pipeline/housat/worker.py            │
   │  ├─ fetch_bands()   : clip rasterio + reproj │
   │  ├─ upscale_bands() : surrésolution SEN2SR   │
   │  ├─ match_shape()   : calage géométrique t0  │
   │  └─ observations.py : PV_i, pivots, jalons   │
   └──────────────────────┬───────────────────────┘
                          │ Ingestion persistante (déduplication amont)
                          ▼
   ┌──────────────────────────────────────────────┐
   │             Base de données                  │
   │  ├─ sites         : polygones GeoJSON EPSG   │
   │  ├─ observations  : jalons, pv_sum, image_png│
   │  ├─ frame_store   : états matriciels t0/prev │
   │  └─ reports       : PDF compilés + SHA-256   │
   └──────────────┬───────────────────────────────┘
                  │
        ┌─────────┴─────────┐
        ▼                   ▼
┌──────────────────┐  ┌────────────────────────────────────────┐
│  apps/api        │  │  .github/workflows/weekly-report.yml  │
│  FastAPI (8000)  │  │  Génération cron lundis 12:00 UTC      │
└───────┬──────────┘  └────────────────────────────────────────┘
        │ Contrats JSON RFC 7807 + flux binaires mis en cache
        ▼
┌──────────────────────────────────────────────────────────────┐
│  apps/web (React 18 + Vite + MapLibre sur Caddy : 8080)       │
│  ├─ Formulaire de bornage parcellaire (bboxfinder compatible)│
│  ├─ Dashboard de progression temporelle & alertes monotones  │
│  ├─ Carte (fond satellite + calques géoréférencés TL/TR/BR/BL)│
│  └─ Téléchargement instantané des rapports PDF certifiés     │
└──────────────────────────────────────────────────────────────┘
```

### Principes de conception appliqués

1. **Intégrité scientifique d'abord :** L'ordre des bandes spectrales respecte la physique du capteur Sentinel-2 (`blue`, `green`, `red`, `nir`, `swir16`). La bande SWIR-1 (20 m) est rééchantillonnée sur la grille 10 m avant le calcul du NDBI et du BSI.
2. **Économie de bande passante et frugalité mémoire :** Les attributs volumineux (`image_png`, `pdf`, `frame_store.data`) sont déclarés en chargement différé SQL. La présence d'image est vérifiée par projection `IS NOT NULL` pour bannir toute anomalie N+1.
3. **Idempotence et exclusion mutuelle :** Les doubles clics et requêtes parallèles sur les rétro-analyses (`/backfill`) sont verrouillés en base par commit préalable du statut `running` avant l'émission de la réponse HTTP 202.
4. **Cache HTTP immuable :** Les images d'observations et les éditions PDF portent l'en-tête `Cache-Control: public, max-age=31536000, immutable`, prévenant toute re-consommation inutile de calcul.

---

## Mécanisme de détection et V&V phénoménologique

Contrairement aux solutions généralistes reposant sur des seuils statistiques arbitraires, Housat implémente un modèle de détection bi-temporel qualifié :

### 1. Variables de Perturbation Validée (PV)
Pour chaque indice spectral $i \in \{\text{NDVI}, \text{NDBI}, \text{BSI}\}$ par rapport à la référence d'ancrage $t_0$ :
$$\Delta_i = I_{i, t} - I_{i, t0}$$
$$PV_i = \text{clip}(\Delta_i, 0, +\infty)$$

Une troncature périphérique d'anneau externe ($\text{ring} = 1$) est appliquée systématiquement pour éliminer les artefacts sub-pixellaires de bordure de découpe.

### 2. Emprise robuste et somme d'énergie
L'emprise robuste unifiée est construite à partir du quantile 80 des pixels actifs :
$$m_i = \{ PV_i > q_{80}(PV_i > 0) \}$$
$$m_{\text{joint}} = m_{\text{NDVI}} \cup m_{\text{NDBI}} \cup m_{\text{BSI}}$$
La métrique $pv\_sum$ représente la somme masquée de cette énergie, permettant le calcul d'avancement inter-périodes :
$$\text{Progression}_{t1 \to t2} = 100 \times \min\left(\frac{pv\_sum(t_2)}{\max(pv\_sum(t_1), 10^{-6})}, 1.3\right)$$

### 3. Qualification d'un pivot de chantier
Un franchissement physique (fondations achevées, démarrage des maçonneries ou toiture) est qualifié lorsque le différentiel d'énergie relative $\text{dPRA}$ domine nettement les résidus négatifs :
$$\text{dPRA} = \frac{\sum \text{div}[+]}{\sum PV_t[+]} > 0{,}15 \quad \text{ET} \quad |\overline{\text{div}[-]}| < 0{,}05$$

### 4. Classification des jalons opérationnels

```text
[M0 : Terrain nu]
       │
       ▼ (Hausse marquée du BSI, sol terrassé découvert)
[M1 : Fondation détectée]
       │
       ▼ (Pivot confirmé + croissance d'emprise bâtie dPRA > 0.15)
[M2 : Structure en progression (murs / élévation)]
       │
       ▼ (Plateau NDBI, stabilisation d'emprise, pic de réflectance toiture)
[M3 : Toiture probable]
       │
       ▼ (Stabilisation complète, rémanence végétale environnante)
[M4 : Finition / aménagement extérieur]
```

---

## Structure du dépôt

```text
Housat/
├── .github/
│   └── workflows/
│       ├── ci.yml                 # Intégration continue : Ruff, Pytest API & Pipeline, build Web
│       ├── release.yml            # Publication des images conteneurisées sur GHCR (tags v*)
│       └── weekly-report.yml      # Cron de génération des rapports PDF (lundis 12:00 UTC)
├── apps/
│   ├── api/
│   │   ├── Dockerfile             # Image conteneur API non-root (Python 3.11-slim)
│   │   ├── main.py                # Contrôleur FastAPI v0.5.4, gestionnaire RFC 7807, startup DB
│   │   ├── models.py              # Schéma SQLModel, chargement différé des BLOBs et contraintes
│   │   ├── requirements.txt       # Dépendances de production de l'API
│   │   └── tests/
│   │       ├── test_api.py        # Tests d'intégration HTTP (TestClient, SQLite isolé)
│   │       ├── test_reports.py    # Cycle complet des routes de rapports PDF (201, 409, ETag)
│   │       └── test_dedup_migration.py # Validation de la purge au démarrage et de l'index unique
│   └── web/
│       ├── Dockerfile             # Construction multi-étapes Node.js 20 -> Caddy 2 Alpine
│       ├── package.json           # Dépendances React 18, MapLibre GL, Vite, Playwright
│       ├── playwright.config.ts   # Configuration des suites E2E navigateur
│       ├── index.html             # En-tête HTML5 sémantique, méta AEO/SEO
│       ├── e2e/
│       │   └── app.spec.ts        # Tests Playwright hors-ligne (résilience réseau)
│       └── src/
│           ├── main.tsx           # Point d'entrée de l'application cliente
│           ├── App.tsx            # Dashboard, dessin d'emprise, état + preuve, panneaux rapports
│           └── styles.css         # Système de design responsive épuré
├── pipeline/
│   ├── Dockerfile                 # Image conteneur worker autonome (CLI de traitement batch)
│   ├── requirements.txt           # Dépendances scientifiques (Rasterio, Shapely, ReportLab)
│   ├── tests/
│   │   ├── test_change.py         # Tests des réflectances spectrales et scores adaptatifs
│   │   ├── test_frames.py         # Sérialisation des matrices NPZ, calage match_shape
│   │   ├── test_reporting.py      # Validation du rendu ReportLab et de l'encodage Latin-1
│   │   ├── test_reporting_db.py   # Persistance SQL des éditions PDF et vérification d'empreinte
│   │   └── test_vv_regressions.py # Non-régression sur l'ordre physique des bandes et pivots purs
│   └── housat/
│       ├── __init__.py            # Métadonnées de version du module scientifique
│       ├── config.py              # Configuration typée (Pydantic Settings)
│       ├── observations.py        # Cœur mathématique V&V : PV, pivots, masques robustes
│       ├── reporting.py           # Compilateur PDF A4 (KPIs, tables, flowables, métadonnées)
│       ├── worker.py              # Orchestration des rétro-analyses et vérifications ponctuelles
│       ├── alerts/
│       │   └── notify.py          # Adaptateurs de notification SMTP / ntfy (durcis avec timeout)
│       ├── detection/
│       │   ├── change.py          # Algèbre spectrale (NDVI, NDBI, BSI, seuillage adaptatif)
│       └── milestones.py      # Règles de transition d'états de chantier
│       └── imagery/
│           ├── sentinel2.py       # Interrogation du catalogue STAC Element84 et découpe CRS
│           ├── rendering.py       # Rendu d'affichage RGB (étirement percentile 2-98 % + gamma + rehaussement)
│           ├── basemap.py         # Fond visuel haute résolution pour toute emprise lat/long (cascade + licence)
│           └── super_resolution.py# Surrésolution à deux voies : SEN2SR (détection) + ONNX (affichage)
├── infra/
│   └── docker-compose.yml         # Environnement local complet (PostGIS, API, Web, Worker)
├── docs/
│   ├── architecture.md            # Spécification détaillée des flux et modes dégradés
│   ├── competitive-analysis.md    # Analyse de marché et positionnement unitaire (diaspora)
│   ├── roadmap-90-days.md         # Jalons de mise sur le marché et modèle de revenus
│   ├── verification.md            # Matrice d'assurance qualité et critères A1 à A10
│   ├── limites-et-honnetete.md    # DOCUMENT DE RÉFÉRENCE : ce qui est mesuré, ce qui ne peut pas être affirmé
│   ├── glossaire.md               # Jargon interne ↔ langage client (règle d'écriture de l'IHM)
│   └── adr/
│       ├── 0001-stack-zero-dollar.md                   # Arbitrages d'ingénierie sur l'infrastructure gratuite
│       ├── …
│       ├── 0010-masque-nuage-par-parcelle.md           # Filtrer les nuages sur la parcelle, pas la tuile
│       ├── 0011-emprise-dessinee-et-portee-de-la-mesure.md  # L'utilisateur dessine ; la mesure porte sur l'emprise
│       ├── 0012-validite-de-la-mesure-petites-emprises.md    # filled=False + voisinage SCL 60 m (maisons 10-20 m)
│       └── 0013-etape-monotone-et-preuve-affichee.md         # Étape = plus haut jalon + preuve chiffrée affichée
├── .gitignore
├── .env.example                   # Gabarit des variables d'environnement documentées
└── README.md
```

---

## Démarrage local rapide

### Prérequis

- **Docker & Docker Compose** (recommandé pour une mise en service immédiate)
- Ou pour un développement natif : **Python 3.11+**, **Node.js 20+**, bibliothèques GDAL/GEOS sous-jacentes.

### Démarrage en 1 commande (Docker Compose)

```bash
# 1. Cloner le référentiel
git clone https://github.com/leosand/Housat.git
cd Housat

# 2. Copier l'environnement d'exemple
cp .env.example .env

# 3. Lancer l'ensemble des conteneurs
docker compose -f infra/docker-compose.yml up --build
```

Accédez aux services une fois initialisés :
- 🌐 **Interface utilisateur Web :** [http://localhost:8080](http://localhost:8080)
- 🚀 **Documentation interactive Swagger/OpenAPI :** [http://localhost:8000/docs](http://localhost:8000/docs)

### Parcours utilisateur de validation (E2E)

1. Ouvrez l'interface web sur `http://localhost:8080`.
2. Créez un nouveau chantier en saisissant une boîte englobante (les coordonnées par défaut de Douala sont pré-remplies ; vous pouvez utiliser [bboxfinder.com](http://bboxfinder.com) pour d'autres parcelles).
3. Cliquez sur **« Lancer le backfill archive »** : le statut passe en exécution continue (`running`), interroge le catalogue STAC et télécharge les scènes historiques.
4. Consultez le tableau de bord actualisé automatiquement : le jalon détecté s'affiche avec son niveau de confiance métrologique.
5. Utilisez le module **Avant / Après** :
   - Inspectez la parcelle sur la carte interactive avec les faders d'opacité superposés au cadastre OpenStreetMap.
   - Manipulez le curseur coulissant pour un comparatif pixel par pixel des scènes super-résolues.
6. Cliquez sur **« Générer le rapport de la semaine dernière »** : le document PDF compilé apparaît instantanément en téléchargement avec son empreinte SHA-256 scellée.

---

## Sources de données et équation économique

| Intrant / Composant | Source technique | Structure de coût | Impact sur la viabilité |
|---|---|---|---|
| **Imagerie multispectrale** | Sentinel-2 L2A via AWS Element84 | **0,00 $** (Open Data Copernicus) | Aucun abonnement fournisseur (vs 7–12 $/km² chez Planet/SkyWatch). |
| **Calcul d'inférence** | Runner local / GitHub Actions | **0,00 $** (Tier gratuit 2 000 min/mois) | Traitement par lots automatisé lors des révisites satellitaires. |
| **Fond cartographique** | Tuiles raster OpenStreetMap | **0,00 $** (Licence ODbL / Open Data) | Visualisation spatiale sans clé propriétaire (rejet de Mapbox/Google). |
| **Persistance des livrables** | PostgreSQL local / Cloudflare R2 | **0,00 $** (Tier gratuit sans coût d'egress) | Rétention pérenne des rapports d'avancement scellés. |
| **Coût unitaire marginal** | Calcul machine consolidé | **~0,05 $ / vérification** | **Marge brute supérieure à 85 %** sur le forfait cible de 29 $/mois. |

---

## Assurance qualité et critères d'acceptation

La chaîne de traitement est validée par une pyramide de tests stricts exécutés en environnement hermétique sans dépendance réseau :

```bash
# 1. Exécution des tests unitaires, algorithmiques et API (Python)
PYTHONPATH=pipeline:apps/api python -m pytest pipeline/tests apps/api/tests -v

# 2. Exécution des tests d'intégration navigateur (Playwright)
cd apps/web && npm install && npm run test:e2e
```

### Grille de conformité V&V (Norme interne Housat)

| Identifiant | Règle de vérification | Seuil d'acceptation opérationnel | Statut |
|---|---|---|:---:|
| **A1** | Succès de rétro-analyse | $\ge 2$ scènes ingérées, statut final `done` | ✅ Validé |
| **A2** | Pérennité de l'ancre $t_0$ | `frame_store.anchor == True`, comparaisons toutes rattachées à la base | ✅ Validé |
| **A3** | Monotonie des alertes | Aucune régression de jalon émise ($M_t \ge M_{t-1}$) | ✅ Validé |
| **A4** | Cohérence phénoménologique | Jalon $M_2/M_3 \iff \text{pivot\_confirmé} == \text{True}$ | ✅ Validé |
| **A5** | Traçabilité de l'inférence | Méthode (`sen2sr` ou `bicubic_fallback`) consignée dans chaque observation | ✅ Validé |
| **A6** | Format des anomalies | 404, 409, 422 conformes RFC 7807 (`application/problem+json`) | ✅ Validé |
| **A7** | Zéro alerte non sollicitée | Aucune fuite d'émission externe en mode local | ✅ Validé |
| **A8** | Précision avant/après | Grilles recalées via `match_shape`, progression plafonnée à 130 % | ✅ Validé |
| **A9** | Fidélité cartographique | Coins raster superposés coïncidant avec l'`image_bbox` à $\pm 1$ pixel | ✅ Validé |
| **A10** | Intégrité des rapports PDF | Document généré sans réseau, idempotence (HTTP 409 sur doublon), ETag = SHA-256 | ✅ Validé |

---

## Sécurité et gouvernance des données

- **Exclusion de secrets en clair :** Aucune clé d'authentification ni identifiant n'est consigné dans les sources. Toute variable sensible est injectée par l'environnement (`.env`).
- **Contrôle d'accès aux fichiers statiques :** L'API et le worker fonctionnent sous un utilisateur système non privilégié (`housat`, UID 1000).
- **Protection contre les requêtes d'emprise abusives :** L'envergure des parcelles est bridée dès la validation du modèle Pydantic ($\Delta_{\text{lon}} \times \Delta_{\text{lat}} \le 0{,}005$, soit $\approx 2\text{ km}^2$), interdisant les dénis de service par allocation matricielle excessive.
- **Conformité au respect de la vie privée :** Aucune télémétrie commerciale, aucun témoin de connexion publicitaire (*cookie*) ni pistage tiers n'est implanté sur l'application web.

---

## Feuille de route 90 jours

```text
  Phase 0 : Socle V&V & MVP local (Terminée - v0.5.4)
  [x] Acquisition Sentinel-2 STAC 0 $ + surrésolution SEN2SR
  [x] Qualification phénoménologique des pivots (M0 à M4)
  [x] Tableau de bord web React 18 + carte MapLibre (fond satellite haute résolution) synchronisée
  [x] Génération de rapports PDF certifiés par hachage SHA-256
  [x] Durcissement des flux de données (grilles unifiées, déduplication, chargement différé)
         │
         ▼
  Phase 1 : Industrialisation des alertes & Monétisation B2C (J15–J45)
  [ ] Réactivation du module d'alerte externe (notifications courriel avec envoi du PDF)
  [ ] Passerelle de paiement Stripe Checkout (abonnement 29 $/mois/chantier)
  [ ] Portail client en libre-service avec authentification sécurisée
         │
         ▼
  Phase 2 : Précision géométrique & Multi-plateforme (J46–J75)
  [ ] Recalage géodésique fin par points d'amer (warp GCP) pour grands chantiers
  [ ] Intégration de l'API WhatsApp Business pour la réception directe des alertes
  [ ] Déploiement mobile React Native (iOS / Android)
         │
         ▼
  Phase 3 : Offre B2B & Imagerie très haute résolution (J76–J90)
  [ ] Option d'imagerie commerciale 50 cm à la demande en cas de litige constaté
  [ ] Portail institutionnel pour prêteurs et assureurs de la diaspora
```

---

## Licence et contact

- **Propriété intellectuelle :** Tous droits réservés. Architecture logicielle, modèles phénoménologiques et interfaces développés par **Leonel Sandjong**.
- **Gestionnaire du projet :** [Leonel Sandjong](https://github.com/leosand)
- **Signalement d'anomalies :** [GitHub Issues](https://github.com/leosand/Housat/issues)

---

<p align="center">
  <b>Housat</b> — Ingénierie spatiale ouverte appliquée à la transparence de la construction résidentielle. 🌍🛰️
</p>
