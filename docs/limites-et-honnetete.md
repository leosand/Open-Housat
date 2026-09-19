# Limites et honnêteté des mesures

> Statut : document de référence, 2026-09-16. Il décrit **ce que Housat peut affirmer**, **sur quelle
> base**, et **ce qu'il ne peut pas dire**. Toute affirmation de l'interface doit pouvoir être reliée
> à un chiffre de ce document. Si une phrase de l'IHM contredit ce fichier, c'est l'IHM qui a tort.

## 1. Ce qui est mesuré, exactement

| Objet | Réalité technique |
|---|---|
| **Ce qui est mesuré** | L'**emprise** déclarée (un rectangle lon/lat), **en entier**. Jamais un bâtiment désigné nommément. |
| **Source de mesure** | Sentinel-2 L2A, **10 m par point** (bandes), **20 m** pour la couche de nuages SCL. |
| **Indices** | NDVI (végétation), NDBI (bâti), BSI (sol nu), comparés à l'**image d'ancrage** $t_0$ **et** à l'observation précédente. |
| **Étape (M0-M4)** | Sortie d'un **classifieur à seuils** (`pipeline/housat/detection/milestones.py::classify`), alimenté par `detection/change.py::change_score` et `built_ratio`. **Pas** une lecture d'image ni un modèle de vision. |
| **Rapport** | Le PDF reprend les **mêmes** chiffres persistés : aucune donnée recalculée à la génération. |

Règle de lecture des jalons (`classify`). `built_ratio` = part de la parcelle **sans végétation**
(NDBI > 0) ; ΔNDBI / ΔBSI = tendance mesurée contre l'observation **précédente** :

| Condition mesurée | Jalon affiché | Confiance |
|---|---|---|
| aucun changement (score < 0,02 et ΔNDBI, ΔBSI ≤ 0,01) **ou** `built_ratio` < 0,02 | **M0** terrain nu | 0,90 |
| ΔBSI > 0,02 (sol nu qui apparaît) **et** `built_ratio` < 0,15 | **M1** fondation | 0,75 |
| ΔNDBI > 0,015 (bâti en hausse) **et** `built_ratio` ≥ 0,15 | **M2** structure | 0,80 |
| `built_ratio` ≥ 0,40 **et** \|ΔNDBI\| ≤ 0,015 **et** score < 0,08 (plateau) | **M3** toiture | 0,65 |
| score < 0,03 **et** ΔBSI < 0 (le végétal revient) | **M4** finition | 0,60 |
| état ambigu | **M1** (conservateur) | 0,40 |

Deux propriétés sont **portées par le code et vérifiées par les tests** :

- **les cinq jalons sont atteignables** — avant le 2026-09-19, « finition » était du **code mort**
  (0 fois sur 6000 tirages) et une parcelle stable s'affichait « fondation détectée » ;
- **le jalon ne régresse jamais** (`milestones.hold_milestone`) : un chantier ne se dé-construit pas.
  Mesure du 2026-06-09 sur un chantier réel (40 observations) : le rail était passé M2 → M1 → M2 sur
  trois dates dont l'emprise valait 0,2033 / 0,1794 / 0,1981 — identiques à la précision de la mesure.

Ce que ces jalons **ne mesurent pas** : rien ici ne distingue une dalle d'une toiture par la
**géométrie** ou la **hauteur**. La distinction repose sur des seuils spectraux et sur la stabilité
(« plateau »). Le modèle U-Net siamois reste la dette documentée de `milestones.py` (phase 2) — et
la voie **hauteur** existe (`08_openbuildings_temporal.py`), mais elle n'est pas branchée à l'IHM.

## 2. Limites physiques (non négociables)

1. **Résolution — la limite structurante.** Un point de mesure = 10 m. Une maison individuelle occupe
   **1 à 3 points**, un carré de 178 m en occupe 18 × 18. Conséquence : **aucune surrésolution ne
   compense un facteur 15-30×** (ADR 0002, ADR 0003). Le bâti **se lit** sur l'imagerie d'archive
   haute résolution (0,3-0,5 m) ; il **se mesure** sur Sentinel-2. Ces deux voies ne doivent jamais
   être confondues.
2. **Pixels mixtes.** Sur une emprise de maison, chaque point de 10 m contient la parcelle **et ses
   voisines**. Le signal est donc dilué : l'étape peut rester « terrain nu » alors que les travaux
   avancent. La mesure devient discriminante à partir d'environ **30 m de côté**.
3. **Nuages = saison.** En saison des pluies (Douala : mai-septembre), **même le masque par
   parcelle** peut ne rien laisser passer : mesuré 0 passage exploitable sur 33. Ce n'est pas un
   défaut logiciel, c'est la météorologie (d'où l'intérêt du **SAR** en complément, non implémenté).
4. **Cadence réelle de l'imagerie d'archive.** Esri Wayback n'est **pas** quotidien (~mensuel ;
   dernière release vérifiée le **2026-08-05**). La **cadence 5-7 j** demandée est celle de
   Sentinel-2 (écart médian mesuré : **3 j**), pas celle de l'imagerie lisible.
5. **Bâti individuel non isolable.** Suivre *un* bâtiment automatiquement (détection + suivi) n'est
   pas possible à 10 m. Ce qui est fait : mesurer **exactement le rectangle que l'utilisateur
   dessine**, et le dire.

## 3. Limites de qualité de la mesure

1. **Confiance.** `confidence = 0.9` (baseline d'ancrage), `0.8` si la surrésolution satellite
   (SEN2SR) est active, **`0.55` en repli bicubique** — puis ×0,7 si le moteur SR n'est pas la voie
   satellite (`detection/milestones.py`). Dans le déploiement actuel, **SEN2SR n'est pas installé** :
   toutes les mesures sont en repli, la fiabilité affichée est **0,55** et l'IHM l'écrit.
2. **Nuage par parcelle, et son voisinage.** Sous **60 m de côté**, une emprise ne couvre aucun
   centre de pixel SCL (20 m) : le test nuage est alors fait sur un **voisinage de 60 m** centré sur
   l'emprise (ADR 0012). La mesure, elle, reste sur l'emprise exacte. C'est dit dans le code et dans
   le CHANGELOG ; ce n'est pas dit dans l'IHM (limite assumée, à corriger si le produit grandit).
3. **Étape indicative aux petites échelles.** À 2 × 1 points, « 8 % de changement robuste » sur
   l'emprise n'est pas une preuve. L'IHM affiche donc **la date qui a établi l'étape, l'ancrage, les
   deux chiffres et la fiabilité** : à l'utilisateur de juger (ADR 0013).
4. **Comparaison à l'ancrage $t_0$ uniquement** : hystérésis précise, réactivité lente. Une pointe
   isolée ne déplace pas l'étape.
5. **Seuils = décision produit.** Les seuils (20 % de nuages, 0,01-0,02 de croissance, 25 % d'emprise)
   sont des choix, pas des lois physiques. Ils sont dans le code, testés, et modifiables.

## 4. Limites d'infrastructure et de données

1. **Un seul processus API.** Le travail lourd (backfill, surrésolution) tourne dans le processus de
   l'API (`BackgroundTasks`) : pendant une recherche d'images, le **proxy de tuiles est affamé** et
   les cartes se remplissent lentement (mesuré : 0,5-2,1 s par tuile, rendu complet ≈ 3 s **hors**
   backfill). Correctif structurel identifié : déporter le travail dans le service `worker` (déjà
   défini dans `infra/docker-compose.yml`), ou servir N workers uvicorn.
2. **Pas de cache serveur des tuiles** : chaque tuile non mise en cache navigateur est un aller-retour
   vers Esri.
3. **Overpass (OSM) est intermittent** : mesuré 200 en 1,4 s, puis 504 en 8,5 s, POST comme GET. Le
   code essaie deux endpoints et **remonte l'échec** (`unavailable`) au lieu d'un faux « 0 bâtiment ».
4. **OSM : mesurer, jamais conclure sur une réponse vide.** Un carré de 178 m de Douala a d'abord
   été annoncé à **0 bâtiment** — c'était une **réponse vide d'Overpass saturé**, pas un fait.
   Mesure corrigée (2026-09-16, réessais) : **65 polygones** sur ce carré (49,8 % de surface bâtie),
   **136 070** sur 10 km, **286 542** sur la métropole. Règle : `fetch_buildings` **réessaie sur le
   miroir** quand la réponse est vide, car un service saturé renvoie `200` avec zéro élément —
   indiscernable d'une zone sans bâti.
5. **Licences** : les tuiles Esri ne sont **pas** redistribuables — elles servent l'affichage et la
   lecture en ligne ; les rapports livrés utilisent ReportLab + les images Sentinel-2 (Copernicus) et
   OSM (ODbL) selon attribution. Toute embarquement d'imagerie Esri dans un livrable client est **à
   valider juridiquement** (dette ouverte).
6. **Aucun fournisseur authentifié ne doit être réintroduit sans habilitation écrite.** Mesuré le
   2026-09-19 : la seconde voie de fond (mosaïques mensuelles redistribuables) exigeait une clé, le
   programme qui la finançait est **clos depuis 2025**, l'API renvoyait **0 mosaïque** et la clé a été
   **exposée puis révoquée**. Tout le chemin a donc été **supprimé du code** (ADR 0003, amendement
   2026-09-19). Conséquence à assumer : **il n'existe plus aucune source haute résolution
   redistribuable** dans le projet — donc **aucun fond HR ne part dans un rapport livré**.
7. **Un repli ne porte jamais le nom de la source distante.** Leçon du script 08 (Open Buildings) :
   l'URL supposée renvoyait **404** et le repli local OSM était quand même étiqueté « Google Open
   Buildings 2.5D Temporal V1 ». Règle : `provenance` (`remote_download` / `local_fallback`),
   `download.http_status` réel et `agreement_status` mesuré sont écrits dans le JSON ; un repli écrit
   `NON_VERIFIABLE`, jamais `CONFORME`.

## 5. Ce que le produit ne prétend PAS faire

- Il ne **voit** pas une maison : il **mesure une emprise**.
- Il ne remplace pas une **visite de chantier** ni un **constat d'huissier** : il fournit un indice
  daté, reproductible et scellé (SHA-256), à confronter au terrain.
- Il ne fonctionne pas **par tous les temps** : en saison des pluies, la mesure s'arrête — la lecture
  d'archive reste disponible.
- Il ne suit pas **un logement dans un immeuble** ni une parcelle non délimitée « à la main » :
  c'est le rectangle déclaré qui est mesuré.
