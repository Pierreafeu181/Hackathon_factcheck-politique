# Lot 0 — Contrat de données ✅ FAIT (gelé)

**Livré** : `backend/app/models.py`, `schemas/claim.schema.json`, `docs/DATA_CONTRACT.md`, `db/schema.sql`.

Si un lot a besoin d'un nouveau champ :
1. L'ajouter en **optionnel** (`Optional[...] = None`) dans `models.py`, pour ne rien casser chez les autres.
2. Lancer `python -m app.export_schema`.
3. Mettre à jour `DATA_CONTRACT.md` et ajouter une ligne au changelog.
4. Prévenir l'équipe.

Attention aux sorties structurées Claude : pas de contraintes numériques (`ge`, `le`) ni de `pattern` dans les modèles envoyés au LLM (`ExtractionResult`, `WebVerification`, `ExplanationText`). Garder des types simples.
