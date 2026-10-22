# FactCheck Politique

**Une extension Chrome qui vérifie en direct les chiffres cités dans les discours politiques, à partir des données publiques.**

Sur une vidéo YouTube d'une interview, d'un meeting ou d'un débat, l'extension :

1. récupère le **transcript** ;
2. en extrait les **affirmations factuelles chiffrées** (« le chômage a baissé de 3 points depuis 2017 ») ;
3. les **compare aux séries officielles** (INSEE, DARES / France Travail via data.gouv) ou, à défaut, les vérifie **sur le web** ;
4. affiche un **verdict** (vrai, plutôt vrai, imprécis, trompeur, faux, invérifiable), la **valeur officielle**, une **correction** et les **sources**. Un clic renvoie au bon moment de la vidéo ;
5. **stocke** tout pour construire une base de discours analysés et un **profil de fiabilité** par personnalité.

> Hackathon, présidentielle. MVP limité à la thématique **emploi / chômage** (15 séries officielles).
> **Agents de code : lisez [`AGENTS.md`](AGENTS.md) en premier.**

## Démarrage rapide (5 min)

```bash
git clone <ce repo> && cd factcheck-politique/backend
python -m venv .venv && source .venv/bin/activate   # Windows : .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                # mettre ANTHROPIC_API_KEY
python -m app.selftest                              # vérifie référentiel + DB, sans clé API
uvicorn app.main:app --reload --port 8000           # doc API : http://localhost:8000/docs
```

Ensuite, pour l'extension :

1. Ouvrir `chrome://extensions`.
2. Activer le mode développeur.
3. Cliquer sur « Charger l'extension non empaquetée » et choisir le dossier `extension/`.
4. Ouvrir une vidéo YouTube, puis cliquer sur l'icône de l'extension.

Pour tester sans YouTube, avec un transcript synthétique :

```bash
curl -X POST localhost:8000/analyze -H "Content-Type: application/json" -d @../data/fixtures/demo_request.json
```

## Comment ça marche

```
YouTube ──► extension (side panel) ──POST /analyze──► backend FastAPI
                                                      │
                     transcript.py   (youtube-transcript-api, ou transcript envoyé par l'extension)
                          │
                     extract.py      Claude → affirmations structurées (indicateur, valeur, unité, période)
                          │
                     verify.py ──► referentiel.py   comparaison DÉTERMINISTE aux séries INSEE / DARES
                          │   └──► recherche web     (Claude + web_search) si hors référentiel
                          │
                     db.py (SQLite) ──► /politicians : profils de fiabilité
```

Principe clé : **c'est le code qui tranche sur les chiffres, pas le LLM.** Le LLM extrait, normalise et rédige ; la comparaison est déterministe, reproductible et sourcée.

## Documentation

| Document | Contenu |
|---|---|
| [AGENTS.md](AGENTS.md) | Règles, carte du repo, commandes, état d'avancement (à lire en premier) |
| [docs/HACKATHON_PLAN.md](docs/HACKATHON_PLAN.md) | Planning sur 3 h, répartition de l'équipe |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Flux de données, API, choix techniques |
| [docs/DATA_CONTRACT.md](docs/DATA_CONTRACT.md) | Format d'une affirmation et d'un verdict (contrat gelé) |
| [docs/METHODOLOGIE.md](docs/METHODOLOGIE.md) | Échelle des verdicts, tolérances, neutralité, éthique |
| [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md) | Séries officielles utilisées, et comment en ajouter |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Live, autres thèmes, autres médias, détection de contradictions |
| [docs/lots/](docs/lots/) | Une spec par lot de travail (A à E) |

## Stack

- **Backend** : Python 3.11+, FastAPI, Pydantic, SQLite, SDK Anthropic.
- **LLM** : `claude-opus-5-5`, avec sorties structurées et outil serveur `web_search`.
- **Extension** : Chrome Manifest V3 en JS natif, panneau latéral (side panel), sans build.
- **Données** : API SDMX de la BDM INSEE (gratuite, sans clé). Les séries sont figées dans `data/referentiel/emploi.json`.
