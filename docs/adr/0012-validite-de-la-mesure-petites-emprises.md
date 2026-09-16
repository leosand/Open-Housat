# ADR 0012 — Validité de la mesure sur une petite emprise (10-20 m)

Statut : accepté (2026-09-16)

## Contexte

Une maison individuelle fait **10 à 20 m de côté**. En testant un chantier réel de **16 × 8 m**
(technique : `POST /sites` puis `POST /sites/14/backfill`), le résultat était **zéro observation** :
les **20 scènes examinées** étaient toutes rejetées avec « nuages PARCELLE **100,0 %** », jamais
autre chose. Deux causes distinctes ont été isolées :

1. **Le remplissage du masque comptait comme des nuages.** `fetch_scl` appelait
   `rasterio.mask.mask(..., filled=True, nodata=0)`. Les pixels **hors emprise** sont alors remplis à
   `0`, valeur de la classe `NO_DATA` — **présente dans `SCL_OBSCURED`**, donc comptée comme
   « obscurcie ». Or la couche SCL est à **20 m** : une emprise de 16 × 8 m ne couvre **aucun centre
   de pixel**, la fenêtre était donc majoritairement (ou totalement) du remplissage → **100 % de
   nuages, systématiquement**.
2. **Juger les nuages sur un unique pixel n'a pas de sens.** Même sans remplissage, un test à 20 m sur
   une emprise de maison est un tirage au sort.

## Décision

1. **`filled=False`** dans `fetch_scl` : le masque devient un tableau masqué, et seules les valeurs
   **réellement valides** sont retournées (`compressed()`, vecteur 1-D). Le remplissage hors emprise
   ne peut plus être compté comme un nuage. Le paramètre mort `ref_shape` (aucun appelant) est retiré
   en même temps.
2. **Voisinage minimal de nuages** : `_scl_window(geom, SCL_MIN_SPAN_M = 60 m)` étend l'emprise lue
   pour le **test nuage** à 60 m de côté minimum, centrée sur l'emprise. La **mesure**, elle, reste sur
   l'emprise exacte. Une emprise ≥ 60 m n'est pas modifiée (comportement inchangé, ADR 0010 préservé).
3. **Aucun blocage côté produit** : l'IHM avertit (pixels mixtes, seuil de discrimination vers 30 m)
   mais laisse créer et mesurer (ADR 0011).

## Conséquences

- **Mesuré sur le chantier de 16 × 8 m : 0 → 6 observations** (2026-03-18 au 2026-05-25),
  **M0 → M2 « structure en progression », pivot confirmé** — même date de bascule (2026-04-27) que
  l'îlot de 178 m qui contient cette maison, ce qui est cohérent.
- Les scènes réellement nuageuses restent rejetées (100 % sur plusieurs dates de saison des pluies) :
  le correctif n'a pas rendu le filtre permissif, il l'a rendu **mesurant**.
- Sémantique affichée : sous 60 m de côté, le taux de nuages affiché qualifie le **voisinage** de
  l'emprise, pas elle seule (limite assumée, tracée dans `docs/limites-et-honnetete.md`).
- Test de non-régression : `pipeline/tests/test_clouds.py::test_scl_window_etend_les_emprises_de_maison`
  (maison 16 × 8 m étendue à 60 m ; parcelle 178 m inchangée).

## Limites

À cette échelle, la mesure reste **indicative** : 2 × 1 points, pixels mixtes, confiance 0,55 en repli
bicubique. La preuve solide reste l'imagerie d'archive haute résolution. Pour une mesure réellement
probante sur une maison, il faudrait soit **installer SEN2SR** (voie détection), soit changer de
capteur (imagerie sub-métrique commerciale) — dette assumée, chiffrée dans `docs/roadmap-90-days.md`.
