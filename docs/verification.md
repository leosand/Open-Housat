# Plan V&V — Housat MVP-l1

Objectif : demontrer localement la chaine E2E — backfill archive Sentinel-2, jalons M0-M4
avec qualification phenomenologique (pivots), dashboard web — avant les phases PDF/paiement.

## Indicateurs phenomenologiques (implementation : pipeline/housat/observations.py)

- PV_i = clip(delta_i vs t0, 0, +inf), tronquee sur l'anneau externe (ring=1), pour i in {NDVI, NDBI, BSI}
- Emprise robuste : m_i = { PV_i > q80(PV_i > 0) } ; emprise jointe = union des 3 masques
- Progression : 100 x sum(divPV0[m0]) / sum(divPV_t[m_t]), cap 130 %.
  Interpretation : < 100 = pivot negatif (rebroussement), >> 100 = croissance + pivot positif.
- Pivot qualifie : dPRA = sum(div[+]) / sum(PV_t[+]) > 0.15 ET |moyenne(div[-])| < 0.05
- Jalons : M2 = pivot + emprise croissante ; M3 = pivot stabilise ; M1 = croissance sans pivot ;
  M4 = PV elevee + activite nulle ; sinon M0.

## Tests automatises

| Couche | Fichier | Couverture |
|---|---|---|
| Unitaires detection | pipeline/tests/test_change.py | indices, score adaptatif, jalons rules, flag low_confidence |
| Unitaires V&V/pivot | pipeline/tests/test_frames.py | roundtrip frames npz, troncature ring, divPV, pivot qualifie, M2/M0, PNG |
| API (TestClient) | apps/api/tests/test_api.py | 201 bbox valide, 422 RFC 7807 (bbox invalide/trop grande), 404 RFC 7807, progress idle, listes |
| Build web | CI job web-build | compilation Vite/TypeScript strict |

```bash
python -m pytest pipeline/tests apps/api/tests -q   # attendu : ~20 tests verts, 0 reseau
```

## Runbook E2E manuel (verification empirique)

1. `docker compose -f infra/docker-compose.yml up --build`
2. http://localhost:8080 — creer « Chantier Demo » avec la bbox pre-remplie (Douala)
   ou votre propre bbox (bboxfinder.com)
3. « Lancer le backfill archive » — attendu : statut running, polling 5 s, puis done
   avec 5-10 observations, dates ISO, images PNG Sentinel-2 visibles
4. Verifier presence ancre/prev : GET /sites/1/frames => {anchor: true, prev: true}
5. « Verifier maintenant » — attendu : reponse < 120 s, nouvelle observation, jalon mis a jour
6. Si un jalon est franchi : alerte in-app listee dans le dashboard (canal externe = phase 2)

## Criteres d'acceptation MVP-l1

| # | Critere | Seuil |
|---|---|---|
| A1 | Backfill reussit sur bbox test | >= 2 scenes, statut done |
| A2 | Ancre t0 persistee + reutilisee | frames.anchor == true, comparaisons toutes vs t0 |
| A3 | Jalons monotones dans les alertes | aucune alerte de regression de jalon |
| A4 | Pivot confirme coherant | milestone M2/M3 <=> pivot_confirme == true |
| A5 | Fallback SR trace | sr_method dans payload ; confidence reduite si bicubique |
| A6 | Erreurs RFC 7807 | 404/422/409/502 en application/problem+json |
| A7 | 0 alerte externe emise | aucun appel ntfy/SMTP dans ce perimetre |

## Limites documentees (dette assumee)

- Toiture vs finition reste indifferencee a 2,5 m sans multi-angle (M3 = « probable »).
- Cumul des masques joint|anneau peut sous-estimer la progression — metrique affichee telle quelle, non lissee.
- Comparaison ancre uniquement (pas de comparaison scene-a-scene) : hystere precis mais reactif lent.
- Scenes tres nuageuses : observation marquee, jamais d'alerte sur donnee stale.
