# Feuille de route 90 jours — Housat

## Phase 0 — Validation marche (J1-J14, budget < 50 $)

Script de validation :
1. Landing Carrd/Framer (~20 $) : « Suivez le chantier de votre maison au pays depuis l'etranger — satellite, alertes, 29 $/mois ». Pixel Meta.
2. 3 groupes Facebook/WhatsApp diaspora (ex. Cameroun, Haiti, Cote d'Ivoire) : sondage + formulaire d'intention.
3. Concierge MVP : 5 chantiers pilotes traites a la main avec le pipeline actuel, rapport PDF hebdo envoye par courriel. Objectif : 3 pre-paiements.

Critere de passage : >= 3 pre-paiements ou >= 40 intentions qualifiees.

## Phase 1 — MVP self-serve (J15-J45)

- apps/web : carte de dessin de polygone (MapLibre + terrains OSM gratuits), onboarding < 3 min (SXO).
- Stripe Checkout + portail client ; cadence hebdo automatique.
- Rapport PDF v1 : image avant/apres, score de changement, jalon courant, photo de confiance.
- SEO : pages /suivre-chantier-[pays] avec FAQPage JSON-LD (AEO), contenu cite (GEO).

## Phase 2 — Fiabilisation (J46-J75)

- U-Net siamois (inspire SenseEarth2020) pour reduire les faux positifs ombre/saison.
- Seuils adaptatifs par site (apprentissage sur historique).
- Partenariat verification terrain (reseau local, modele LandWatch) en option +9 $.
- WhatsApp Business API (Twilio) pour les alertes — canal prefere diaspora.

## Phase 3 — Monetisation etendue (J76-J90)

- Upsell imagerie commerciale 50 cm pour litiges (~15 $/image, marge 50 %).
- Offre B2B « preteurs diaspora » a 99 $/site/mois (sous-priced vs Terra Trace 149 $).
- Programme parrainage : 1 mois offert par filleul.

## Simulation financiere (par chantier, par mois)

| Poste | Cout |
|---|---|
| Verifications Sentinel-2 (~6/mois, calcul Actions) | ~0 $ (free tier 2000 min) |
| Stockage + bande passante | ~0,10 $ |
| Stripe (2,9 % + 0,30 $) | ~1,15 $ |
| Support amorti | ~2 $ |
| **Marge brute sur 29 $** | **~25,7 $ (89 %)** |

Seuil de rentabilite infra payante (VPS 20 $/mois + R2) : 2 clients.

## Dette technique assumee

- Fallback bicubique : jalon `low_confidence` trace en base, jamais masque au client.
- Pas encore de tuilage multi-scene : chantiers > 1 km2 decoupes en phase 2.
