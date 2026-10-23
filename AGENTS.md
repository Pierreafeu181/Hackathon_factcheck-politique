# AGENTS.md — Instructions pour les agents de code (Claude Code, Cursor, Codex…)

> Ce fichier est la **source de vérité** pour tout agent qui travaille sur ce repo.
> `CLAUDE.md` l'importe. Lis-le en entier avant de toucher au code.

## 1. Le projet en 30 secondes

**Vérif'Pol** vérifie les affirmations des responsables politiques français :
1. une **extension Chrome** (ou la **veille RSS** du serveur) récupère le texte : transcript YouTube, article, sélection, podcast transcrit ;
2. le **moteur d'analyse Python** en **extrait les affirmations vérifiables** (surtout chiffrées) ;
3. il les **vérifie** contre des **données publiques** (INSEE, DARES) en priorité, puis contre le **web** en repli ;
4. il rend un **verdict**, une **correction** et des **sources** ;
5. il **stocke** tout pour construire un **profil de fiabilité par personnalité politique**.

Contexte : **hackathon de 3 h**, en vue de la présidentielle. Le référentiel de données officielles couvre pour l'instant **l'emploi et le chômage**.
Tout le reste (live, autres thèmes, contradictions dans le temps) est dans `docs/ROADMAP.md` — **ne pas le coder maintenant**.

## 2. Carte du repo

```
AGENTS.md / CLAUDE.md    ← tu es ici
README.md                ← présentation + lancement des 3 briques
shared/contract.ts       ← FORMAT D'ÉCHANGE extension ↔ serveur ↔ moteur (CheckRequest / CheckResponse / Watch*)

extension/               ← extension Chrome MV3 en TypeScript (Sébastien)
  src/sidepanel.ts       ← panneau : onglets « Cette page » et « Veille », cartes verdict, saut vidéo
  src/extract.ts         ← injecté dans la page : texte d'article (Readability) ou transcript YouTube horodaté
  src/background.ts      ← menu clic droit « vérifier la sélection »
  static/                ← manifest.json, sidepanel.html/css → copiés dans extension/dist par build.mjs
server/                  ← serveur Node/Hono, port 8790 (Sébastien)
  src/index.ts           ← /api/health, /api/check (relaie vers CHECKER_URL ou moteur démo), /api/watch
  src/checker.ts         ← appel du moteur (CHECKER_URL) + faux moteur de démo
  src/watcher.ts, rss.ts ← veille RSS (feeds.json), état dans server/data/state.json
  src/deepgram.ts        ← transcription Deepgram : podcasts (garde l'invité) et vidéos YouTube sans sous-titres
  src/media-audio.ts     ← télécharge l'audio d'une vidéo (YouTube sans sous-titres, TikTok, Reels, X…) avec yt-dlp + ffmpeg
  test/                  ← tests (npm test)

backend/                 ← MOTEUR D'ANALYSE Python / FastAPI, port 8000
  app/main.py            ← endpoints (/check pour le serveur Node, /analyze, /politicians…)
  app/check_api.py       ← adaptateur contract.ts ↔ pipeline Python (mapping des verdicts)
  app/models.py          ← modèles Pydantic (modèle interne + miroir de contract.ts)
  app/transcript.py      ← transcript YouTube côté serveur (souvent bloqué, voir §8)
  app/extract.py         ← LLM : texte → affirmations structurées
  app/verify.py          ← routeur de vérification (référentiel → web)
  app/referentiel.py     ← séries officielles + comparaison DÉTERMINISTE
  app/llm.py             ← client LLM unique : Gemini (défaut) ou Claude, sortie structurée, boucle d'outils
  app/tools.py           ← registre des outils de vérification exposés au modèle
  app/open_data.py       ← Eurostat, data.gouv.fr (producteurs publics certifiés), Banque mondiale, Google Fact Check*, Légifrance* (*clé)
  app/assemblee.py       ← votes de l'Assemblée nationale (open data officiel, indexé au démarrage)
  app/insee_api.py       ← outils Claude : API BDM de l'INSEE en direct (thèmes → séries → observations)
  app/db.py              ← SQLite (politicians, speeches, claims, verifications) + profils
  app/prompts/*.md       ← prompts système (à itérer ici, pas dans le code)
  app/selftest.py        ← autotests sans clé API
scripts/fetch_insee.py   ← (re)génère data/referentiel/<thème>.json depuis l'API INSEE
data/referentiel/        ← series.json (config) + emploi.json (données figées)
data/fixtures/           ← transcripts / requêtes de démo synthétiques
db/schema.sql            ← schéma SQL (SQLite, compatible Postgres/Supabase)
schemas/claim.schema.json← JSON Schema du modèle Python (généré)
docs/                    ← plan, architecture, contrat, méthodologie, sources, roadmap, lots/
```

## 3. Règles non négociables

1. **Deux formats, un seul à respecter pour l'échange.** `shared/contract.ts` est le format entre l'extension, le serveur et le moteur ; on ne le modifie **qu'en équipe**. Son miroir Python est dans `backend/app/models.py` (section « POST /check ») : si l'un change, l'autre change **dans le même commit**. Le modèle interne Python (`ExtractedClaim`, `Verification`, 6 verdicts) est plus riche ; il est converti par `app/check_api.py`.
2. **Les chiffres sont comparés en code, pas par le LLM.** Le LLM extrait, normalise (indicateur, période, unité) et rédige. La décision chiffrée vient de `referentiel.py`.
3. **Toujours une source.** Un verdict autre que `invérifiable` avec une liste de sources vide est un bug.
4. **Neutralité.** On juge des **affirmations**, jamais des personnes. Pas de mot « fake », « menteur », etc. dans l'UI ni dans les prompts. Voir `docs/METHODOLOGIE.md`.
5. **Pas de secret dans le repo.** Les clés vont dans `backend/.env` et `server/.env`, ignorés par git. Les modèles de fichier sont les `.env.example`.
6. **Modèle LLM** : centralisé dans `backend/app/llm.py`. **Gemini Flash (offre gratuite) par défaut** (`GEMINI_API_KEY`, `GEMINI_MODEL`), Claude en option (`LLM_PROVIDER=anthropic`) faute de crédits. N'instancie aucun client LLM ailleurs. Les sources de vérification sont des outils déclarés dans `backend/app/tools.py`.
7. **Démo d'abord.** Tout ce qui ne sert pas la démo va dans `docs/ROADMAP.md`.
8. **Un lot = des fichiers distincts** (voir §5). Commits petits et fréquents, `git pull --rebase` avant de pousser.

## 4. Commandes

```bash
# Moteur Python
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows : .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # ANTHROPIC_API_KEY (+ DATABASE_URL pour Postgres/Aiven)
python -m app.selftest                                 # autotests sans clé API (référentiel, DB, /check)
uvicorn app.main:app --reload --port 8000              # http://localhost:8000/docs

# Serveur Node + extension (depuis la racine)
npm install
cp server/.env.example server/.env                     # CHECKER_URL=http://localhost:8000/check (+ DEEPGRAM_API_KEY)
npm run dev:server                                     # http://localhost:8790
npm run build:ext                                      # → extension/dist, à charger dans chrome://extensions
npm test                                               # tests serveur + typecheck extension

# Tester le moteur directement
curl -X POST localhost:8000/check -H "Content-Type: application/json" -d @data/fixtures/check_request.json
curl -X POST localhost:8000/analyze -H "Content-Type: application/json" -d @data/fixtures/demo_request.json

# Régénérer le référentiel emploi depuis l'INSEE (pas de clé requise)
python scripts/fetch_insee.py
```

## 5. Répartition des lots (qui touche quoi)

| Lot | Spec | Fichiers possédés |
|---|---|---|
| 0 — Contrats | `docs/lots/LOT-0-contrat.md` | `shared/contract.ts`, `backend/app/models.py`, `docs/DATA_CONTRACT.md` (en équipe) |
| A — Extension + serveur Node | `docs/lots/LOT-A-extension.md` | `extension/**`, `server/**`, `package.json` |
| B — Extraction | `docs/lots/LOT-B-pipeline.md` | `backend/app/transcript.py`, `extract.py`, `prompts/extract.md` |
| C — Vérification | `docs/lots/LOT-C-verification-emploi.md` | `backend/app/referentiel.py`, `verify.py`, `check_api.py`, `prompts/verify_*.md`, `scripts/`, `data/referentiel/` |
| D — Stockage + profils | `docs/lots/LOT-D-stockage-profils.md` | `backend/app/db.py`, `db/schema.sql`, routes `/politicians*` |
| E — Démo + pitch | `docs/lots/LOT-E-demo-pitch.md` | `data/fixtures/`, `docs/PITCH.md` |

`backend/app/main.py` est partagé : n'y ajoute **que** tes routes, sans réorganiser le reste.

## 6. État actuel (à tenir à jour)

- [x] Extension TS : page, vidéo YouTube, sélection par clic droit, onglet Veille, saut vidéo (gère les pubs)
- [x] Serveur Node : relais `/api/check`, moteur de démo, veille RSS, transcription Deepgram des podcasts
- [x] Moteur Python : référentiel de 15 séries INSEE/DARES, comparaison déterministe, extraction, repli web, SQLite, profils
- [x] `POST /check` sur le moteur Python, compatible `shared/contract.ts` (autotest du mapping OK)
- [x] **Brancher et tester de bout en bout** : `CHECKER_URL=http://localhost:8000/check` avec une vraie clé Anthropic. Testé le 22/10 : fixture de démo (3 verdicts justes, 7 s avec `LLM_MODEL=claude-sonnet-5-5`, 12 s avec Opus 5.5) et veille podcasts (RMC, RTL, Sud Radio : Deepgram → moteur → 13 affirmations sourcées). Reste à tester le panneau de l'extension avec le vrai Claude
- [x] Onglet « Profils » dans l'extension : score de fiabilité, répartition des verdicts, dernières affirmations (`GET /politicians/{id}/claims`, relais `/api/politicians*` côté Node) — Lots A/D
- [x] Nom de l'orateur : `politician` et `date` ajoutés à `CheckRequest` dans `contract.ts` ; l'extension devine l'orateur depuis le titre (corrigeable)
- [x] Panneau en mode chat : vérification automatique des vidéos YouTube, chat (`/api/chat` → `/chat`), « Pourquoi ? » par carte, carte en cours surlignée, cache des analyses côté Node — Lot A
- [x] Base PostgreSQL : `db.py` bascule sur Postgres si `DATABASE_URL` est défini (SQLite sinon), testé sur Postgres 17 — Lot D
- [x] Outils INSEE en direct pour Claude (`insee_api.py`) : vérification web et chat lisent les séries officielles hors référentiel (inflation, dette, PIB…) — Lots A/C
- [x] Vidéos YouTube sans sous-titres : le serveur Node télécharge l'audio (yt-dlp) et le fait transcrire par Deepgram (`/api/transcribe-youtube`) — Lot A
- [x] Panneau façon ChatGPT : verdicts en liste dépliable, filtres par verdict, onglet Veille avec résumé faux/trompeur de la session (dédoublonné) et historique des pages analysées (`chrome.storage.local`) — Lot A
- [x] Analyse automatique des articles de presse (og:type / JSON-LD NewsArticle) et des vidéos de toutes plateformes (TikTok, Instagram, X, Facebook, Dailymotion, Vimeo, Twitch, france.tv…) via `/api/transcribe` ; suggestions de questions qui tournent — Lot A
- [x] Direct : bouton « ● Direct », son de l'onglet (chrome.tabCapture) → WebSocket `/api/live` → Deepgram en streaming → analyse toutes les ~45 s de parole. Marche sur n'importe quel site, y compris connecté — Lot A
- [x] Garde-fous du chat : hors sujet (code, devoirs…), consignes de vote et injections refusés (`prompts/chat.md`)
- [x] Passage à Gemini Flash (offre gratuite), Claude en option — `llm.py`
- [x] Sources de vérification : Eurostat, data.gouv.fr (producteurs publics certifiés seulement), Banque mondiale, votes de l'Assemblée nationale ; Google Fact Check et Légifrance dès que leurs clés sont dans `.env`. Wikipédia, réseaux sociaux et blogs exclus comme preuves ; hiérarchie des sources dans les prompts — Lot C
- [ ] Banque de France (clé du portail développeur) et OCDE (API refusée, 403)
- [x] Pipeline complet testé sur Gemini 3.5 Flash-Lite (gratuit) : benchmark 10/10 (Claude seul 3/10, Gemini seul 6/10), vidéo réelle en 14 s, chat avec les votes de l'Assemblée. `gemini-3.8-flash` n'a que 20 requêtes/jour en gratuit : il sert de secours
- [x] Aiven PostgreSQL branché (`DATABASE_URL`) : tables créées, analyses écrites et relues depuis Aiven
- [x] Image Docker d'hébergement (`Dockerfile`, `deploy/start.sh`, `docs/DEPLOY.md`) + clé d'accès `API_TOKEN` côté serveur et dans les Réglages de l'extension ; testée en local
- [x] Déployé sur Aiven Runtime (service `verifpol`, `startup-20-512`, branche `deploy` de `sebastiendero/aiven`) — voir `docs/DEPLOY.md`
- [ ] Itérer les prompts sur 2-3 vraies vidéos — Lots B/C
- [ ] Choisir et mettre en cache les vidéos de démo — Lot E

Quand tu termines une tâche, **coche-la ici** dans ton commit.

## 7. Définition de « fini » pour n'importe quelle tâche

- Ça tourne en local : `python -m app.selftest` et `npm test` passent.
- Les échanges respectent `shared/contract.ts`.
- Pas de nouveau secret ; les nouvelles dépendances sont ajoutées à `requirements.txt` ou au `package.json`.
- La case du §6 est cochée, et la spec du lot est mise à jour si le comportement a changé.

## 8. Pièges connus

- **Verdicts : 4 côté contrat, 6 côté Python.** Le mapping est dans `check_api.py` : plutôt vrai → `vrai`, imprécis → `trompeur`. La nuance est préfixée dans l'explication, suivie de « Correction : … ». Le contrat écrit **`invérifiable` avec accent** ; le Python interne écrit `inverifiable` sans accent.
- **YouTube transcript** : le serveur (Python ou Node) est souvent bloqué par YouTube. La voie normale, c'est l'extension qui lit la transcription dans la page (`extension/src/extract.ts`). `backend/app/transcript.py` ne sert qu'à `/analyze` en local. **Sans sous-titres**, et pour les vidéos des autres plateformes, l'extension appelle `/api/transcribe` : le serveur Node télécharge l'audio avec **yt-dlp + ffmpeg** (`brew install yt-dlp ffmpeg`, marche depuis un Mac, pas depuis un serveur hébergé) et l'envoie en fichier à Deepgram. Le lien audio ne peut pas être passé à Deepgram : il n'est valable que pour l'IP qui l'a demandé. Instagram et Facebook exigent souvent un compte : `YTDLP_COOKIES_FROM_BROWSER=chrome` (opt-in, machine perso). Les longues vidéos sans piste audio séparée (Dailymotion) sont lentes.
- **Sous-titres auto** : pas de ponctuation, et des chiffres parfois écrits en lettres (« sept virgule cinq pour cent »). C'est le prompt d'extraction qui normalise.
- **API INSEE en direct** (`insee_api.py`) : 30 appels/min (espacés automatiquement, cache 6 h). Les très gros thèmes (indices de prix) renvoient HTTP 413 : passer par les idbanks de `FREQUENT`. Le référentiel figé reste prioritaire, car son verdict est calculé en code ; avec l'outil en direct, c'est Claude qui compare (méthode `web`, confiance plafonnée à 0,7).
- **Chômage : BIT ≠ France Travail.** Le « taux de chômage » (INSEE, BIT) n'est pas le « nombre de demandeurs d'emploi » (France Travail, cat. A/B/C). Une confusion entre les deux donne `imprecis`, pas `faux`.
- **France entière vs hors Mayotte**, **CVS** : à toujours préciser dans la note des sources.
- **Périodes** : « depuis 2017 » = moyenne annuelle 2017 comparée au dernier point publié (voir `docs/METHODOLOGIE.md`).
- **Ports** : moteur Python sur 8000, serveur Node sur 8790. L'extension parle au serveur Node, qui parle au moteur Python.
- **Gemini, offre gratuite** : pas de recherche Google (payante) → la vérification hors INSEE passe par nos outils (`tools.py`). Quota par minute : `llm.py` limite les appels parallèles (`GEMINI_MAX_PARALLEL`) et relance sur 429. Les échanges peuvent servir à Google pour améliorer ses modèles.
- **Claude** (si `LLM_PROVIDER=anthropic`) : pas de `temperature`, pas de `budget_tokens`, pas de prefill ; utiliser `output_config.effort`. Recherche web `web_search_20260209`.
- **Windows** : chemins longs → `git config core.longpaths true`.
