# Lot C — Vérification (thème emploi)

**Fichiers possédés** : `backend/app/referentiel.py`, `backend/app/verify.py`, `backend/app/prompts/verify_*.md`, `scripts/`, `data/referentiel/`
**Objectif démo** : chaque affirmation couverte par le référentiel reçoit un verdict **calculé**, avec la valeur officielle, la période, la source INSEE cliquable et une correction. Les autres passent en recherche web, avec des sources réelles.

## État actuel
- `data/referentiel/emploi.json` : **15 séries INSEE/DARES** (détail dans `docs/DATA_SOURCES.md`), régénérables avec `scripts/fetch_insee.py`.
- `referentiel.py` : chargement, conventions de période, comparaisons `niveau`, `evolution` (sens + ampleur, confusion points / %) et `record` (« plus bas depuis N ans », avec repli « c'était vrai il y a peu » → imprécis). Tolérances en tête de fichier. Autotesté (`python -m app.selftest`).
- `verify.py` : référentiel, sinon web (`llm.web_research`, puis structuration, puis filtrage des URL réellement vues ; confiance ≤ 0,7), sinon invérifiable.
- Hors référentiel, Claude dispose aussi des **outils INSEE en direct** (`app/insee_api.py` : `insee_chercher_themes`, `insee_lister_series`, `insee_lire_serie`). Il lit la série officielle (inflation, dette, PIB…) et cite sa page insee.fr, comptée comme source officielle. Testé : « inflation > 4 % » → faux (3,1 % en sept. 2026) ; « dette 3 600 Md€, 119 % du PIB » → vrai.

## Tâches, par priorité
1. **[P0] Cas limites** sur les vraies affirmations du Lot B. Ajouter chaque cas dans `selftest.py`.
2. **[P0] Confusion BIT / France Travail** : si `indicator` est un taux BIT mais que `unit` est en milliers ou personnes, ou l'inverse, rendre `imprecis` avec l'explication. Aujourd'hui ce cas n'est pas détecté. Ajouter une table `AMBIGUOUS = {...}` dans `referentiel.py`.
3. **[P1] `period_end` à la date du discours** : si `date` est fournie et `period_end` est null, comparer au dernier point **publié avant** cette date. Passer `speech_date` jusqu'à `referentiel.check`.
4. **[P1] Séries supplémentaires utiles** : contrats d'apprentissage (DARES, sur data.gouv), créations d'emplois annuelles (différence de `emploi_salarie_total`, déjà calculable avec `evolution`), chômage par région si besoin.
5. **[P1] Prompt web** (`prompts/verify_web.md`) : tester 5 affirmations hors référentiel et vérifier la qualité des sources (privilégier les sources primaires).
6. **[P2] Cache web** : mémoriser `claim → Verification` (dictionnaire en mémoire ou table SQL) pour ne pas relancer la recherche sur une affirmation identique.

## Critères de fin
- `python -m app.selftest` passe avec au moins 10 cas.
- Sur la fixture, les verdicts correspondent au tableau de `data/fixtures/README.md`.
- 100 % des verdicts autres que `inverifiable` ont au moins une source dont l'URL fonctionne.

## Prompt de démarrage pour ton agent
> Lis AGENTS.md, docs/METHODOLOGIE.md puis docs/lots/LOT-C-verification-emploi.md. Commence par la tâche P0 n°2 (confusion taux BIT / demandeurs d'emploi) dans backend/app/referentiel.py, ajoute les cas de test dans backend/app/selftest.py, et garde la règle : le verdict chiffré est calculé en code, jamais par le LLM.
