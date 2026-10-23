#!/usr/bin/env bash
# Lance le moteur Python (interne) et le serveur Node (public). Si l'un s'arrête, le conteneur s'arrête
# et l'hébergeur le relance.
set -m
# Serveur public : soit une clé d'accès (API_TOKEN), soit l'accès libre avec quotas (PUBLIC_ACCESS=1).
if [ -z "$API_TOKEN" ] && [ "$PUBLIC_ACCESS" != "1" ]; then
  echo "Ni API_TOKEN ni PUBLIC_ACCESS=1 : refus de démarrer un serveur public sans protection." >&2; exit 1
fi
(cd /app/backend && exec uvicorn app.main:app --host 127.0.0.1 --port 8000) &
(cd /app/server && exec /app/node_modules/.bin/tsx src/index.ts) &
wait -n
exit 1
