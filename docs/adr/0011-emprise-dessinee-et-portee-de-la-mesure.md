# ADR 0011 — L'utilisateur dessine l'emprise ; la mesure porte sur l'emprise entière

Statut : accepté (2026-09-16)

## Contexte

Le MVP supposait implicitement qu'une emprise = une maison. La démonstration livrée utilisait un
carré de **178 × 178 m** (un îlot) avec, en tête de fiche, la phrase « Où en est **votre maison** ? »
— affirmation **fausse par construction** : la mesure agrège tout le rectangle et ne désigne aucun
bâtiment. Deux conséquences observées :

1. l'utilisateur ne pouvait pas savoir **ce qui était mesuré** (le contour bleu n'était pas légendé) ;
2. il ne pouvait pas **choisir une autre emprise** depuis la carte, alors que c'est la seule façon
   honnête de « suivre une autre maison » à cette résolution.

Un premier outil « clic pour placer un carré de côté fixe » a échoué à l'usage : l'utilisateur a
spontanément **glissé** pour dessiner (idiome SIG standard), la carte s'est déplacée, rien n'est
apparu.

## Décision

1. **L'emprise est dessinée au glisser** : « Dessiner une emprise à analyser » → clic maintenu +
   glissement → aperçu orange vivant → relâche = emprise fixée sur **les deux cartes synchronisées**.
   Le **déplacement de la carte est suspendu** pendant le dessin.
2. **Création de chantier depuis la carte** : « Créer un chantier sur cette emprise » utilise
   `POST /sites` (aucune route nouvelle) ; le garde-fou anti-doublon existant (409) s'applique.
3. **Aucun seuil bloquant** : un bâtiment individuel fait 10-20 m de côté, on ne refuse pas ces
   emprises. En dessous de **30 m** de côté, l'IHM affiche un avertissement **chiffré et non
   bloquant** (« 2 × 1 points : pixels mixtes, la mesure devient discriminante vers 30 m »).
4. **Vocabulaire conditionnel** : « Où en est **votre maison** ? » seulement si le côté le plus long
   est ≤ **45 m** (échelle d'une parcelle) ; sinon « Où en est **ce chantier** ? » + phrase explicite
   (« ce carré couvre plusieurs bâtiments : le suivi porte sur l'ensemble du carré »).
5. **Caractérisation formelle affichée** : dimensions (m), surface (ha), nombre de **points de mesure**
   (`côté / 10`), légende des contours (bleu = zone analysée, orange = emprise en cours de dessin).
6. **Formulaire de création** ramené à une **parcelle de 22 m** (~0,0002°) au lieu d'un îlot de 178 m,
   avec la règle de taille expliquée.

## Conséquences

- Le produit ne promet plus « votre maison » sur un quartier : l'affirmation suit la géométrie.
- « Suivre une autre maison » = dessiner un autre carré et créer un chantier dessus : cohérent avec la
  physique (aucune analyse par bâtiment possible à 10 m, cf. ADR 0012).
- Retrait assumé de composants trompeurs : le **comparateur de mesure** (carte MapLibre + curseurs
  d'opacité, dont l'image de mesure est illisible et les curseurs sans effet visible) et le **calque
  OSM** (0 bâtiment cartographié à Douala, service intermittent) → fiche passée de 2 595 à 1 759 px.
  `apps/web/src/MapView.tsx` supprimé ; `GET /sites/{id}/compare` **conservé** côté API (surface
  publique testée).

## Limites

Le dessin reste **manuel** : aucune détection automatique de parcelle. Un utilisateur qui ignore où
est sa parcelle doit passer par un outil externe (bboxfinder.com, cadastre) — c'est documenté dans
l'IHM. Le plafond serveur reste ~2 km² par emprise (`_validate_bbox`).
