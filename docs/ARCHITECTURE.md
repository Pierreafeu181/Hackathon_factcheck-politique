# Architecture

## Flux

```
┌───────────── Chrome ─────────────┐        ┌──────────────────── backend (FastAPI) ────────────────────┐
│ content.js (youtube.com)         │        │                                                            │
│  - videoId, titre, chaîne        │        │ POST /analyze                                              │
│  - seek(t)                       │        │   1. cache ? (speech "yt:<id>" déjà en base) → renvoie     │
│  - transcript du DOM (plan B)    │        │   2. transcript.py   → segments [{start, text}]            │
│            ▲   │                 │        │   3. extract.py      → Claude (sortie structurée)          │
│   messages │   ▼                 │  HTTP  │                        ExtractionResult.claims[]           │
│ sidepanel.js ────────────────────┼───────►│   4. verify.py  (6 threads en parallèle)                   │
│  - formulaire orateur/date       │        │        ├─ referentiel.check()  → verdict calculé            │
│  - cartes verdict, seek          │◄───────┼        │     └─ Claude rédige l'explication (effort low)   │
│  - onglet Profils                │  JSON  │        ├─ sinon web : Claude + web_search → JSON structuré │
└──────────────────────────────────┘        │        └─ sinon inverifiable                               │
                                            │   5. db.py → SQLite                                        │
                                            │ GET /videos/{id}/claims · /politicians · /politicians/{id} │
                                            │ GET /indicators · /health                                  │
                                            └────────────────────────────────────────────────────────────┘
                     data/referentiel/emploi.json  ◄── scripts/fetch_insee.py ◄── API SDMX BDM INSEE
```

## Endpoints

| Méthode | Route | Rôle |
|---|---|---|
| GET | `/health` | Vivant + nombre d'indicateurs chargés |
| GET | `/indicators` | Liste des séries du référentiel (clé, libellé, dernier point) |
| POST | `/analyze` | Body `AnalyzeRequest` → `AnalyzeResponse`. Mis en cache par `video_id` sauf `force: true` |
| GET | `/videos/{video_id}/claims` | Résultats déjà calculés (404 sinon) |
| GET | `/politicians` | Liste des profils (`PoliticianProfile`) |
| GET | `/politicians/{slug}` | Un profil ; slug = nom en minuscules sans accents, tirets |

Tous les schémas sont dans `backend/app/models.py`, et la doc interactive est sur `/docs`.

## Choix techniques et justification

| Choix | Pourquoi |
|---|---|
| Référentiel **figé** en JSON plutôt qu'appels live | Démo fiable hors ligne, comparaisons reproductibles, pas de quota. Mise à jour : `scripts/fetch_insee.py` |
| **Verdict calculé en code** | Le jury et les utilisateurs doivent pouvoir auditer, et le LLM peut se tromper en arithmétique ou halluciner un chiffre |
| Recherche web en **repli** avec confiance ≤ 0,7 | Couvre les affirmations hors référentiel, avec moins de garanties |
| Sources web **filtrées** sur les URL réellement vues par `web_search` | Empêche les URL inventées |
| SQLite | Zéro installation. Schéma compatible Postgres/Supabase pour la suite |
| Side panel MV3 en JS natif | Pas de build, chargement instantané |
| Un seul module LLM (`llm.py`) | Modèle, fallbacks et effort réglés en un seul endroit |

## Performances (ordre de grandeur)

- Extraction : 1 appel LLM par vidéo (transcript complet ; le contexte d'1M tokens suffit pour plusieurs heures de discours).
- Vérification : 1 appel court par affirmation couverte par le référentiel, 2 appels (recherche, puis structuration) en mode web.
- Une interview de 20 min contient environ 5 à 15 affirmations emploi, soit **30 s à 2 min** selon la part de recherche web.
- Pour accélérer : `LLM_MODEL=claude-sonnet-5-5`, ou `use_web: false`.

## Passage au « quasi-live » (après le hackathon)

Voir `ROADMAP.md`. Le backend est déjà découpé pour ça : `extract_claims()` accepte n'importe quel morceau de texte. Le live consiste à appeler l'analyse par fenêtres glissantes de 60 s (sous-titres live ou audio de l'onglet transcrit par Whisper), en dédupliquant les affirmations.
