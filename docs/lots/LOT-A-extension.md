# Lot A — Extension Chrome + serveur Node

**Fichiers possédés** : `extension/**`, `server/**`, `package.json`
**Objectif démo** : sur une vidéo YouTube ou un article, un clic ouvre le panneau, on lance l'analyse, puis des cartes de verdict apparaissent. Cliquer sur l'horodatage renvoie la vidéo au bon moment. L'onglet Veille montre les derniers épisodes analysés.

## État actuel (branche de Sébastien, fusionnée)
- **Extension TS** (`npm run build:ext` → `extension/dist`) : onglets « Cette page » et « Veille », extraction d'article (Readability) ou de transcript YouTube horodaté (`src/extract.ts`), vérification d'une sélection au clic droit, saut vidéo qui gère les pubs.
- **Serveur Node** (port 8790) : `/api/check` relayé vers `CHECKER_URL` (sinon moteur de démo), `/api/watch` (veille RSS, transcription Deepgram des podcasts).
- **Branchement au moteur Python** : `CHECKER_URL=http://localhost:8000/check` dans `server/.env`.

## Mode chat (branche lot-a-extension)
- Le panneau est un **fil de discussion**. Sur une vidéo YouTube, la vérification part toute seule (onglet actif ou navigation sans rechargement) et arrive comme un message avec les cartes. Sur un article : pastille « Vérifier cette page ». Clic droit sur une sélection : vérifiée dans le fil.
- Titre et chaîne via oEmbed ; orateur·rice deviné depuis le titre (`src/speaker.ts`, testé), sinon la chaîne ; ✎ pour corriger (retenu par chaîne) et revérifier (`/api/check?force=1`).
- Chat : `POST /api/chat` (Node) → `POST /chat` (Python), avec les verdicts affichés en contexte. Bouton « Pourquoi ? » sur chaque carte.
- Node garde les analyses en cache par page et orateur (`server/data/check-cache.json`), sauf les réponses de démo.
- `extract.ts` : après une navigation, rouvre le panneau Transcription jusqu'à lire la nouvelle vidéo (20 s max).

## Tâches, par priorité
1. **[P0] Bout en bout** : backend Python avec une clé Anthropic, `CHECKER_URL` renseigné, extension chargée. Tester sur 2 vidéos et 1 article. Le temps d'analyse est de 30 s à 2 min : vérifier que le `fetch` de `server/src/checker.ts` ne coupe pas avant, et sinon augmenter le délai ou afficher une progression.
2. **[P0] Nom de l'orateur** : le contrat ne le transporte pas, donc rien n'est stocké pour les profils. Proposer en équipe d'ajouter `politician?: { name: string; party?: string }` et `date?: string` à `CheckRequest`, champs que le Python accepte déjà, puis un champ « Orateur » dans le panneau (pré-rempli avec la chaîne YouTube).
3. **[P1] Onglet Profils** : appeler `GET http://localhost:8000/politicians` via le serveur Node (ajouter un relais `/api/politicians`) et afficher le score, le nombre d'affirmations et la répartition des verdicts. L'ancienne extension JS natif faisait ça : voir l'historique git, `extension/sidepanel.js` au commit `e6c92ba`.
4. **[P1] Correction mise en avant** : le moteur Python ajoute « Correction : … » à la fin de `explanation`. L'afficher dans un encadré distinct (découper sur « Correction : »).
5. **[P2] Surlignage pendant la lecture** de la carte en cours, puis badge en surimpression sur la vidéo : c'est l'amorce du live.

## Critères de fin
- Démo sans erreur console sur 2 vidéos enchaînées et 1 article, avec les verdicts du moteur Python (pas « [Démo] »).
- `npm test` passe.

## Prompt de démarrage pour ton agent
> Lis AGENTS.md puis docs/lots/LOT-A-extension.md. Lance le backend Python (port 8000) et le serveur Node avec CHECKER_URL=http://localhost:8000/check. Commence par la tâche P0 n°1 : vérifie le délai d'attente dans server/src/checker.ts et l'affichage de la progression dans extension/src/sidepanel.ts. Respecte shared/contract.ts.
