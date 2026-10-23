#!/usr/bin/env bash
# Lance le moteur Python (interne) et le serveur Node (public). Si l'un s'arrête, le conteneur s'arrête
# et l'hébergeur le relance.
set -m
if [ -z "$API_TOKEN" ]; then echo "API_TOKEN manquant : refus de démarrer un serveur public sans clé d'accès." >&2; exit 1; fi
(cd /app/backend && exec uvicorn app.main:app --host 127.0.0.1 --port 8000) &
(cd /app/server && exec /app/node_modules/.bin/tsx src/index.ts) &
wait -n
exit 1
