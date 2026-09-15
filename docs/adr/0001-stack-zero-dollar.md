# ADR 0001 — Stack zero dollar

Statut : accepte (2026-09-15)

## Contexte

Le modele economique exige un cout marginal par verification < 3 $. Toute dependance payante au demarrage tue la marge B2C a 29 $/mois.

## Decision

| Couche | Choix | Alternative rejetee | Raison du rejet |
|---|---|---|---|
| Imagerie | Sentinel-2 L2A via STAC Earth Search (sans compte) | Planet / SkyWatch | 7-12 $/km2, min de scene |
| Superresolution | SEN2SR (ESA OpenSR, pip, poids fournis) | entrainer S2DR4 from scratch | semaines de GPU + dataset ; reimplementer apres traction |
| Detection | indices spectraux + PCA/k-means ; U-Net siamois en phase 2 | foundation models AWS | SageMaker hors budget |
| Compute | GitHub Actions runners (cron) + Colab | AWS ECS | facturation a la minute |
| DB | PostGIS (Docker) | Supabase free | ok aussi, mais PostGIS local = souverainete donnees |
| Stockage | MinIO local, puis Cloudflare R2 free tier | S3 | egress |
| Alertes | ntfy.sh + SMTP | Twilio | payant ; WhatsApp en phase 2 |
| Paiement | Stripe | Paddle | standard, pas de raison de devier |
| API | FastAPI + SQLModel | NestJS | pipeline deja en Python, une seule langue au demarrage |

## Consequences

- Couverture temporelle : 5 jours (Sentinel-2), acceptable pour jalons batiment.
- Resolution utile 2,5 m : suffisant pour emprise bati/jalons, insuffisant pour comptage de fenetres — assume.
- Reevaluation a 100 clients payants : envisager imagerie commerciale en upsell.
