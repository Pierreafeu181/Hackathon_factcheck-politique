import { readFileSync } from "node:fs";
import { serve } from "@hono/node-server";
import { type Context, Hono } from "hono";
import type { ChatRequest, CheckRequest, Segment } from "../../shared/contract.ts";
import { CheckCache } from "./cache.ts";
import { chat, check } from "./checker.ts";
import { mergeSegments, transcribeAudio } from "./deepgram.ts";
import type { Feed } from "./rss.ts";
import { Watcher } from "./watcher.ts";
import { downloadAudio, mediaUrl, YOUTUBE_ID } from "./media-audio.ts";

try {
  process.loadEnvFile(new URL("../.env", import.meta.url));
} catch {
  // Pas de .env : on garde les valeurs par défaut.
}

const port = Number(process.env.PORT ?? 8790);
const feeds: Feed[] = JSON.parse(readFileSync(new URL("../feeds.json", import.meta.url), "utf8"));

const watcher = new Watcher({
  feeds,
  statePath: new URL("../data/state.json", import.meta.url).pathname,
  deepgramKey: process.env.DEEPGRAM_API_KEY || undefined,
  deepgramModel: process.env.DEEPGRAM_MODEL || "nova-3",
  maxPerFeed: Number(process.env.MAX_EPISODES_PER_FEED ?? 1),
});

const app = new Hono();
// Pas de CORS : l'extension a les droits d'accès au serveur, les sites web non.
// Exiger du JSON force une requête de vérification préalable (CORS) qu'un site web ne peut pas passer :
// sans ça, une page pourrait poster du texte brut vers localhost et empoisonner le cache.
// On refuse aussi tout Host autre que localhost (DNS rebinding) et toute origine qui n'est pas une extension.
const allowedHosts = new Set([`localhost:${port}`, `127.0.0.1:${port}`, `[::1]:${port}`]);
app.use("/api/*", async (c, next) => {
  const origin = c.req.header("origin");
  if (!allowedHosts.has(c.req.header("host") ?? "") || (origin && !origin.startsWith("chrome-extension://"))) {
    return c.json({ error: "Accès réservé à l'extension." }, 403);
  }
  if (c.req.method === "POST" && !c.req.header("content-type")?.startsWith("application/json")) {
    return c.json({ error: "Content-Type application/json requis." }, 415);
  }
  await next();
});

app.get("/api/health", (c) => c.json({ ok: true, checker: process.env.CHECKER_URL ? "équipe" : "démo" }));

const cache = new CheckCache(new URL("../data/check-cache.json", import.meta.url).pathname);

/** `?force=1` ignore le cache (ex. après correction de l'orateur). */
app.post("/api/check", async (c) => {
  const req = await c.req.json<CheckRequest>();
  if (!req?.segments?.length) return c.json({ error: "Aucun texte à analyser." }, 400);
  try {
    return c.json(await cache.get(req, () => check(req), c.req.query("force") === "1"));
  } catch (err) {
    return c.json({ error: (err as Error).message }, 502);
  }
});

app.post("/api/chat", async (c) => {
  const req = await c.req.json<ChatRequest>();
  if (!req?.messages?.length) return c.json({ error: "Aucune question." }, 400);
  try {
    return c.json(await chat(req));
  } catch (err) {
    return c.json({ error: (err as Error).message }, 502);
  }
});

/**
 * Vidéo sans texte lisible dans la page (YouTube sans sous-titres, TikTok, Instagram, X, Facebook…) :
 * yt-dlp télécharge l'audio, Deepgram le transcrit. Une transcription à la fois (crédit Deepgram),
 * résultats gardés en mémoire. `{ videoId }` reste accepté pour YouTube.
 */
const transcripts = new Map<string, Segment[]>();
let transcribing: Promise<unknown> = Promise.resolve();
const transcribe = async (c: Context) => {
  const body = await c.req.json<{ url?: string; videoId?: string }>();
  let url: string;
  try {
    if (body.videoId && !YOUTUBE_ID.test(body.videoId)) throw new Error("Identifiant de vidéo YouTube invalide.");
    url = mediaUrl(body.videoId ? `https://www.youtube.com/watch?v=${body.videoId}` : body.url ?? "");
  } catch (err) {
    return c.json({ error: (err as Error).message }, 400);
  }
  const key = process.env.DEEPGRAM_API_KEY;
  if (!key) return c.json({ error: "La transcription audio n'est pas activée (DEEPGRAM_API_KEY manquante dans server/.env)." }, 503);
  const cached = transcripts.get(url);
  if (cached) return c.json({ segments: cached });
  const job = transcribing.then(async () => {
    const { audio, contentType } = await downloadAudio(url);
    return mergeSegments(await transcribeAudio(audio, contentType, key, process.env.DEEPGRAM_MODEL || "nova-3"));
  });
  transcribing = job.catch(() => undefined);
  try {
    const segments = await job;
    if (!segments.length) return c.json({ error: "Deepgram n'a reconnu aucune parole dans cette vidéo." }, 422);
    if (transcripts.size >= 50) transcripts.delete(transcripts.keys().next().value!);
    transcripts.set(url, segments);
    return c.json({ segments });
  } catch (err) {
    return c.json({ error: (err as Error).message }, 502);
  }
};
app.post("/api/transcribe", transcribe);
app.post("/api/transcribe-youtube", transcribe);

app.get("/api/watch", (c) => c.json(watcher.snapshot()));

app.post("/api/watch/refresh", (c) => {
  void watcher.poll();
  return c.json({ ok: true });
});

serve({ fetch: app.fetch, port, hostname: process.env.HOST ?? "127.0.0.1" }, () => {
  console.log(`Serveur prêt sur http://localhost:${port}`);
  console.log(`Analyse : ${process.env.CHECKER_URL ? process.env.CHECKER_URL : "moteur de démo"}`);
  console.log(`Transcription Deepgram : ${process.env.DEEPGRAM_API_KEY ? "activée" : "désactivée (pas de DEEPGRAM_API_KEY)"}`);
  watcher.start(Number(process.env.POLL_MINUTES ?? 15));
});
