# Plan hackathon (3 h)

Point de départ : le squelette est **déjà fonctionnel**. Le référentiel INSEE est chargé, la comparaison déterministe et le stockage sont testés, l'API et l'extension sont branchées.
Le travail restant consiste à **brancher la clé API, itérer sur de vraies vidéos et soigner la démo**.

## Timeline

| Heure | Toute l'équipe | Lot A — Extension | Lot B — Extraction | Lot C — Vérification | Lot D — Profils | Lot E — Démo |
|---|---|---|---|---|---|---|
| 0:00–0:15 | Clone, `.env`, `selftest`, chacun lance backend + extension | | | | | Choisir 3 vidéos candidates |
| 0:15–1:30 | | Robustesse SPA YouTube, état « chargement », lien profil | Tester `/analyze` sur les vidéos, itérer `prompts/extract.md` | Cas limites des comparaisons, prompt web, éventuellement + séries | Page profil dans l'extension | Rédiger le pitch, noter les vraies affirmations des vidéos |
| 1:30–1:45 | **Point d'intégration** : une vidéo réelle de bout en bout | | | | | |
| 1:45–2:30 | | Polish UI | Fiabiliser les timestamps | Fiabiliser les sources web | Seed de 3-4 discours en base | Mise en cache des réponses de démo |
| 2:30–2:45 | **Gel du code.** Répétition de la démo | | | | | |
| 2:45–3:00 | Pitch | | | | | |

## Répartition suggérée

- **1 personne front** → Lot A.
- **1 personne Python + prompts** → Lot B.
- **1 personne data** → Lot C. C'est le cœur : la crédibilité vient de la qualité des données.
- **1 personne** → Lot D, puis Lot E (démo et pitch).

Avec 3 personnes : fusionner D et E. Avec 2 : une personne sur A+D, une sur B+C, et le pitch ensemble.

## Règles d'équipe

- Une branche par lot (`lot-a-extension`…), merge sur `main` toutes les 45 min.
- Ne touchez pas aux fichiers d'un autre lot sans le prévenir (voir `AGENTS.md` §5).
- Contrat de données gelé : toute modification doit être annoncée à toute l'équipe.
- **À 2:30, plus de nouvelle fonctionnalité.** Seulement des correctifs de démo.

## Plan B pour la démo

1. Vidéos pré-analysées → les réponses sont en base SQLite et en cache (`/videos/{id}/claims` répond instantanément).
2. YouTube bloque le transcript → cocher « Utiliser la transcription affichée sur la page » dans l'extension, ou coller le texte.
3. API LLM lente ou en panne → rejouer `data/fixtures/<video_id>.json`.
