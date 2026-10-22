# AGENTS.md — Instructions pour les agents de code (Claude Code, Cursor, Codex…)

> Ce fichier est la **source de vérité** pour tout agent qui travaille sur ce repo.
> `CLAUDE.md` l'importe. Lis-le en entier avant de toucher au code.

## 1. Le projet en 30 secondes

**FactCheck Politique** : une extension Chrome qui, sur une vidéo YouTube d'un·e responsable politique,
1. récupère le **transcript** ;
2. en **extrait les affirmations factuelles vérifiables** (surtout chiffrées) ;
3. les **vérifie** contre des **données publiques** (INSEE, DARES, data.gouv) en priorité, puis contre le **web** en repli ;
4. rend un **verdict** (vrai / plutôt vrai / imprécis / trompeur / faux / invérifiable) avec **correction** et **sources** ;
5. **stocke** tout pour construire à terme un **profil de fiabilité par personnalité politique**.

Contexte : **hackathon, 3 h**, en vue de la présidentielle. Périmètre MVP : **la thématique EMPLOI / CHÔMAGE uniquement**.
Tout le reste (live, autres thèmes, autres médias, contradictions dans le temps) est dans `docs/ROADMAP.md` — **ne pas le coder maintenant**.

## 2. Carte du repo

```
AGENTS.md                ← tu es ici
README.md                ← présentation humaine + quickstart
docs/
  HACKATHON_PLAN.md      ← planning 3 h, qui fait quoi
  ARCHITECTURE.md        ← flux de données, endpoints, choix techniques
  DATA_CONTRACT.md       ← format JSON d'une affirmation / d'un verdict (CONTRAT GELÉ)
  METHODOLOGIE.md        ← échelle des verdicts, règles de neutralité, éthique
  DATA_SOURCES.md        ← séries INSEE/DARES utilisées, comment les mettre à jour
  ROADMAP.md             ← l'après-hackathon
  lots/LOT-*.md          ← une spec par lot de travail, avec critères de fin
schemas/claim.schema.json← JSON Schema du contrat (validé côté backend)
backend/                 ← API FastAPI (Python 3.11+)
  app/main.py            ← endpoints
  app/models.py          ← modèles Pydantic = contrat de données
  app/transcript.py      ← récupération transcript YouTube
  app/extract.py         ← LLM : transcript → affirmations
  app/verify.py          ← routeur de vérification (référentiel → web)
  app/referentiel.py     ← chargement des séries + comparaison DÉTERMINISTE
  app/llm.py             ← client Claude unique (modèle, fallbacks, helpers)
  app/db.py              ← SQLite (politicians, speeches, claims, verifications)
  app/prompts/*.md       ← prompts système (à itérer ici, pas dans le code)
scripts/fetch_insee.py   ← (re)génère data/referentiel/emploi.json depuis l'API INSEE
data/referentiel/        ← séries.json (config) + emploi.json (données figées)
data/fixtures/           ← transcript de démo synthétique pour tester sans YouTube
db/schema.sql            ← schéma SQL (SQLite, compatible Postgres/Supabase)
extension/               ← extension Chrome Manifest V3 (side panel)
```

## 3. Règles non négociables

1. **Le contrat de données (`docs/DATA_CONTRACT.md`, `backend/app/models.py`, `schemas/claim.schema.json`) est gelé.**
   Si tu dois le changer : change les 3 fichiers **dans le même commit** et préviens l'équipe (message dans le canal + ligne dans `docs/DATA_CONTRACT.md#changelog`).
2. **Les chiffres sont comparés en code, pas par le LLM.** Le LLM sert à : extraire, normaliser (indicateur, période, unité), et rédiger l'explication. La décision chiffrée vient de `referentiel.py`.
3. **Toujours une source.** Un verdict autre que `invérifiable` sans `sources[]` non vide est un bug.
4. **Neutralité.** On juge des **affirmations**, jamais des personnes. Pas de mot « fake », « menteur », etc. dans l'UI ni les prompts. Voir `docs/METHODOLOGIE.md`.
5. **Pas de secret dans le repo.** Clé API dans `backend/.env` (ignoré par git). Modèle de fichier : `backend/.env.example`.
6. **Modèle LLM** : centralisé dans `backend/app/llm.py` (`claude-opus-5-5` par défaut, surchargeable via `LLM_MODEL`). Ne pas instancier de client Anthropic ailleurs.
7. **Démo d'abord.** Tout ce qui ne sert pas la démo de fin de hackathon va dans `docs/ROADMAP.md` au lieu d'être codé.
8. **Un lot = un dossier/fichiers distincts** pour éviter les conflits git (voir §5). Commits petits et fréquents, `git pull --rebase` avant de pousser.

## 4. Commandes

```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows : .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # puis renseigner ANTHROPIC_API_KEY
uvicorn app.main:app --reload --port 8000

# Tests rapides (sans clé API : référentiel + transcript)
python -m app.selftest

# Régénérer le référentiel emploi depuis l'INSEE (pas de clé requise)
python ../scripts/fetch_insee.py

# Analyse de bout en bout sur le transcript de démo (clé API requise)
curl -X POST localhost:8000/analyze -H "Content-Type: application/json" \
  -d @../data/fixtures/demo_request.json
```

Extension : `chrome://extensions` → mode développeur → « Charger l'extension non empaquetée » → dossier `extension/`.
L'URL du backend se règle dans `extension/config.js` (défaut `http://localhost:8000`).

## 5. Répartition des lots (qui touche quoi)

| Lot | Spec | Fichiers possédés | Dépend de |
|---|---|---|---|
| 0 — Contrat | `docs/lots/LOT-0-contrat.md` | `docs/DATA_CONTRACT.md`, `app/models.py`, `schemas/` | — (fait, gelé) |
| A — Extension | `docs/lots/LOT-A-extension.md` | `extension/**` | contrat |
| B — Transcript + extraction | `docs/lots/LOT-B-pipeline.md` | `app/transcript.py`, `app/extract.py`, `app/prompts/extract.md` | contrat |
| C — Vérification emploi | `docs/lots/LOT-C-verification-emploi.md` | `app/referentiel.py`, `app/verify.py`, `app/prompts/verify_*.md`, `scripts/`, `data/referentiel/` | contrat |
| D — Stockage + profils | `docs/lots/LOT-D-stockage-profils.md` | `app/db.py`, `db/schema.sql`, endpoints `/politicians*` | contrat |
| E — Démo + pitch | `docs/lots/LOT-E-demo-pitch.md` | `data/fixtures/`, `docs/PITCH.md` | tout |

`app/main.py` est partagé : n'y ajoute **que** tes routes, sans réorganiser le reste.

## 6. État actuel (à tenir à jour)

- [x] Contrat de données, schéma SQL, squelettes de tous les modules
- [x] Référentiel emploi INSEE figé dans `data/referentiel/emploi.json` (voir `docs/DATA_SOURCES.md` pour la liste exacte)
- [x] Comparaison déterministe niveau / évolution / record (`referentiel.py`) + autotest
- [x] Endpoints `/analyze`, `/videos/{id}/claims`, `/politicians`, `/politicians/{id}`
- [x] Extension : side panel, lecture de l'ID vidéo, affichage des cartes, saut au timestamp
- [ ] Itérer les prompts sur 2-3 vraies vidéos (Lot B/C)
- [ ] Ajouter des séries DARES / France Travail (demandeurs d'emploi) si besoin (Lot C)
- [ ] Page profil politicien dans l'extension (Lot D/A)
- [ ] Choisir et mettre en cache les vidéos de démo (Lot E)

Quand tu termines une tâche, **coche-la ici** dans ton commit.

## 7. Définition de « fini » pour n'importe quelle tâche

- Le code tourne localement (`uvicorn` démarre, `python -m app.selftest` passe).
- Les sorties respectent le contrat (Pydantic valide).
- Pas de nouveau secret, pas de nouvelle dépendance non ajoutée à `requirements.txt`.
- La case correspondante du §6 est cochée, et la spec du lot mise à jour si le comportement a changé.

## 8. Pièges connus

- **YouTube transcript** : `youtube-transcript-api` (v1.x : `YouTubeTranscriptApi().fetch(video_id, languages=["fr"])`) marche depuis une IP perso, **bloqué depuis beaucoup d'IP cloud**. Plan B : l'extension envoie le texte du panneau « Transcription » de YouTube, ou on colle le transcript à la main (`transcript` dans la requête `/analyze`).
- **Sous-titres auto** : pas de ponctuation, chiffres parfois écrits en lettres (« sept virgule cinq pour cent »). Le prompt d'extraction doit normaliser.
- **Chômage : BIT ≠ France Travail.** Le « taux de chômage » (INSEE, BIT, enquête) n'est pas le « nombre de demandeurs d'emploi » (France Travail, catégories A/B/C). Un politique qui mélange les deux → verdict `imprécis`, pas `faux`.
- **France entière vs hors Mayotte**, **CVS** (données corrigées des variations saisonnières) : toujours préciser dans `sources[].note`.
- **Périodes** : « depuis 2017 » = comparer au T2 2017 (élection) ou à la moyenne 2017 ? Choix fait : dernier point **avant** la date citée ; le dire dans l'explication.
- **Claude Opus 5.5** : pas de `temperature`, pas de `budget_tokens`, pas de prefill ; utiliser `output_config.effort`. Les `web_search` server tools = `web_search_20260209`. Tout est déjà encapsulé dans `app/llm.py`.
