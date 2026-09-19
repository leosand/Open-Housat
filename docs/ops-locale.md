# Exploitation locale de la pile — runbook mesuré

> *Local stack operations — measured runbook. Every number below was observed on this workstation,
> not estimated. Commands that failed are listed with their raw output.*
>
> **Dernière vérification : 2026-09-19** (Docker 29.8.0, Compose v5.5.1, Windows + Git Bash).
> Toutes les commandes supposent la racine du dépôt `Housat` comme répertoire courant.

---

## 1. Prérequis (à vérifier avant tout)

```bash
docker version --format 'client={{.Client.Version}} server={{.Server.Version}}'   # attendu : 29.8.0
docker compose version                                                           # attendu : v5.5.1
git rev-parse --abbrev-ref HEAD                                                  # attendu : main
git log --oneline -1                                                             # attendu : d2fbf22 ou descendant
docker compose -f infra/docker-compose.yml --profile manual ps                   # attendu : VIDE
```

> **Le `--profile manual` n'est pas décoratif.** `docker compose ps` sans profil ne montre **pas** le
> worker, et `docker compose down` sans profil ne le **supprime pas**. C'est la cause de la panne
> n° 2 ci-dessous. Prendre l'habitude de toujours passer `--profile manual` sur `ps`, `down`, `logs`.

## 2. Construction

```bash
docker compose -f infra/docker-compose.yml build
```

**Garde `libexpat1`** (exigence d'exécution des wheels manylinux de `rasterio`) — vérification directe
dans l'image, plus fiable que de relire un journal de build :

```bash
docker run --rm --entrypoint bash infra-api -c \
  "dpkg -l libexpat1 | tail -1; python -c 'import rasterio; print(rasterio.__version__)'"
# mesuré : ii libexpat1:amd64 2.8.3-1~deb13u1 ... / rasterio 1.4.4
```

Le journal de build doit aussi porter la ligne :
`#NN [api N/10] RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 curl ca-certificates`

## 3. Démarrage

```bash
docker compose -f infra/docker-compose.yml up -d db api
docker compose -f infra/docker-compose.yml --profile manual ps
```

Attendu : `db` **healthy**, `api` **Up**. Le `depends_on: db: {condition: service_healthy}` garantit
l'ordre ; le `restart: unless-stopped` de `db` évite la panne n° 1.

### Worker — service PONCTUEL

Le worker fait **une passe** sur les chantiers puis sort avec le code **0**. Ce n'est pas un plantage.

```bash
# Usage recommande : conteneur ephemere, aucun residu possible
docker compose -f infra/docker-compose.yml run --rm worker

# Alternative (up -d) : possible, mais lire la panne n° 2 avant
docker compose -f infra/docker-compose.yml --profile manual up -d worker
```

## 4. V&V — les trois niveaux

```bash
# a) Tests 08 dans le conteneur (12 tests)
docker compose -f infra/docker-compose.yml exec -T api pytest -q /srv/tests/test_08_openbuildings_temporal.py

# b) Suite COMPLETE dans le conteneur (112 tests) — les trois chemins sont necessaires
docker compose -f infra/docker-compose.yml exec -T api pytest -q /srv/pipeline/tests /srv/api/tests /srv/tests

# c) Parcours E2E reel, dans le conteneur (28 assertions A1-A10, ~11 min : backfill reseau)
docker compose -f infra/docker-compose.yml exec -T api bash /srv/scripts/vv_live.sh
```

Mesuré le 2026-09-19 : **12 passed** (a), **112 passed** (b), **29/29 PASS, 0 FAIL** (c).

> `/srv/tests` **seul** donne **12** tests, pas 112 : ce chemin est le dossier hôte `tests/` monté, qui
> ne contient que `test_08_openbuildings_temporal.py`. Les 112 viennent de `pipeline/tests` +
> `apps/api/tests` + `tests`, cuits dans l'image aux emplacements `/srv/pipeline/tests` et
> `/srv/api/tests`.

> Sous Git Bash (Windows), un chemin absolu passé à `docker compose exec` est réécrit en chemin
> Windows (`/srv/...` → `C:/Program Files/Git/srv/...`). Préfixer par `MSYS_NO_PATHCONV=1` — sinon
> l'erreur affichée est `file or directory not found: C:/Program Files/Git/srv/tests`, qui accuse à
> tort le conteneur.

## 5. Sondes d'usage

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/healthz   # 200
curl -s http://localhost:8000/sites                                      # JSON, liste des chantiers
docker stats --no-stream
```

> **Il n'y a pas de préfixe `/api`.** `GET /api/sites` renvoie `404 {"detail":"Not Found"}` ; le
> chemin réel est `/sites`. Idem pour toutes les routes : `/sites/{id}/progress`, `/sites/{id}/alerts`,
> `/sites/{id}/reports/{week}/pdf`, `/observations/{id}/image`.

Budget mémoire mesuré :

| Conteneur | Repos | Pic observé |
|---|---|---|
| `api` | 263 MiB | 354 MiB (pendant un backfill) |
| `db` | 89 MiB | 157 MiB |
| `worker` | — (sorti) | 84 MiB pendant la passe |

## 6. Arrêt propre

```bash
docker compose -f infra/docker-compose.yml --profile manual stop worker
docker compose -f infra/docker-compose.yml --profile manual down     # --profile OBLIGATOIRE
```

Les données PostGIS sont conservées dans le volume `infra_pgdata` (vérifié avant/après un `down`).
`down` **n'efface rien** ; seul `down -v` détruit le volume — à ne faire que sur confirmation
explicite.

---

## Pannes mesurées, cause racine et correctif

### Panne 1 — l'API boucle en redémarrage (`Restarting (1)`)

```
docker compose ps
infra-api-1   Restarting (1) 32 seconds ago
infra-db-1    Exited (255) 38 minutes ago

docker compose logs api | tail -3
sqlalchemy.exc.OperationalError: (psycopg2.OperationalError)
could not translate host name "db" to address: Name or service not known
```

**Cause** : `api` avait `restart: unless-stopped`, `db` **aucune** politique de redémarrage. Après un
redémarrage de Docker Desktop, seule l'API revenait — sans base, donc en boucle infinie. Le symptôme
ressemble à « l'API est cassée » ; c'est un **ordre de démarrage**.

**Correctif appliqué** : `restart: unless-stopped` sur `db` (voir `infra/docker-compose.yml`).
**Correctif immédiat** : `docker compose -f infra/docker-compose.yml down` puis `up -d db api`.

### Panne 2 — le worker refuse de démarrer (`network ... not found`)

```
docker compose -f infra/docker-compose.yml --profile manual up -d worker
Error response from daemon: failed to set up container networking:
network b4d4837133dbff21479a378d3767f8bb938511d6546b3db893eda457abe17cb3 not found
```

**Cause** : `docker compose down` **sans** `--profile manual` ne supprime pas les conteneurs des
profils désactivés. Le worker a survécu au `down`, gardant une référence vers le réseau supprimé ; au
`up` suivant, Compose a voulu **démarrer** ce conteneur au lieu de le recréer.

**Correctif immédiat** : `docker rm -f infra-worker-1` puis recréer (ou `run --rm worker`).
**Prévention** : passer `--profile manual` à `down`/`ps`/`logs`.

### Panne 3 — le harnais V&V introuvable dans le conteneur (code 127)

```
docker compose -f infra/docker-compose.yml exec -T api bash /srv/scripts/vv_live.sh
bash: /srv/scripts/vv_live.sh: No such file or directory        # code de sortie 127
```

**Deux causes indépendantes**, mesurées :
1. `scripts/` n'était **pas monté** dans le service `api` (seuls `tests/` et `housat-finedouala-1/`
   l'étaient) ;
2. l'image ne contenait **pas `curl`** (`command -v curl sha256sum python` → seuls les deux derniers),
   donc le harnais n'aurait pas pu tourner même monté.

**Correctif appliqué** : montage `../scripts:/srv/scripts:ro` + `curl` et `ca-certificates` dans
`apps/api/Dockerfile`.

### Panne 4 — `GET /api/sites` → 404

Voir § 5 : l'API n'expose pas de préfixe `/api`.

---

## Points de vigilance

- **L'emprise du parcours E2E vient de `.env`** (`VVSITE_*`), par conception : aucune localisation
  n'est codée dans le dépôt. Si `.env` est absent, le harnais retombe sur ses valeurs par défaut
  internes. Cas mesuré dans le conteneur : `/srv` ne contient pas de `.env`
  (`ls -a /srv` → `api apps housat-finedouala-1 pipeline scripts tests`), donc un run *dans le
  conteneur* et un run *depuis l'hôte* peuvent viser **deux emprises différentes**. Vérifier l'emprise
  effective avant d'interpréter les chiffres d'un run.

  Illustration mesurée le 2026-09-19, **même harnais, deux contextes** :

  | Contexte | Emprise | Observations | Semaine du PDF | `A7.2 NTFY_TOPIC` |
  |---|---|---|---|---|
  | depuis l'hôte (`.env` lu) | `VVSITE_*` du `.env` | **40** | 2026-09-07 | `true` |
  | dans le conteneur (pas de `.env`) | défauts internes du harnais | **5** | 2026-05-18 | `false` |

  Les deux runs sont **29/29 PASS** : aucune des deux n'est « la bonne » — elles ne mesurent pas la
  même emprise. Ne pas comparer leurs chiffres entre eux.
- **`LOCALHOST` dans le conteneur = le conteneur lui-même.** Le harnais vise
  `http://localhost:8000`, ce qui fonctionne car `uvicorn` écoute dans le même conteneur. Depuis
  l'hôte, c'est le port publié qui répond — même URL, cible différente.
- **Ne jamais présenter un `Exited (0)` du worker comme un échec** : c'est son mode nominal.
