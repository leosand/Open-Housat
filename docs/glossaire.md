# Glossaire — jargon interne ↔ langage client

> Statut : 2026-09-16. Règle de l'IHM : **le client lit son vocabulaire, l'ingénieur garde le sien
> dans « Détails techniques »**. Toute étiquette visible par un propriétaire doit figurer dans la
> colonne de droite.

## Termes du produit

| Jargon interne (code, API) | Ce qu'un propriétaire doit lire | Où |
|---|---|---|
| *jalon* `M0..M4` | « **Étape** 3 sur 5 » | rail d'état |
| `M0 terrain nu` / `M1 fondation detectee` / `M2 structure en progression` / `M3 toiture probable` / `M4 finition` | Terrain nu · Fondations · Structure · Toiture · Finition | rail d'état |
| `pv_sum` (« PV cumulée ») | « **indice de changement** » | détails techniques, vignettes |
| `emprise` (fraction 0-1, `robust_frac_joint`) | « **% du carré modifié** » | vignettes, preuve |
| `pivot_confirme` | « **passage d'étape confirmé** » (jamais « pivot » seul côté client) | détails techniques |
| `progression` | « **avancement mesuré** » | détails techniques |
| `milestone_date` | « **mesurée le** <date> » | en-tête d'état |
| ancre $t_0$ / `baseline` | « **image d'ancrage** (point de départ) » | détails techniques, vignettes |
| `backfill` / « archive » | « **Chercher les images des derniers mois** » | bouton principal |
| `check` (mode latest) | « **Vérifier maintenant** » | bouton secondaire |
| `sr_method` / `sen2sr` / `bicubic_fallback` | « surrésolution (modèle satellite ou repli) » | détails techniques |
| `display_sr` / `realesrgan` | « affichage (image) » | infobulle de vignette |
| `cloud_pending`, `duplicate`, `baseline`, `ok` (statuts API) | phrases d'action en français (« aucune scène récente sous le seuil de nuages — réessayez plus tard ») | bandeau de statut |
| **mesure** (Sentinel-2, 10 m) | « **mesure** : sert à chiffrer le chantier » | partout |
| **lecture** (imagerie d'archive Esri, 0,3-0,5 m) | « **lecture** : sert à voir les bâtiments » | vue haute résolution |
| « emprise » (bbox) | « **ce carré** » / « votre emprise » | fiche, outil de dessin |
| OSM / Overpass | « emprises de bâtiments (OpenStreetMap) » — **retiré de l'IHM** (couverture nulle à Douala, service intermittent) | — |

## Termes SIG à ne pas confondre

| Terme | Sens précis |
|---|---|
| **emprise / AOI** | rectangle lon/lat mesuré. Ce n'est **pas** un bâtiment. |
| **point de mesure** (pixel) | 10 m × 10 m pour Sentinel-2, 20 m pour la couche nuages. |
| **pixel mixte** | un point qui contient plusieurs objets (la maison *et* ses voisines) : dilution du signal. |
| **ancre $t_0$** | première scène retenue, référence de toutes les comparaisons. |
| **SCL** | *Scene Classification Layer* : classes (nuage, ombre, cirrus, végétation…) à 20 m. |
| **pivot** | changement structurel qualifié (test sur la distribution des changements), base du passage M1→M2. |
| **hystérésis** | confirmation d'un changement pour éviter les faux positifs ; rend le suivi plus lent mais plus fiable. |
| **cadence** | intervalle entre deux passages ; Sentinel-2 = **écart médian 3 j** à Douala (mesuré), l'archive visuelle ≈ 1 mois. |

## Phrase-type de l'IHM (à conserver)

> **Où en est votre maison ?** — Étape 3 sur 5 — structure en progression *(mesurée le 2026-04-27)*
> **Sur quoi repose cette étape** — indices NDVI/NDBI/BSI de chaque date, comparés à l'image d'ancrage
> du 2026-03-18 (Sentinel-2, 10 m) : ce n'est pas une lecture d'image. À la date retenue : 8 % de
> l'emprise en changement robuste, indice de changement 0,1.
