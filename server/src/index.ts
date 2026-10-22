import { readFileSync } from "node:fs";
import { serve } from "@hono/node-server";
import { Hono } from "hono";
import { cors } from "hono/cors";
import type { CheckRequest } from "../../shared/contract.ts";
import { check } from "./checker.ts";
import type { Feed } from "./rss.ts";
import { Watcher } from "./watcher.ts";

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
app.use("/api/*", cors());

app.get("/api/health", (c) => c.json({ ok: true, checker: process.env.CHECKER_URL ? "équipe" : "démo" }));

app.post("/api/check", async (c) => {
  const req = await c.req.json<CheckRequest>();
  if (!req?.segments?.length) return c.json({ error: "Aucun texte à analyser." }, 400);
  try {
    return c.json(await check(req));
  } catch (err) {
    return c.json({ error: (err as Error).message }, 502);
  }
});

app.get("/api/watch", (c) => c.json(watcher.snapshot()));

app.post("/api/watch/refresh", (c) => {
  void watcher.poll();
  return c.json({ ok: true });
});

serve({ fetch: app.fetch, port }, () => {
  console.log(`Serveur prêt sur http://localhost:${port}`);
  console.log(`Analyse : ${process.env.CHECKER_URL ? process.env.CHECKER_URL : "moteur de démo"}`);
  console.log(`Transcription Deepgram : ${process.env.DEEPGRAM_API_KEY ? "activée" : "désactivée (pas de DEEPGRAM_API_KEY)"}`);
  watcher.start(Number(process.env.POLL_MINUTES ?? 15));
});
