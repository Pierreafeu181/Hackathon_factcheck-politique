# Feuille de route (après le hackathon — à pitcher, pas à coder maintenant)

## V1 — Couverture
- **Tous les thèmes** : un fichier `data/referentiel/<theme>.json` par domaine (voir `DATA_SOURCES.md`), en gardant le même contrat.
- **Mise à jour automatique** du référentiel (cron quotidien sur `fetch_insee.py`, plus les autres connecteurs : Eurostat, data.gouv, SSMSI…).
- **Comparaisons** (`claim_type = comparaison`) : France vs UE via Eurostat.
- **Données à la date du discours** : utiliser les données publiées *à cette date*, en gardant les millésimes (vintages).

## V2 — Quasi-live
- **YouTube live** : lire les sous-titres en direct par fenêtres de 60 s, puis `extract` + `verify` en continu, avec déduplication des affirmations.
- **Tout média** : capture audio de l'onglet (`chrome.tabCapture`), transcription Whisper en streaming, puis même pipeline. Couvre TV en replay, radio, Twitch, X.
- **Diarisation** : identifier qui parle dans un débat (pyannote), pour attribuer chaque affirmation au bon orateur.
- **Overlay** sur la vidéo : badge en surimpression au moment où l'affirmation est prononcée.

## V3 — Base de discours et profils
- **Ingestion massive** : chaînes YouTube officielles des partis, de l'Assemblée et du Sénat, comptes rendus de séance (débats en ligne de l'Assemblée, data.gouv), Vie publique.
- **Recherche sémantique** : « qu'a dit X sur le chômage ? » via des embeddings des affirmations (pgvector sur Supabase).
- **Détection de contradictions** dans le temps : « X a dit A en 2022, et ¬A en 2026 ».
- **Profils** : évolution du score dans le temps, par thème, comparaison anonymisée à la moyenne.
- **API publique** et widget intégrable pour les médias.

## Gouvernance (indispensable avant toute publication)
- Relecture humaine (journalistes partenaires) des verdicts `faux` et `trompeur` avant publication.
- Bouton « signaler une erreur » et droit de réponse.
- Méthodologie publique et versionnée ; journal des corrections.
- Avis juridique : diffamation, règles de l'Arcom en période électorale, RGPD (les opinions politiques sont des données sensibles, mais les déclarations publiques d'élus et de candidats sont publiques).
