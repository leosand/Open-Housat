# Plan V&V — Housat MVP-l2

Objectif : demontrer localement la chaine E2E — backfill archive Sentinel-2, jalons M0-M4
avec qualification phenomenologique (pivots), comparaison avant/apres entre periodes,
dashboard web — avant les phases PDF/paiement.

## Indicateurs phenomenologiques (pipeline/housat/observations.py)

- PV_i = clip(delta_i vs t0, 0, +inf), tronquee sur l'anneau externe (ring=1), pour i in {NDVI, NDBI, BSI}
- Alignement grille : match_shape() (bilineaire vers geometrie ancre) avant TOUT calcul de PV/div —
  corrige le desalignement latent (fenetres de clip decalees d'un pixel selon les dates)
- Emprise robuste : m_i = { PV_i > q80(PV_i > 0) } ; emprise jointe = union des 3 masques
- pv_sum (par observation) = somme masquee q80 jointe des 3 indices
- Progression entre periodes arbitraires : 100 x pv_sum(t2)/pv_sum(t1), cap 130 %
  (< 100 = pivot negatif dans la periode ; >> 100 = croissance + pivot positif)
- Pivot qualifie : dPRA = sum(div[+])/sum(PV_t[+]) > 0.15 ET |moyenne(div[-])| < 0.05
- Jalons : M2 = pivot + emprise croissante ; M3 = pivot stabilise ; M1 = croissance sans pivot ;
  M4 = PV elevee + activite nulle ; sinon M0. Alertes in-app monotones (jamais de regression).

## Tests automatises

| Couche | Fichier | Couverture |
|---|---|---|
| Unitaires detection | pipeline/tests/test_change.py | indices, score adaptatif, jalons rules, low_confidence |
| Unitaires V&V/pivot | pipeline/tests/test_frames.py | frames npz, ring, divPV, pivot, M2/M0, PNG, **match_shape (alignement grille)** |
| API (TestClient) | apps/api/tests/test_api.py | 201/422/404 RFC 7807, **compare : 422 si from==to, 404 si observation hors chantier** |
| E2E web (Playwright) | apps/web/e2e/app.spec.ts | rendu accueil, formulaire, remontee d'erreur sans API (offline, CI) |
| Build web | CI job web-build | Vite/TypeScript strict |

```bash
python -m pytest pipeline/tests apps/api/tests -q
cd apps/web && npm install && npm run test:e2e
```

## Runbook E2E manuel

1. `docker compose -f infra/docker-compose.yml up --build`
2. http://localhost:8080 — creer « Chantier Demo » (bbox Douala pre-remplie, ou bboxfinder.com)
3. « Lancer le backfill archive » — statut running -> done, 5-10 observations, images PNG visibles
4. GET /sites/1/frames => {anchor: true, prev: true}
5. « Verifier maintenant » — nouvelle observation < 120 s
6. **Avant/Apres** : choisir deux dates dans les selecteurs -> curseur coulissant sur les images
   super-resolues (pixel-alignees via match_shape), delta jalon + progression de periode affiches
7. Jalon franchi => alerte in-app (canaux externes = phase 2)

## Criteres d'acceptation MVP-l2

| # | Critere | Seuil |
|---|---|---|
| A1 | Backfill reussit | >= 2 scenes, statut done |
| A2 | Ancre t0 persistee + reutilisee | frames.anchor == true |
| A3 | Alertes monotones | aucune regression de jalon signalee |
| A4 | Pivot confirme coherant | M2/M3 <=> pivot_confirme == true |
| A5 | Fallback SR trace | sr_method dans payload, confiance reduite si bicubique |
| A6 | Erreurs RFC 7807 | 404/422/409/502 en application/problem+json |
| A7 | 0 alerte externe | aucun appel ntfy/SMTP |
| A8 | **Avant/apres fiable** | images pixel-alignees (match_shape), progression periode = pv_sum ratio, 422 si dates identiques, 404 si hors chantier |

## Limites documentees (dette assumee)

- match_shape = reechantillonnage bilineaire, PAS une co-registration geodesique fine (phase 2 : warp GCP).
- Toiture vs finition indifferencee a 2,5 m sans multi-angle (M3 = « probable »).
- Comparaison ancre uniquement : hystere precis, reactivite lente ; series scene-a-scene en phase 2.
- Scenes tres nuageuses : observation marquee, jamais d'alerte sur donnee stale.
