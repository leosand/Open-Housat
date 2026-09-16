# ADR 0013 — Étape monotone et étape prouvée dans l'interface

Statut : accepté (2026-09-16)

## Contexte

Deux défauts d'**honnêteté** ont été relevés par l'utilisateur sur la fiche d'état :

1. « Étape 3 sur 5 — structure en progression · dernière observation : 2026-03-21 » : la date affichée
   n'était **pas** celle qui avait établi l'étape (`/progress` exposait le jalon de la **dernière**
   observation, pas celui qui a franchi l'étape). La fiche semblait donc s'appuyer sur une image qui
   disait autre chose.
2. Après une alerte « **Étape franchie : structure en progression** », une scène ultérieure sans
   changement par rapport à l'ancre **redescendait** l'affichage à « terrain nu » : fiche et journal
   d'alertes se contredisaient.
3. Plus généralement, l'IHM **affirmait** une étape sans jamais montrer **sur quoi** elle reposait —
   vécu comme un mensonge, à juste titre.

## Décision

1. **Étape monotone** : `/sites/{id}/progress` expose le **plus haut jalon atteint**
   (`max(observation.milestone)`), pas le dernier calculé — même règle de monotonicité que les alertes.
   Le libellé est celui de l'observation qui a atteint ce jalon.
2. **Preuve exposée par l'API** (additif) : `milestone_date`, `milestone_emprise` (% de l'emprise en
   changement robuste à cette date), `milestone_pv` (indice de changement), `anchor_date` (image
   d'ancrage).
3. **Preuve affichée par l'IHM** :
   - en-tête : « Étape 3 sur 5 — structure en progression **(mesurée le 2026-04-27)** · dernière image
     analysée : 2026-05-25 » — la date de l'étape et la date de la dernière image sont **distinctes** ;
   - phrase « **Sur quoi repose cette étape** » : indices NDVI/NDBI/BSI, **date d'ancrage**, et les deux
     nombres retenus (« 8 % de l'emprise en changement robuste, indice de changement 0,1 ») ;
   - chaque vignette de mesure porte **ses propres chiffres** (« 2026-04-27 — étape : Structure ·
     8 % du carré modifié · indice 0,1 ») ;
   - « Détails techniques » déclare la **fiabilité et sa cause** (« 0,55 — surrésolution de repli
     (`bicubic_fallback`) : le modèle SEN2SR de la voie détection n'est pas installé dans ce
     déploiement ») ainsi que l'**image d'ancrage**.

## Conséquences

- Toute affirmation de l'IHM est reliée à une mesure datée et à deux nombres vérifiables
  (complément de `docs/limites-et-honnetete.md`).
- Une étape ne peut plus **régresser** à l'écran sans intervention : cohérence avec le journal
  d'alertes scellé et avec le rapport PDF.
- Les tests API existants restent verts (les champs ajoutés sont additifs ; `milestone` garde son
  type et son sens « étape atteinte »).

## Limites

L'étape reste une **sortie de classifieur à seuils** sur 1 à 3 points de mesure à l'échelle d'une
maison : indicative, non probante (ADR 0012). Un vrai classifieur (U-Net siamois, prévu phase 2)
remplacerait `detection/milestones.py` sans changer le contrat exposé ici.
