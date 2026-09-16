# Changelog

Tous les changements notables de Housat sont documentes ici.
Format : [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) · Versionnage : [SemVer](https://semver.org/lang/fr/).
Horodatage ISO 8601 avec fuseau local (protocole harness-meta).

## [v0.1.0] - 2026-09-16
- **Socle dataset bâti (objectifs « contours » et « dalle/toit »)** : `pipeline/housat/built_dataset.py`
  rasterise les empreintes **OSM (ODbL)** sur la grille du LR Sentinel-2 (`all_touched=False`, règle
  conservatrice alignée sur `footprint_stats`) et fournit un tuilage à **couverture totale** (dernière
  fenêtre alignée sur le bord — le premier jet laissait 14 px dehors, attrapé par le test).
  **Preuve d'alignement vecteur/raster** : 49,8 % de surface bâtie OSM ↔ **50,4 %** de pixels bâtis
  dans le masque rasterisé, sur une scène réelle (2024-12-01, 8 % de nuages, îlot Housat, grille 19×19).
  Tests : `pipeline/tests/test_built_dataset.py` (4) — total **104 tests** verts.
- **OSM à Douala : correction d'une erreur de mesure** — un premier relevé annonçait **0 bâtiment** sur
  l'îlot de 178 m : c'était une **réponse vide d'Overpass saturé** (`200` + zéro élément) acceptée comme
  un fait. Mesure refaite avec réessais : **65 polygones** sur l'îlot (49,8 % bâti), **136 070** sur
  10 km, **286 542** sur la métropole. `fetch_buildings` **réessaie sur le miroir** quand la réponse est
  vide ; la règle est écrite dans `docs/limites-et-honnetete.md`, l'ADR 0011, la note de connaissance
  Overpass et la fiche projet.
- **Disponibilité des scènes sèches mesurée (nuage tuile, Douala 10 km)** : 23 scènes en 2017-2018
  (**6** sous 15 %), 25 en 2022-2023 (**3**), 17 en 2024-2025 (**1**), et **0 sous 30 %** pour la
  saison 2025-2026 → la saison la plus récente doit être **qualifiée par parcelle (SCL, ADR 0010)**
  avant tout choix de dates, la statistique tuile n'étant pas décisionnaire.
- **L'etape affiche sa PREUVE (passe 7, 13:2x)** — reponse a « sur quoi tu te bases pour dire terrain nu,
  structure ? » : l'IHM ne l'affirme plus sans le montrer.
  - La fiche nomme la **date qui a etabli l'etape** (« mesuree le 2026-04-27 ») au lieu de laisser
    croire que c'est la derniere image, et affiche **« Sur quoi repose cette etape »** : indices
    NDVI/NDBI/BSI compares a l'**image d'ancrage (date)**, avec les deux nombres retenus —
    « **8 % de l'emprise en changement robuste, indice de changement 0.1** ».
  - `GET /sites/{id}/progress` expose la preuve : `milestone_date`, `milestone_emprise`, `milestone_pv`,
    `anchor_date` (additif).
  - Chaque vignette de « Vignettes de mesure » porte ses chiffres : « 2026-04-27 — etape : Structure ·
    **8 %** du carre modifie · indice **0.1** » — toute affirmation est tracable a une mesure datee.
  - « Details techniques » declare la **fiabilite et sa cause** : « 0.55 — surresolution de repli
    (bicubic_fallback) : le modele SEN2SR de la voie detection n'est pas installe dans ce deploiement ».
  - Verifie dans l'IHM (capture) sur le chantier reel de 16 x 8 m : ancrage 2026-03-18, etape mesuree
    le 2026-04-27, 8 % / 0.1, fiabilite 0.55 avec sa raison.
- **Emprises de MAISON (10-20 m) : deux bugs racines corriges + etape monotone (passe 6, 13:0x)** :
  - **Le blocage des emprises < 20 m est supprime** (il contredisait la realite : un batiment individuel
    fait 10 a 20 m de cote). A la place, un avertissement **non bloquant** et chiffre : « 16 x 8 m = 2 x 1
    points Sentinel-2 : chaque point couvre votre batiment ET ses voisins (pixels mixtes), l'etape peut
    rester « terrain nu » ; la mesure devient discriminante vers 30 m de cote ».
  - **Bug 1 — `rio_mask(filled=True, nodata=0)`** : les pixels **hors** emprise etaient remplis a 0,
    classe `NO_DATA`, **comptee comme « obscurci »**. Sur une emprise de 16 x 8 m, la couche SCL (20 m)
    ne couvre aucun centre de pixel : **20 scenes refusees d'affilee a 100 % de nuages, zero observation**.
    Corrige par `filled=False` + valeurs valides seulement (`compressed`).
  - **Bug 2 — SCL a 20 m vs emprise de maison** : on juge desormais les nuages sur un **voisinage de
    60 m minimum** (`_scl_window`), la MESURE restant sur l'emprise exacte. Sans cela le test nuage
    etait un tirage au sort sur un unique pixel.
  - **Resultat mesure (Douala, chantier reel 16 x 8 m)** : **0 → 6 observations** (2026-03-18 au
    2026-05-25), **M0 → M2 « structure en progression », pivot confirme** — l'analyse automatique
    fonctionne enfin a l'echelle d'une maison. Comparaison : la meme parcelle en 178 m donnait 4
    observations ; meme date de bascule M2 (2026-04-27).
  - **Etape MONOTONE** : `/sites/{id}/progress` renvoyait le jalon de la **derniere** observation —
    une scene ulterieure sans changement re-affichait « terrain nu » alors que l'alerte « Etape
    franchie » avait deja ete envoyee. L'etape exposee est desormais le **plus haut jalon atteint**
    (meme regle que les alertes), avec sa date de bascule.
- **DESSINER l'emprise au glisser + bug MapLibre racine corrige (passe 5, 12:5x)** :
  - **Bug racine trouve** : le motif `if (map.loaded()) fn(); else map.once('load', fn)` etait faux —
    `loaded()` est **faux tant que des tuiles se chargent** (1-3 s ici) et l'evenement `load` ne se
    reproduit **jamais**. Toute couche ajoutee pendant un chargement (rectangle de selection, apercu
    du glisser, changement de date) etait donc **silencieusement perdue** : c'est ce qui rendait le
    dessin inoperant. Corrige par `onStyleReady()` (`isStyleLoaded()` sinon `once('idle')`, qui se
    reproduit) — verifie : le rectangle apparait desormais sur les **deux** cartes synchronisees.
  - **Interaction refaite** : « **Dessiner une emprise a analyser** » puis **clic maintenu + glisser**
    sur la carte (idiome SIG standard), apercu orange vivant pendant le geste, relache = emprise
    fixee sur les deux cartes ; le **deplacement de la carte est suspendu** pendant le dessin (le
    glisser dessine au lieu de deplacer). Le menu « Cote du carre » (signale inoperant, et sans
    objet) est **supprime** ; garde-fou « trop petit » sous 20 m de cote (4 points de mesure).
    Verifie de bout en bout : glisser 120 x 90 px → « Emprise dessinee : **57 x 43 m** (0.25 ha) » →
    chantier **10 « Ma maison (57 x 43 m) »** cree (le doublon exact repond 409, garde-fou existant).
- **Designer l'emprise sur la carte (passe 4, 12:2x)** — la fiche dit ce qui est mesure et laisse le choisir :
  - Reponse explicite a « sur quel batiment ? » : « La mesure porte sur **toute l'emprise** (178 x 178 m,
    3.17 ha) : l'etape ci-dessus est celle de l'**ensemble du carre**, pas d'un batiment designe » puis
    « Sentinel-2 mesure **1 point par 10 m**, ce carre fait **18 x 18 points**, une maison individuelle
    n'en occupe que 1 a 3 : pas de suivi batiment par batiment a cette resolution ». **Legende des
    contours** : bleu = la zone analysee, orange = l'emprise en cours de choix.
  - Nouvel outil « **Choisir une emprise a analyser** » : un **clic sur la carte** place un carre de
    20/30/40/60/100 m (contour orange en pointilles, curseur en reticule), les dimensions et le centre
    s'affichent, et « **Creer un chantier sur ce carre** » ouvre le chantier correspondant — via
    `POST /sites` existant, **aucune route nouvelle**. Verifie de bout en bout (Playwright) : clic →
    « Emprise choisie : 30 x 30 m, centre 4.04522 N / 9.70484 E » → creation → « Ma maison (30 m) » (site 9).
  - `SiteMap` gagne un mode de selection (etat courant lu par refs, curseur croix, couche `pick`) ;
    les deux cartes synchronisees affichent le carre candidat.
- **Comparateur de mesure SUPPRIME + caracterisation formelle de l'emprise (passe 3, 11:4x)** :
  - Le bloc « **Comparer deux passages** » (carte MapLibre, 2 curseurs d'opacité, sélecteurs de
    dates) est **retiré** : il dupliquait la vue haute résolution datée, ses curseurs ne produisaient
    aucun changement visible, et son image de mesure est illisible par construction. Partent avec lui
    `apps/web/src/MapView.tsx` (orphelin), le CSS `.mapbox` et l'interface `CompareResult` — la fiche
    passe de **2 595 a 1 759 px** (−32 %). L'endpoint `/sites/{id}/compare` reste dans l'API (surface
    publique testée).
  - Les **vignettes de mesure** passent derrière un repli explicite : « Sentinel-2, 10 m : a cette
    resolution un batiment fait 1 a 3 pixels, ces images ne sont pas interpretables a l'oeil ».
  - **Caracterisation FORMELLE de l'emprise** (fin du « votre maison » générique) : « Emprise
    analysee : **178 x 178 m** (3.17 ha) · mesure Sentinel-2 a 1 point par 10 m, soit **18 x 18
    points** » et, au-dela de **45 m de cote**, « Ce carre couvre **plusieurs batiments** (un ilot,
    pas une maison) : le suivi porte sur l'ensemble du carre… emprise d'environ **30 m de cote** » ;
    le titre devient « Ou en est **ce chantier** ? ». Le formulaire passe du carre de 178 m (un ilot)
    a une **parcelle de 22 m** (~0,0002°) et explique la taille attendue.
  - **Superposition OSM reparee puis retiree de l'IHM** : la case « Emprises de batiments (OSM) »
    n'affichait rien — Overpass etait appele en GET sans repli et **tout echec devenait une collection
    vide** (donc silencieusement vide). `fetch_buildings` essaie deux endpoints (mesure : `api.de` 200
    en 1,4 s **puis** 504 en 8,5 s, POST comme GET) et **remonte l'echec** ; `/parcel/buildings`
    expose `stats` (nombre, part batie **coupee a l'emprise** via shapely, emprise moyenne) et
    `unavailable`. Mesure live : parcelle de 22 m = **1 batiment, 61 % bati** ; ilot de 178 m =
    **65 polygones** (mesure CORRIGEE le 2026-09-16 apres reessai : la reponse vide d'Overpass
    sature avait ete prise pour un fait) — OSM couvre bien Douala : 136 070 polygones sur 10 km,
    286 542 sur la metropole ; le verdict IHM ne s'appuie toujours **pas** sur OSM, mais la
    supervision bati, elle, est possible.
    fonder le verdict de l'IHM sur OSM.
- **Revue IHM par captures réelles (passe 2, 2026-09-16 11:2x)** : parcours complet capturé à
  1280×800 sur deux chantiers (avec et sans données), défauts corrigés :
  - **Lightbox cassée** — le clic sur une vignette « pour l'agrandir » n'agrandissait rien (image
    native de 76 px centrée dans un écran noir) : boîte fixe `82vw × 82vh` + `object-fit: contain`
    + `pixelated` → la mesure est réellement agrandie, sans faux détail interpolé, avec une **légende
    datée** sous l'image (`2026-05-20 — etape : Structure · mesure Sentinel-2 (10 m)`).
  - **Accueil en langage client** : « a jour » / « jamais analyse » / « 4 observations » au lieu de
    `done` / `idle` / « 4 obs » ; accroche orientée propriétaire (« Suivez la construction de votre
    maison **a distance**… ») au lieu de la liste de fonctionnalités.
  - **Ordre de la fiche** : « Ou en est votre maison ? » passe **avant** la carte (la réponse d'abord,
    les preuves ensuite) ; le bouton principal devient **« Chercher les images des derniers mois »**
    (fin du jargon « backfill archive », repris dans les messages d'aide qui le citaient).
  - **Mur de 33 puces** des passages Sentinel-2 réduit aux **12 mesurés** (ceux que le résumé compte) ;
    les 21 plus anciens passent derrière « Voir les 21 passages plus anciens ».
  - **Comparateur** : curseurs d'opacité **au-dessus** de la carte et à **0 par défaut** — l'ancien
    défaut (0,9) affichait d'emblée un rectangle de mesure flou au milieu de la carte.
  - **Alertes** : date ISO (`2026-09-16`) au lieu de « 16 h 04 min 52 s ».
  - **Carte vide ≠ carte cassée** : l'imagerie d'archive met 1-3 s par tuile (proxy → Esri, sans cache
    serveur) ; un « Chargement de l'imagerie d'archive… » s'affiche jusqu'au premier `idle` de la carte.
  - **Diagnostic consigné** : les cartes vides observées en cours de session coïncidaient avec un
    **backfill lancé par l'utilisateur** — le travail lourd tourne dans le processus de l'API
    (`BackgroundTasks`) et affame le proxy de tuiles. Chronologie mesurée : `/sites` 155 ms,
    `/overpasses?parcel=true` 4,2 s, tuiles 0,5-2,1 s chacune, rendu complet ≈ 3 s **hors** backfill.
- **Suivi de chantier LISIBLE par un non-initié** (revue « essence produit », 2026-09-16 11:04) : le
  bloc `Jalon — / Progression 0 % / PV cumulee 0.00 / Observations 0` qui ouvrait la fiche est
  remplacé par le **rail des 5 étapes** (Terrain nu → Fondations → Structure → Toiture → Finition),
  la phrase « **Etape N sur 5 — libellé** · derniere observation : date » et, si le chantier n'a
  aucune donnée, un **message d'action** (« Lancer le backfill archive ») au lieu de tirets. Le
  jargon (indice de changement, pivot, observations) passe dans « Details techniques », replié.
- **Avant/après** : le **slider de deux vignettes Sentinel-2 (10 m)** — illisible à l'échelle du bâti,
  cause récurrente de « on ne distingue pas une maison » — est **supprimé** ; le panneau conserve la
  **carte datée** (lecture), les curseurs d'opacité des images de mesure, et gagne la phrase en clair
  « Entre le … et le …, votre chantier est passe de **Terrain nu** a **Structure** ». Les vignettes de
  mesure deviennent « **Historique des mesures** » avec la distinction explicite mesure 10 m / lecture
  haute résolution (+ section masquée quand il n'y a rien à montrer).
- **Rapport PDF côté client** : KPI renommés (« **Ou en est votre maison ?** » = Etape N sur 5,
  avancement, observations, fiabilité), colonnes « Etape du chantier / Confirmee / Fiabilite /
  Changement / Terrain modifie », semaine à **observation unique** rendue « Observation de la semaine »
  (fin du faux Avant/Après à date identique), **largeurs de colonnes mesurées** (aucun en-tête replié)
  et typographie traduite (`•`, `—`, `…` → ASCII) au lieu de « ? » dans le livrable client.
- **Rapport générable malgré des données anciennes** : le bouton visait toujours la **semaine ISO
  écoulée** → 422 « aucune observation sur cette semaine » dès que le chantier n'a rien observé cette
  semaine-là (démo dont les données datent de mai) ; il cible désormais la **semaine de la dernière
  observation**, avec libellé et explication (« Aucune observation la semaine derniere : le rapport
  porte sur la semaine de votre derniere observation (…) »).
- **« 0 exploitable » expliqué** : quand les 12 passages mesurés sont nuageux **sur la parcelle**, le
  panneau le dit en clair et renvoie vers la vue haute résolution — au lieu d'un zéro sec qui laisse
  croire que le produit ne fonctionne pas.
- **Corrections** : `apps/web/src/MapView.tsx` **ne compilait plus** en `tsc --noEmit` (type des 4
  coins de l'overlay image ; `npm run build` = Vite seul, sans typecheck, d'où la dérive) ; alerte
  « Etape franchie : … » au lieu de « Jalon atteint : … (M2) » ; accord singulier/pluriel des rapports
  (« 1 observation ») ; **CSS mort** du comparateur supprimé.
- **Masque nuage PAR PARCELLE (ADR 0010)** : `imagery/clouds.py` lit la couche **SCL** (20 m,
  catégorielle) et compte la fraction obscurcie **sur la parcelle** — `eo:cloud_cover` porte sur
  toute la tuile (~110 km) et **écartait des scènes dont la parcelle est dégagée**. Seuils découplés :
  `tile_cloud_prefilter` (90 %, coupe amont large) vs `max_cloud_cover` (20 %, seuil **parcelle**).
  Le worker lit **le SCL seul d'abord** (1 fichier) et ne télécharge les 5 bandes que si la parcelle
  est dégagée ; `check_site` examine jusqu'à 6 scènes et retient la plus récente dégagée.
  Rééchantillonnage **plus proche voisin** (une couche catégorielle ne s'interpole jamais), repli
  **non bloquant** si le SCL manque. `GET /sites/{id}/overpasses?parcel=true` expose le nuage parcelle.
  **Mesuré (Douala, 120 j)** : **0 → 2** dates exploitables sur 33 — dont **2026-06-19** (tuile
  **91,2 %** mais parcelle **19,0 %**), que le filtre tuile rejetait.
- **Cadence d'imagerie RÉELLE exposée** : `GET /sites/{id}/overpasses?days=N` + panneau
  « Passages Sentinel-2 » (date · nuages % · analysé / exploitable / nuageux, **écart médian**).
  Mesure sur la parcelle de Douala (120 j) : **33 passages, écart médian 3 j** — mais **0
  exploitable** (nuages 30–100 %). La contrainte n'est donc **pas la cadence**, ce sont les nuages.
- **Rapport PDF lisible (vue haute résolution)** : `render_weekly_pdf(..., hr_png, hr_label)` — le
  module reste **pur** (aucun IO réseau) ; c'est **l'API** qui fournit l'image d'archive de la parcelle
  (≤ fin de semaine). Le PDF hebdo embarque donc la **vue HR lisible** en plus des images Sentinel-2
  (mesure). `sr_method` est désormais **exposé par l'API** (traçabilité de la surrésolution).
- **Parcelle de démonstration conforme à la vision** : ~**178 m** (maison individuelle) au lieu d'un
  quartier de 1,1 km ; libellés « **mesure** » (Sentinel-2 10 m) vs « **lecture** » (imagerie d'archive),
  les dates d'archive étant explicitement **indépendantes** des dates d'observation.
- **Surrésolution à deux voies (ADR 0002)** : voie DÉTECTION (`upscale_bands`) — SEN2SR (ESA
  OpenSR) réellement activable via import paresseux, repli bicubique honnête ; voie AFFICHAGE
  (`upscale_rgb_display`) — modèle perceptuel optionnel Real-ESRGAN ONNX (tuiles, fp16, GPU local
  RTX 4070 Ti SUPER 16 Go). Sélection par `SR_ENGINE` / `DISPLAY_SR_ENGINE` ; poids non committés
  (fournis séparément). `pipeline/requirements-sr.txt` documente les dépendances optionnelles,
  hors image slim.
- `imagery/rendering.py` : étirement robuste par percentiles 2-98 % + gamma 0,9 + léger rehaussement
  pour le PNG avant/après ; neutralise NaN/inf et les scènes quasi-uniformes (aucune division par ~0).
- Tests V&V : `tests/test_rendering.py` (gamme dynamique, gamma, robustesse NaN/uniforme) et
  `tests/test_sr_engines.py` (sélection de moteur, dégradation SEN2SR, tiling ONNX via session factice).
- **Fond visuel haute résolution (ADR 0003)** : `imagery/basemap.py` — cascade de fournisseurs rendant
  lisible **toute** emprise lat/long. Le Sentinel-2 à 10 m est illisible à l'échelle d'une parcelle et
  **aucune surrésolution ne compense un facteur 15-30×** : le problème est la source, pas le modèle.
  Chaque fournisseur porte `attribution`, `licence` et `redistributable` (garde-fou avant embarquement
  en rapport). CLI : `python -m housat.imagery.basemap --bbox minLon,minLat,maxLon,maxLat --out f.jpg`.
  Tests `tests/test_basemap.py` (fetcher injecté, sans réseau). Preuve live : emprises Douala,
  Port-au-Prince et périurbain camerounais rendues lisibles.
- **Fournisseur NICFI (`planet_nicfi`)** : mosaïques PlanetScope 4,77 m **datées** (mensuelles),
  redistribuables sous attribution — source retenue pour les rapports livrés. Assemblage de tuiles XYZ
  côté **serveur** (`PLANET_API_KEY` **jamais** exposée au navigateur, exigence du tile service Planet)
  + géométrie Web Mercator (`choose_zoom` / `tile_range` / `stitch_xyz`). Config `PLANET_API_KEY` /
  `NICFI_MOSAIC`. Chemin réseau couvert par tests à fetcher injecté (validation live à faire avec la clé).
- **Benchmark SR reproductible** (`pipeline/housat/benchmark.py`, `benchmarks/`) : protocole
  simulated-LR 4×, méthodes `nearest` / `bicubic` / `swin2sr` / `onnx_sr`, métriques PSNR/SSIM vs
  proxy Esri, sur **CPU et GPU**. Résultats (Douala + Port-au-Prince) dans `benchmarks/README.md` :
  **Swin2SR est le seul à battre le bicubique (SSIM +0,09 à +0,10, PSNR équivalent) ; le GPU ×7 en
  débit sans changer la qualité ; les modèles perceptuels génériques (SwinIR, Nomos/Real-ESRGAN)
  passent SOUS le bicubique** — d'où l'interdiction de les brancher sur la voie détection.
- **Fine-tuning SR satellite (ADR 0005)** : `housat/benchmark_finetune.py` (EDSR-lite ×4) entraîné
  ~8 min sur GPU (100 paires, villes `abidjan/accra/yaounde/kinshasa`) et évalué sur sites **held-out**
  (Douala, Port-au-Prince). Résultat : **seul modèle à battre le bicubique sur PSNR ET SSIM**
  (+0,3 à +0,4 dB ; +0,05 SSIM) et **bat Swin2SR sur PSNR** ; ~3,5× plus rapide que Swin2SR au GPU.
  Limite tracée : train et test partagent l'opérateur de dégradation (chiffres optimistes, non valables
  tels quels sur vraie Sentinel-2).
- **Paires réelles multi-capteurs (ADR 0006)** : `housat/benchmark_realpairs.py` — jeu `isp-uv-es/opensr-test`
  (LR = Sentinel-2 L2A **réelle**, HR = **NAIP domaine public** / SPOT CC BY-NC), **split spatial**,
  sans opérateur de dégradation partagé. Résultat : **in-domain le fine-tuné bat bicubique ET Swin2SR
  sur PSNR et SSIM (paires réelles, sans le biais optimiste)** ; **cross-capteur (NAIP→SPOT) il PERD
  face au bicubique alors que Swin2SR (générique) généralise le mieux** → **modèle de domaine à
  ré-entraîner par capteur/région**. Licence : NAIP commercialisable, SPOT non.
- **SR servie en ONNX et intégrée au pipeline web (ADR 0007)** : `housat/export_onnx.py` (export
  reproductible, **parité torch/onnx exacte** : diff 0,0) ; modèle de référence
  `housat/models/housat_sr_x4.onnx` (EDSR-lite ×4, **entraîné sur NAIP domaine public =
  commercialisable**). La SR d'affichage est appliquée au **worker sur les bandes brutes 10 m** (×4),
  donc le `image_png` servi par l'API est SR-amélioré **sans aucun changement côté front/PDF**.
  `onnxruntime` (CPU, ~15 Mo, **sans torch**) devient une dépendance de service. Activation opt-in
  (`SR_MODEL_PATH`), moteur d'affichage `onnx`, repli bicubique historique par défaut.
- **Objectif perceptuel LPIPS/adversarial (ADR 0008)** : `train_real(loss="perceptual"|"perceptual_gan")`
  = L1 + LPIPS (+ PatchGAN optionnel), entraîné sur paires **réelles NAIP**. Évaluation à **trois
  métriques** : **le perceptuel DOMINE le LPIPS (0,088 vs 0,230 ; ~2,6×) mais BAISSE PSNR/SSIM** →
  l'hypothèse « LPIPS pousse le SSIM » est **falsifiée** ; c'est un **arbitrage fidélité↔perception**
  mesuré, pas supposé. Deux modèles ONNX livrés : `housat/models/housat_sr_x4.onnx` (perceptuel,
  défaut affichage) et `housat_sr_l1_x4.onnx` (fidélité). Nouvel endpoint **`GET /sr/preview?bbox=…`**
  (PNG **LR | SR | HR**) testable au navigateur pour toute emprise. `.dockerignore` ajoutés (contexte
  de build allégé : sans eux, torch dans `.venv` serait embarqué).
- **Imagerie haute résolution DATÉE (ADR 0009)** : `imagery/wayback.py` (Esri World Imagery Wayback) —
  imagerie **sub-métrique datée** où l'on **VOIT les bâtiments**, là où Sentinel-2 (10 m) est
  illisible. Douala : **121 dates (2018→2026, ~mensuel)**. Endpoints `GET /parcel/wayback/dates`
  (sonde la **couverture réelle**, 404/placeholder filtrés) et `GET /parcel/wayback/image` ; panneau
  front **« Vue réelle haute résolution »** avec **sélecteurs Avant/Après** → **vrai avant/après
  lisible**. Sentinel-2 reste la **mesure** ; Wayback est la **lecture**. Tests `tests/test_wayback.py`.
  **Zoom** : contrôle d'emprise (réduit autour du centre) + taille 1024 → profondeur native **z19
  (~0,3 m/px, vérifiée plus nette que z17)** ; le limitant était le **rendu** (`GSD = étendue/taille`),
  pas la donnée. **Rendu NATIF** (`size` omis ⇒ 1 px image = 1 px source ; `size` fourni **borné au
  natif**) — fin de l'upsampling qui floutait, repli auto de zoom si couverture absente. **Emprises de
  bâtiments OSM** (`?buildings=1`, Overpass, **ODbL redistribuable**) pour identifier le bâti.
  **Plafond de zoom corrigé** : `choose_zoom` était plafonné à z17 (~1,2 m/px, cause racine du flou) →
  Wayback rendu à **z19 = 0,30 m/px** (133 m ⇒ 449 px). **Zoom jusqu'à ~20 m** + **clic pour recentrer**
  sur un bâtiment précis + « Réinitialiser » + affichage de l'emprise (m) et de la borne native.
  **Navigation MapLibre** : panneau = **deux cartes Avant/Après synchronisées** (pan/molette/clavier,
  clic = centrer, *Focus bâti*), **proxy de tuiles same-origin** `/parcel/wayback/tile` (tuiles à la
  demande → **rendu plus rapide**, cache immutable) + emprises OSM en **GeoJSON** (`/parcel/buildings`).

### Changed
- **Rendu des images avant/après** : `observations.image_png_rgb` étire désormais le composite
  (percentiles + gamma + rehaussement) au lieu du clip dur `rgb / 0.35`, qui produisait des vignettes
  sombres et plates. `stretch=False` restaure l'ancien comportement (comparaison A/B).
- **Fond de carte web** : `MapView.tsx` passe du fond OSM au fond satellite **haute résolution**
  (Esri World Imagery, sans clé, attribution conservée) — toute emprise devient lisible sur la carte ;
  le Sentinel-2 reste en overlay. Licence de redistribution à valider avant usage en rapport (ADR 0003).

### Fixed
- **« Les dates s'arrêtent début août » (diagnostic)** : ce n'est **pas un bug** — la release Wayback
  la plus récente est bien **2026-08-05** (196 releases vérifiées à la source). L'archive Esri n'est
  **pas quotidienne** (~mensuelle). Le défaut était le **silence** de l'UI : le panneau affiche
  désormais la **date la plus récente pour l'emprise** et précise que la cadence est mensuelle, en
  renvoyant vers « Passages Sentinel-2 » pour les dates récentes.
- **`lastWeekMonday()` calculé en UTC** : un dimanche soir (UTC déjà lundi), le bouton rapport
  désignait la semaine **en cours**, que l'API refuse (422 « semaine invalide »). Le calcul suit
  maintenant le **calendrier LOCAL**, comme la validation côté API.
- **Panneau « Passages Sentinel-2 » incohérent avec l'ADR 0010** : il jugeait « exploitable » sur les
  nuages **tuile** et annonçait donc « **0 exploitable** » alors que des dates passent sur la parcelle.
  Le panneau interroge désormais `?parcel=true`, marque les pastilles sur le nuage **parcelle**
  (suffixe `parc.`), affiche **« N exploitable(s) sur M mesurées »** et porte le détail en infobulle.
- **Bouton rapport actif sans données** : « Générer le rapport » était cliquable sur un chantier à
  0 observation → erreur rouge opaque. Il est **désactivé** avec le guidage « lancez d'abord le
  backfill », et le message 422 de l'API est devenu actionnable.
- **`Content-Type` du proxy de tuiles** : déclarait `image/png` en servant du **JPEG** (Esri) — le
  navigateur devait *sniffer*. Le type amont est désormais relayé tel quel.
- **`/overpasses` retournait un 500** : `SceneMeta.acquired` est un `date` (et non un `datetime`)
  selon l'item STAC → `.date()` levait `AttributeError`. Garde-fou `_iso_day()` (accepte les deux).
- **Rendus (contrôle visuel sur capture réelle de la page)** : la vignette d'observation était
  **étirée à 100 %** de sa colonne alors que le PNG Sentinel-2 d'une parcelle fait ~72 px → flou
  massif et **trompeur sur le détail réellement disponible**. Elle est affichée à sa **taille
  naturelle** (et **pixelisée** dans la visionneuse). Le **cadrage des cartes** — MapLibre mesurait le
  conteneur avant sa taille définitive — est désormais appliqué après `resize()` + `ResizeObserver`,
  et **une seule carte cadre pour les deux** → les deux vues sont rigoureusement identiques.
- **Sites homonymes indiscernables** : deux chantiers « Ma maison » étaient impossibles à distinguer ;
  la liste affiche maintenant **emprise (m) · statut · date de création**.
- **Confusion mesure / affichage (exactitude)** : la légende indiquait la méthode de la voie
  **détection** (`bicubic_fallback`) alors que l'image est produite par la voie **affichage**. Le
  worker enregistre `display_sr` et l'API l'expose → légende exacte (+ infobulle avec bbox).
- **Dates d'archive non fiables (SIG)** : `available_dates` sondait à **z16** → il listait des dates
  dont la couverture **profonde** est absente (carte à trous dès qu'on zoome). Sonde portée à **z18**
  + **cache par emprise** (la sonde coûte ~196 requêtes : plus refaite à chaque affichage).
- **Fuseau du rapport (incohérence)** : `_report_meta` court-circuitait le sérialiseur du modèle →
  `created_at` **naïf** dans la réponse POST ; il passe désormais par `_iso_utc` (UTC explicite).
- **Alerte parasite M0 (logique)** : le worker émettait une alerte « Jalon atteint : terrain nu (M0) »
  dès la première observation — or M0 est la **baseline** (terrain nu), pas un progrès. Alertes
  désormais réservées à **M1+** (`milestone > 0`).
- **Fuseau des alertes (affichage)** : `sent_at` était stocké en UTC naïf et rendu tel quel → heure
  décalée (ex. « 01 h 45 » pour 21 h 45 local). L'API renvoie désormais un ISO 8601 **avec fuseau**
  (UTC `Z`) → le navigateur affiche l'**heure locale** correcte.
- **Rendu des observations (UX)** : vignettes agrandies (grille responsive `minmax(340px, 1fr)` +
  images à leur **taille naturelle** au lieu d'un carré recadré), **lightbox** au clic (plein écran,
  fermeture Échap), conteneur élargi (880 → 1160 px).
- **Statuts illisibles (UX)** : « Vérification terminée : cloud_pending » → message en langage
  utilisateur (`STATUS_FR`). Copie « carte OSM » corrigée en « carte satellite haute résolution ».
- **Écart documentation/réalité (V&V)** : le pipeline **n'exécutait aucune surrésolution neuronale**
  (`sen2sr` absent de `requirements.txt`, du venv et de l'image Docker) — le README annonçait pourtant
  « 2,5 m par inférence neuronale ». SEN2SR est désormais réellement chargeable, et un échec
  d'inférence dégrade en bicubique tracé au lieu de rompre le worker.
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

### Removed
- **Code mort (passe `ponytail`)** : `clouds.is_parcel_clear` (0 usage hors tests — le worker fait
  son propre test de seuil) ; `buildings.draw_buildings` **et** le paramètre `?buildings=1` de
  `/parcel/wayback/image` — le front superpose les emprises en **GeoJSON** via le moteur de carte,
  la rasterisation serveur faisait double emploi ; paramètre `available_dates(refresh=…)` (test-only :
  le cache est déjà purgé par la fixture) ; 3 constantes SCL fusionnées en une (`SCL_OBSCURED`).
  **−70 lignes** sur les fichiers ajoutés la veille, **aucune fonctionnalité perdue**.

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
