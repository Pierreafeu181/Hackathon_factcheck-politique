# Lot B — Transcript et extraction des affirmations

**Fichiers possédés** : `backend/app/transcript.py`, `backend/app/extract.py`, `backend/app/prompts/extract.md`
**Objectif démo** : sur une vraie vidéo, **toutes** les affirmations emploi chiffrées sont extraites, avec le bon `indicator`, la bonne `value` (dans l'unité de l'indicateur), la bonne période et un horodatage exploitable. Aucune promesse ni opinion ne doit être extraite.

## État actuel
- `transcript.py` : `youtube-transcript-api` v1.x (`YouTubeTranscriptApi().fetch(id, languages=["fr","en"])`), plus le texte collé ou les segments envoyés par l'extension. `to_prompt_text()` regroupe les segments par fenêtres de 20 s préfixées `[123s]`.
- `extract.py` : un appel `llm.parse(..., ExtractionResult, effort="medium")`. La liste des indicateurs du référentiel est injectée dans le prompt (`{{INDICATORS}}`). On ne garde que `checkable=True` et les catégories demandées.
- `prompts/extract.md` : règles d'extraction et de normalisation (unités, millions → milliers, périodes, records).

## Tâches, par priorité
1. **[P0] Clé API + premier run** : `curl … -d @../data/fixtures/demo_request.json`. Comparer au tableau attendu dans `data/fixtures/README.md`.
2. **[P0] Vraies vidéos** : lancer sur les vidéos choisies par le Lot E, relire chaque affirmation extraite, corriger le prompt (pas le code) jusqu'à ce que ce soit propre. Noter les cas difficiles dans `data/fixtures/README.md`.
3. **[P1] Horodatages** : vérifier que `timestamp_start` tombe à ±10 s de la phrase. Sinon, réduire la fenêtre de `to_prompt_text` (20 s → 10 s).
4. **[P1] Longues vidéos (> 1 h)** : découper le transcript en blocs d'environ 15 min, extraire en parallèle, puis dédupliquer sur `claim`.
5. **[P2] Débats à plusieurs voix** : ajouter un champ optionnel `speaker_hint` (nouveau champ du contrat, voir LOT-0) quand le transcript permet de deviner qui parle.
6. **[P2] Si `youtube-transcript-api` est bloqué** : documenter l'usage du transcript DOM (Lot A), ou tester `yt-dlp --write-auto-subs --skip-download`.

## Critères de fin
- Fixture : 6 affirmations extraites (pas la promesse finale), indicateurs corrects.
- 2 vraies vidéos : au moins 80 % des affirmations emploi chiffrées repérées, 0 opinion extraite.

## Prompt de démarrage pour ton agent
> Lis AGENTS.md puis docs/lots/LOT-B-pipeline.md. Lance le backend et `POST /analyze` avec data/fixtures/demo_request.json. Compare le résultat au tableau de data/fixtures/README.md et améliore backend/app/prompts/extract.md pour corriger les écarts. Ne modifie pas le contrat de données.
