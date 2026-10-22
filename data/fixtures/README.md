# Fixtures

`demo_request.json` : un transcript **entièrement synthétique** (orateur fictif) pour tester le pipeline sans YouTube.
Chaque phrase vise un cas de vérification :

| t | Affirmation | Cas visé | Verdict attendu (données au 2026-Q2) |
|---|---|---|---|
| 8 s | taux de chômage à 8,3 % | `niveau`, référentiel | vrai |
| 22 s | −3 points depuis 2017 | `evolution`, ampleur fausse (réel ≈ −1,1 pt) | trompeur |
| 36 s | plus bas depuis 40 ans | `record`, faux (le chômage remonte) | faux ou imprécis |
| 48 s | < 2 millions de demandeurs cat. A | `niveau`, volume (réel ≈ 3,3 M) | faux |
| 62 s | chômage des jeunes < 15 % | `niveau` (réel ≈ 21,6 %) | faux |
| 74 s | > 800 000 contrats d'apprentissage | hors référentiel → recherche web | dépend du web |
| 88 s | « aller vers le plein emploi » | promesse → **ne doit pas être extraite** | — |

Le Lot E ajoute ici les réponses mises en cache des vraies vidéos de démo (`<video_id>.json`).
