# Lot A — Extension Chrome

**Fichiers possédés** : `extension/**`
**Objectif démo** : sur une vidéo YouTube, un clic ouvre le panneau, on lance l'analyse, puis des cartes colorées apparaissent. Cliquer sur l'horodatage renvoie la vidéo au bon moment.

## État actuel (fonctionnel)
- `manifest.json` (MV3, side panel), `background.js` (le clic sur l'icône ouvre le panneau).
- `content.js` : lit `videoId`, le titre et la chaîne ; `seek(t)` ; lit le panneau « Transcription » du DOM (plan B).
- `sidepanel.*` : formulaire orateur / parti / date, appel `POST /analyze`, rendu des cartes (badge, citation, explication, correction, sources, méthode, confiance), chargement auto du cache `GET /videos/{id}/claims`, onglet **Profils** (`GET /politicians`).

## Tâches, par priorité
1. **[P0] Tester en vrai** sur 2-3 vidéos et corriger les sélecteurs DOM YouTube si besoin (`h1.ytd-watch-metadata`, `ytd-channel-name a`, `ytd-transcript-segment-renderer .segment-text`). YouTube change souvent son DOM.
2. **[P0] Navigation SPA** : YouTube ne recharge pas la page entre deux vidéos. Vérifier que `refreshVideo()` se déclenche (`chrome.tabs.onUpdated` sur `url`). Sinon, écouter l'événement `yt-navigate-finish` dans `content.js` et notifier le panneau.
3. **[P1] Mémoriser l'orateur par chaîne** (`chrome.storage.local`) pour ne pas le retaper.
4. **[P1] Filtre par verdict** (cliquer sur un badge de `#stats` filtre les cartes) et tri par horodatage ou par gravité.
5. **[P1] Lien carte → profil** : clic sur le nom de l'orateur, puis onglet Profils centré sur lui.
6. **[P2] Surlignage pendant la lecture** : `content.js` envoie `currentTime` toutes les 2 s ; la carte en cours est mise en évidence. C'est l'amorce du « live ».
7. **[P2] Petit badge en surimpression sur la vidéo** au moment d'une affirmation (injection DOM dans `#movie_player`).

## Critères de fin
- Démo sans erreur console sur 2 vidéos différentes, enchaînées sans recharger l'onglet.
- Le plan B (transcript DOM) fonctionne quand le backend renvoie 422.

## Prompt de démarrage pour ton agent
> Lis AGENTS.md puis docs/lots/LOT-A-extension.md. Tu travailles uniquement dans `extension/`. Commence par la tâche P0 n°2 (navigation SPA YouTube), puis la n°3. Pas de framework ni de build : JS natif. Respecte le contrat (docs/DATA_CONTRACT.md) pour lire les réponses de l'API.
