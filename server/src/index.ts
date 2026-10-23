import { createHash, timingSafeEqual } from "node:crypto";
import { readFileSync } from "node:fs";
import { serve } from "@hono/node-server";
import { type Context, Hono } from "hono";
import type { ChatRequest, CheckRequest, Segment } from "../../shared/contract.ts";
import { CheckCache } from "./cache.ts";
import { chat, check } from "./checker.ts";
import { mergeSegments, transcribeAudio } from "./deepgram.ts";
import type { Feed } from "./rss.ts";
import { attachLive } from "./live.ts";
import { clientIp, DailyLimiter } from "./ratelimit.ts";
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
// On refuse toute origine qui n'est pas une extension.
// En local : seulement le Host localhost (contre le DNS rebinding).
// Hébergé (API_TOKEN défini) : n'importe quel Host, mais chaque requête doit porter la clé d'accès,
// en en-tête X-VerifPol-Token, ou dans Sec-WebSocket-Protocol pour le direct (« verifpol, <clé> ») :
// un navigateur ne peut pas poser d'autre en-tête sur un WebSocket, et une clé dans l'URL finirait dans les journaux.
// Accès public (PUBLIC_ACCESS=1) : pas de clé, mais des quotas journaliers par IP et au total ; la clé API_TOKEN,
// si elle est fournie, sert alors de clé d'administration (sans quotas, ex. pré-analyse de la démo).
const allowedHosts = new Set([`localhost:${port}`, `127.0.0.1:${port}`, `[::1]:${port}`]);
const apiToken = process.env.API_TOKEN ?? "";
// Empreintes SHA-256 de longueur fixe : timingSafeEqual lève une erreur sur des longueurs différentes.
const digest = (v: string) => createHash("sha256").update(v).digest();
const tokenOk = (given: string | null | undefined) => !!given && !!apiToken && timingSafeEqual(digest(given), digest(apiToken));
const publicAccess = process.env.PUBLIC_ACCESS === "1";
const accessOk = (host: string | undefined, origin: string | undefined, token: string | null | undefined) =>
  (!origin || origin.startsWith("chrome-extension://")) &&
  (tokenOk(token) || publicAccess || (!apiToken && allowedHosts.has(host ?? "")));
/** Quotas de l'accès public, réglables : LIMIT_CHECKS=40/400 (par IP / au total, par jour). */
const limiter = (name: string, perIp: number, total: number) => {
  const [a, b] = (process.env[`LIMIT_${name}`] ?? "").split("/").map(Number);
  return new DailyLimiter(a || perIp, b || total);
};
const limits = { check: limiter("CHECKS", 40, 400), chat: limiter("CHATS", 100, 1000),
  transcribe: limiter("TRANSCRIBE", 10, 100), live: limiter("LIVE", 5, 30) };
/** true si la requête peut passer : admin (clé valide), accès local, ou quota public disponible. */
const withinQuota = (kind: keyof typeof limits, token: string | null | undefined, ip: string) =>
  !publicAccess || tokenOk(token) || limits[kind].take(ip);
const quotaError = { error: "Limite d'utilisation du jour atteinte pour ce service gratuit. Réessayez demain." };
const ipOf = (c: Context) => {
  const incoming = (c.env as { incoming?: { socket?: { remoteAddress?: string } } } | undefined)?.incoming;
  return clientIp(c.req.header("x-forwarded-for"), incoming?.socket?.remoteAddress);
};
let xffLogs = 0;
app.use("/api/*", async (c, next) => {
  if (publicAccess && xffLogs < 5) { // diagnostic : nombre de proxys devant l'app (jamais les adresses)
    xffLogs++;
    console.log(`[proxy] X-Forwarded-For : ${(c.req.header("x-forwarded-for") ?? "").split(",").filter(Boolean).length} élément(s)`);
  }
  if (c.req.path === "/api/health" && c.req.method === "GET") return next(); // sonde de l'hébergeur
  if (!accessOk(c.req.header("host"), c.req.header("origin"), c.req.header("x-verifpol-token"))) {
    return c.json({ error: apiToken && !publicAccess ? "Clé d'accès manquante ou invalide (Réglages du panneau)." : "Accès réservé à l'extension." }, 403);
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
    const token = c.req.header("x-verifpol-token"), ip = ipOf(c);
    let overQuota = false;
    const res = await cache.get(req, async () => {
      if (!withinQuota("check", token, ip)) {
        overQuota = true;
        return { claims: [], demo: true }; // non mis en cache (demo)
      }
      return check(req);
    }, c.req.query("force") === "1" && (!publicAccess || tokenOk(token)), // ?force=1 réservé à l'admin en public
    !publicAccess || tokenOk(token)); // seules les analyses de confiance servent pour toute la vidéo
    return overQuota ? c.json(quotaError, 429) : c.json(res);
  } catch (err) {
    return c.json({ error: (err as Error).message }, 502);
  }
});

app.post("/api/chat", async (c) => {
  const req = await c.req.json<ChatRequest>();
  if (!req?.messages?.length) return c.json({ error: "Aucune question." }, 400);
  if (!withinQuota("chat", c.req.header("x-verifpol-token"), ipOf(c))) return c.json(quotaError, 429);
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
  if (!withinQuota("transcribe", c.req.header("x-verifpol-token"), ipOf(c))) return c.json(quotaError, 429);
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

/** Profils (lecture seule) : relayés vers le moteur Python, à côté de CHECKER_URL. */
const engine = (path: string) => process.env.CHECKER_URL ? new URL(path, process.env.CHECKER_URL).href : "";
const relay = async (c: Context, path: string) => {
  const url = engine(path);
  if (!url) return c.json([], 200); // moteur de démo : pas de profils
  try {
    const res = await fetch(url);
    return c.json(await res.json(), res.ok ? 200 : 502);
  } catch (err) {
    return c.json({ error: (err as Error).message }, 502);
  }
};
const SLUG = /^[a-z0-9-]{1,120}$/;
app.get("/api/politicians", (c) => relay(c, "/politicians"));
app.get("/api/politicians/:id/claims", async (c) => {
  if (!SLUG.test(c.req.param("id"))) return c.json({ error: "Identifiant invalide." }, 400);
  return relay(c, `/politicians/${c.req.param("id")}/claims`);
});

app.get("/api/watch", (c) => c.json(watcher.snapshot()));

app.post("/api/watch/refresh", (c) => {
  void watcher.poll();
  return c.json({ ok: true });
});

const server = serve({ fetch: app.fetch, port, hostname: process.env.HOST ?? "127.0.0.1" }, () => {
  console.log(`Serveur prêt sur http://localhost:${port}`);
  console.log(`Analyse : ${process.env.CHECKER_URL ? process.env.CHECKER_URL : "moteur de démo"}`);
  console.log(`Transcription Deepgram : ${process.env.DEEPGRAM_API_KEY ? "activée" : "désactivée (pas de DEEPGRAM_API_KEY)"}`);
  watcher.start(Number(process.env.POLL_MINUTES ?? 15));
});

// Direct : WebSocket /api/live, mêmes garde-fous que l'API (Host localhost, origine = l'extension).
attachLive(server, {
  deepgramKey: process.env.DEEPGRAM_API_KEY || undefined,
  model: process.env.DEEPGRAM_MODEL || "nova-3",
  check,
  allowed: (req) => {
    const token = (req.headers["sec-websocket-protocol"] ?? "").split(",").map((p) => p.trim())[1];
    const forwarded = req.headers["x-forwarded-for"];
    const ip = clientIp(Array.isArray(forwarded) ? forwarded[0] : forwarded, req.socket.remoteAddress);
    return (req.headers.origin ?? "").startsWith("chrome-extension://") &&
      accessOk(req.headers.host, req.headers.origin, token) && withinQuota("live", token, ip);
  },
  // Accès public : chaque passage vérifié en direct compte comme une analyse, et la session est limitée à 30 min.
  sessionPolicy: (req) => {
    const token = (req.headers["sec-websocket-protocol"] ?? "").split(",").map((p) => p.trim())[1];
    const forwarded = req.headers["x-forwarded-for"];
    const ip = clientIp(Array.isArray(forwarded) ? forwarded[0] : forwarded, req.socket.remoteAddress);
    const limited = publicAccess && !tokenOk(token);
    return { maxMs: limited ? 30 * 60_000 : 2 * 3600_000, allowCheck: () => !limited || limits.check.take(ip) };
  },
});
