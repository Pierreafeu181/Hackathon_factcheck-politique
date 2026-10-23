# Image unique pour l'hébergement : serveur Node (public, port $PORT) + moteur Python (interne, 127.0.0.1:8000)
# + yt-dlp et ffmpeg pour la transcription des vidéos. Voir docs/DEPLOY.md.
FROM node:22-bookworm-slim AS node

FROM python:3.13-slim-bookworm
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt yt-dlp

COPY package.json package-lock.json ./
COPY server/package.json server/package.json
COPY extension/package.json extension/package.json
RUN npm ci -w server --no-audit --no-fund

COPY shared shared
COPY server server
COPY backend backend
COPY data data
COPY db db
COPY deploy/start.sh deploy/start.sh

# Le moteur Python n'écoute que dans le conteneur ; seul le serveur Node est exposé.
ENV HOST=0.0.0.0 PORT=8080 CHECKER_URL=http://127.0.0.1:8000/check PYTHONUNBUFFERED=1
EXPOSE 8080
RUN useradd --create-home app && chown -R app /app
USER app
CMD ["bash", "deploy/start.sh"]
