# Lot E — Démo et pitch

**Fichiers possédés** : `data/fixtures/`, `docs/PITCH.md` (à créer)

## Tâches
1. **[P0 — dès 0:00] Choisir 3 vidéos** : interviews ou débats récents, de personnalités de bords différents (pour la neutralité), qui parlent d'emploi et de chômage avec des chiffres. Vérifier que les sous-titres (même automatiques) existent. Les lister dans `data/fixtures/demo_videos.json` :
   ```json
   [{"video_id": "...", "speaker": {"name": "...", "party": "..."}, "date": "AAAA-MM-JJ", "title": "...", "note": "affirmation phare à 3:12"}]
   ```
2. **[P0] Relever à la main** 2 ou 3 affirmations phares par vidéo, avec leur horodatage. Elles servent de vérité terrain pour les Lots B et C.
3. **[P1] Mettre en cache** les réponses : après analyse, `curl localhost:8000/videos/<id>/claims > data/fixtures/<id>.json`.
4. **[P1] Écrire `docs/PITCH.md`** (3 min) :
   - **Problème** : en campagne, des centaines de chiffres sont cités chaque jour et le fact-checking humain arrive après coup.
   - **Démo live** (90 s) : vidéo, clic, cartes, clic sur l'horodatage, correction et source INSEE, puis l'onglet Profils.
   - **Différenciation** : verdict calculé sur données publiques, donc auditable et reproductible ; le LLM ne tranche pas les chiffres.
   - **Feuille de route** (`docs/ROADMAP.md`) : live, tous les thèmes, tous les médias, contradictions dans le temps.
   - **Éthique** (`docs/METHODOLOGIE.md`) : on juge des affirmations, pas des personnes ; méthodologie publique ; relecture humaine.
5. **[P2] Slide « chiffres »** : nombre de séries officielles intégrées (15), nombre d'affirmations vérifiées pendant le hackathon, temps moyen par vidéo.

## Critères de fin
- La démo se joue 2 fois de suite sans accroc, y compris backend coupé (lecture du cache).
