# Lot D — Stockage et profils des personnalités

**Fichiers possédés** : `backend/app/db.py`, `db/schema.sql`, routes `/politicians*` de `main.py`
**Objectif démo** : après 3 ou 4 discours analysés, l'onglet **Profils** montre pour chaque personnalité le nombre d'affirmations, la répartition des verdicts et un score de fiabilité transparent.

## État actuel
- SQLite par défaut (`backend/factcheck.db`), **PostgreSQL** si `DATABASE_URL` est défini dans `backend/.env` (Aiven, Supabase…). Même schéma `db/schema.sql` et mêmes requêtes pour les deux : n'y écrire que du SQL portable (`CURRENT_TIMESTAMP`, `DOUBLE PRECISION`, `ON CONFLICT … DO UPDATE`, pas de `INSERT OR REPLACE` ni de `datetime('now')`). Tables `politicians`, `speeches` (avec le transcript JSON), `claims`, `verifications` (JSON complet + colonnes indexées).
- `db.profile()` : verdicts, répartition par catégorie, score 0-100 (pondérations dans `VERDICT_WEIGHTS`, minimum 5 affirmations). Autotesté.
- Endpoints `GET /politicians` et `GET /politicians/{slug}`.

## Tâches, par priorité
1. **[P0] Seed de démo** : un script `scripts/seed_demo.py` qui appelle `/analyze` sur la liste des vidéos du Lot E (`data/fixtures/demo_videos.json` : `video_id`, orateur, parti, date) pour pré-remplir la base.
2. **[P1] `GET /politicians/{slug}/claims`** : toutes les affirmations d'une personnalité, filtrables par `indicator` et `verdict`. C'est l'amorce de « qu'a dit X sur le chômage ? ».
3. **[P1] `GET /indicators/{key}/claims`** : qui a dit quoi sur un indicateur (ex. tous les chiffres cités sur le chômage des jeunes), à comparer avec la courbe officielle. C'est un très bon visuel pour le pitch.
4. **[P2] Export** CSV/JSON de la base (`GET /export`) pour le jury.
5. ~~**[P2] Postgres**~~ : fait, via `DATABASE_URL` (psycopg 3 + pool de 5 connexions). Les colonnes JSON restent en `TEXT` pour garder un seul schéma. Autotest sur Postgres : `SELFTEST_DATABASE_URL=postgres://… python -m app.selftest`, sur une base **vide et jetable**.

## Critères de fin
- 3 personnalités ou plus en base, avec des profils cohérents, affichés dans l'extension.

## Prompt de démarrage pour ton agent
> Lis AGENTS.md puis docs/lots/LOT-D-stockage-profils.md. Ajoute l'endpoint GET /politicians/{slug}/claims dans backend/app/main.py (sans réorganiser le reste du fichier) en t'appuyant sur backend/app/db.py, puis écris scripts/seed_demo.py.
