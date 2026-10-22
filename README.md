# Vérif'Pol

Vérification des affirmations des responsables politiques français, sources officielles à l'appui.

- **`extension/`** : extension Chrome (panneau latéral). Vérifie l'article ou la vidéo YouTube ouverte, ou une phrase sélectionnée (clic droit).
- **`server/`** : serveur Node. Reçoit les demandes de l'extension, les transmet au moteur d'analyse, et fait la **veille RSS** (podcasts transcrits par Deepgram, vidéos YouTube listées).
- **`shared/contract.ts`** : le format d'échange entre les trois parties. À modifier seulement en équipe.

## Lancer

```bash
npm install
cp server/.env.example server/.env   # ajouter DEEPGRAM_API_KEY pour la transcription
npm run dev:server                   # http://localhost:8790
npm run build:ext                    # ou npm run watch:ext
```

Puis dans Chrome : `chrome://extensions` → mode développeur → « Charger l'extension non empaquetée » → dossier `extension/dist`. Cliquer sur l'icône Vérif'Pol ouvre le panneau.

Tests : `npm test`.

## Brancher le moteur d'analyse

Tant que `CHECKER_URL` est vide, le serveur répond avec un **faux moteur de démo** : il garde les phrases chiffrées et invente un verdict stable, marqué « [Démo] ».

Pour brancher le vrai moteur : exposer un endpoint qui reçoit un `CheckRequest` en POST et renvoie un `CheckResponse` (voir `shared/contract.ts`), puis mettre son URL dans `CHECKER_URL`.

```jsonc
// CheckRequest
{ "source": { "kind": "youtube", "url": "…", "title": "…" },
  "segments": [{ "text": "Le chômage est à 7 %…", "start": 801, "speaker": "1" }] }

// CheckResponse
{ "claims": [{ "id": "1", "quote": "Le chômage est à 7 %", "verdict": "faux",
               "explanation": "…", "start": 801,
               "sources": [{ "label": "INSEE – Taux de chômage", "url": "https://…", "official": true }] }] }
```

`verdict` vaut `vrai`, `trompeur`, `faux` ou `invérifiable`. `start` (en secondes) permet de sauter au bon moment de la vidéo.

## Veille RSS

Les flux suivis sont dans `server/feeds.json` (RMC Face à Face, l'invité RTL de 7h40, l'invité politique Sud Radio, Public Sénat et franceinfo sur YouTube).

- **Podcasts** : le lien MP3 du flux est envoyé à Deepgram (Nova-3, français, séparation des voix). On ne garde que les phrases de l'intervenant qui parle le plus (l'invité), puis on les envoie à l'analyse.
- **YouTube** : un serveur ne peut pas récupérer les sous-titres (YouTube bloque). Les vidéos sont listées dans l'onglet « Veille » avec un bouton « Ouvrir et vérifier » : l'extension lit alors la transcription dans le navigateur.

Au premier lancement, seul le dernier épisode de chaque flux est traité (`MAX_EPISODES_PER_FEED`) pour ne pas transcrire tout l'historique. L'état est gardé dans `server/data/state.json`.

## Sources de données

- **INSEE, API BDM** : `https://api.insee.fr/series/BDM/V1/…`, sans clé, 30 appels/min/IP, format SDMX (XML). Exemple : `/data/SERIES_BDM/001688527?lastNObservations=1` (taux de chômage BIT).
