# Vérif'Pol

Vérification des affirmations des responsables politiques français, sources officielles à l'appui.

Sur une vidéo YouTube, un article, une phrase sélectionnée ou un podcast suivi en veille :

1. le **transcript** ou le texte est récupéré ;
2. les **affirmations factuelles chiffrées** sont extraites ;
3. elles sont **comparées aux séries officielles** (INSEE, DARES / France Travail), ou vérifiées **sur le web** à défaut ;
4. l'extension affiche un **verdict**, une **explication avec correction** et les **sources**. Un clic renvoie au bon moment de la vidéo ;
5. tout est **stocké** pour construire une base de discours et un **profil de fiabilité** par personnalité.

> Hackathon, présidentielle. Le moteur vérifie en code, sur données officielles figées, l'**emploi**, l'**inflation**, la **croissance**, le **Smic**, la **dette** et le **déficit** (27 séries). Les autres thèmes passent par les outils de données ouvertes et les sites officiels.
> **Agents de code : lisez [`AGENTS.md`](AGENTS.md) en premier.**

## Les trois briques

```
┌─ extension/ (TypeScript) ─────┐   POST /api/check   ┌─ server/ (Node, port 8790) ─────┐   POST /check    ┌─ backend/ (Python, port 8000) ──────────┐
│ panneau latéral Chrome        │ ──────────────────► │ relais + veille RSS             │ ───────────────► │ moteur d'analyse                        │
│ - page / vidéo YouTube        │                     │ - podcasts → Deepgram           │  (CHECKER_URL)   │ - extraction (Claude)                   │
│ - sélection (clic droit)      │ ◄────────────────── │ - vidéos YouTube à ouvrir       │ ◄─────────────── │ - vérif. déterministe INSEE / DARES     │
│ - onglet Veille               │    CheckResponse    │ - moteur démo si pas de checker │  CheckResponse   │ - repli web, SQLite, profils            │
└───────────────────────────────┘                     └─────────────────────────────────┘                  └─────────────────────────────────────────┘
                                  shared/contract.ts = format d'échange (miroir Python : backend/app/models.py, section « POST /check »)
```

Principe clé : **c'est le code qui tranche sur les chiffres, pas le LLM.** Le LLM extrait et normalise ; sur nos séries officielles, l'explication et la correction sont aussi écrites par le code. La comparaison aux données officielles est déterministe, reproductible et sourcée.

## Lancer le tout

```bash
# 1. Moteur d'analyse (Python)
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows : .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                # mettre ANTHROPIC_API_KEY
python -m app.selftest                              # vérifie référentiel, DB, /check (sans clé API)
uvicorn app.main:app --reload --port 8000           # doc : http://localhost:8000/docs

# 2. Serveur de veille + extension (Node), depuis la racine
npm install
cp server/.env.example server/.env                  # CHECKER_URL=http://localhost:8000/check, + DEEPGRAM_API_KEY
npm run dev:server                                  # http://localhost:8790
npm run build:ext                                   # ou npm run watch:ext
```

Ensuite, dans Chrome :

1. Ouvrir `chrome://extensions`.
2. Activer le mode développeur.
3. Cliquer sur « Charger l'extension non empaquetée » et choisir le dossier `extension/dist`.
4. Cliquer sur l'icône Vérif'Pol pour ouvrir le panneau.

Tests :

- Node : `npm test`.
- Python : `cd backend && python -m app.selftest`.

Sans `CHECKER_URL`, le serveur Node répond avec un **faux moteur de démo**, marqué « [Démo] ». Avec `CHECKER_URL=http://localhost:8000/check`, il utilise le moteur Python.

## Veille RSS

Les flux suivis sont dans `server/feeds.json` : RMC Face à Face, l'invité RTL de 7h40, l'invité politique Sud Radio, Public Sénat et franceinfo sur YouTube.

- **Podcasts** : le lien MP3 du flux est envoyé à Deepgram (Nova-3, français, séparation des voix). On ne garde que les phrases de l'intervenant qui parle le plus (l'invité), puis on les envoie à l'analyse.
- **YouTube** : un serveur ne peut pas récupérer les sous-titres, car YouTube bloque. Les vidéos sont listées dans l'onglet « Veille » avec un bouton « Ouvrir et vérifier » ; l'extension lit alors la transcription dans le navigateur.

Au premier lancement, seul le dernier épisode de chaque flux est traité (`MAX_EPISODES_PER_FEED`), pour ne pas transcrire tout l'historique. L'état est gardé dans `server/data/state.json`.

## Sources de données

- **INSEE, API BDM** (SDMX, sans clé) et **Eurostat** : 27 séries figées dans `data/referentiel/` (emploi, économie, finances publiques), régénérables avec `python scripts/fetch_insee.py`. Détails dans [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md).
- **Google Fact Check Tools** : `https://factchecktools.googleapis.com/v1alpha1/claims:search?query=…&languageCode=fr&key=…`, gratuit avec une clé Google Cloud. L'API renvoie les fact-checks déjà publiés (AFP Factuel, Les Décodeurs, Libé CheckNews…) avec leur verdict. Branché (outil `factchecks_publies`) dès que `GOOGLE_FACTCHECK_API_KEY` est dans `backend/.env`. [Présentation](https://newsinitiative.withgoogle.com/resources/trainings/google-fact-check-tools/)

## Documentation

| Document | Contenu |
|---|---|
| [AGENTS.md](AGENTS.md) | Règles, carte du repo, commandes, état d'avancement (à lire en premier) |
| [docs/HACKATHON_PLAN.md](docs/HACKATHON_PLAN.md) | Planning, répartition de l'équipe |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Flux de données, API, choix techniques |
| [docs/DATA_CONTRACT.md](docs/DATA_CONTRACT.md) | Formats d'échange (`shared/contract.ts` et le modèle interne Python) |
| [docs/METHODOLOGIE.md](docs/METHODOLOGIE.md) | Échelle des verdicts, tolérances, neutralité, éthique |
| [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md) | Séries officielles utilisées, et comment en ajouter |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Live, autres thèmes, autres médias, contradictions |
| [docs/lots/](docs/lots/) | Une spec par lot de travail |
