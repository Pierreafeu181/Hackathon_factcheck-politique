# Héberger Vérif'Pol (sans le Mac)

Une seule image Docker (`Dockerfile` à la racine) : le serveur Node est public sur `$PORT` (8080 par défaut),
le moteur Python n'écoute qu'à l'intérieur du conteneur. La base est Aiven PostgreSQL (`pg-cd8988f`).

## En production

- Service Aiven Runtime **`verifpol`** (projet `factcheck`, `aws-eu-west-1`, plan `startup-20-512`, ~12 $/mois),
  construit depuis la branche **`deploy`** de `sebastiendero/aiven`. Base : intégration avec `pg-cd8988f`.
- Mettre à jour : pousser sur `deploy`, puis relancer le déploiement (console Aiven ou outil `aiven_application_redeploy`).
- Les variables `API_TOKEN`, `GEMINI_API_KEY`, `DEEPGRAM_API_KEY` sont des secrets du service (console Aiven).

## Variables d'environnement

| Variable | Rôle |
|---|---|
| `PUBLIC_ACCESS` | `1` = extension utilisable **sans clé**, avec quotas journaliers par IP et au total (`LIMIT_CHECKS=40/400`, `LIMIT_CHATS=100/1000`, `LIMIT_TRANSCRIBE=10/100`, `LIMIT_LIVE=5/30`). IP lue depuis la droite de `X-Forwarded-For` en sautant les proxys internes |
| `API_TOKEN` | Clé d'accès. Sans `PUBLIC_ACCESS`, obligatoire pour chaque requête ; avec, clé d'administration qui ignore les quotas (pré-analyse de la démo). Le conteneur refuse de démarrer sans l'un ni l'autre. Générer : `openssl rand -hex 24` |
| `GEMINI_API_KEY` | Modèle (offre gratuite Gemini) |
| `DEEPGRAM_API_KEY` | Transcription (podcasts, vidéos sans sous-titres, direct) |
| `DATABASE_URL` | Aiven PostgreSQL. Sur Aiven Applications, l'injecter par une intégration `pg` plutôt qu'en clair |
| `GOOGLE_FACTCHECK_API_KEY`, `PISTE_CLIENT_ID`, `PISTE_CLIENT_SECRET` | Sources facultatives |

## Tester l'image en local

```bash
docker build -t verifpol .
docker run --rm -p 8099:8080 --env-file backend/.env -e DEEPGRAM_API_KEY=… -e API_TOKEN=essai verifpol
curl localhost:8099/api/health
```

## Brancher l'extension

Panneau → **Réglages** (en bas) : **Serveur** = l'URL publique (`https://…`), **Clé d'accès** = `API_TOKEN`.

## Ce qui change une fois hébergé

- **YouTube bloque yt-dlp depuis les serveurs** : les vidéos YouTube *sans sous-titres* ne sont plus transcrites.
  Le reste marche : sous-titres lus par l'extension, articles, direct (le son vient du navigateur), souvent TikTok.
- Les fichiers `server/data/*.json` (cache, veille) repartent de zéro à chaque redéploiement ; les analyses
  avec orateur connu restent dans Aiven.
- La veille RSS tourne en continu : elle consomme du quota Gemini et du crédit Deepgram chaque matin.
