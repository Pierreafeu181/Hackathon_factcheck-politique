import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { CheckCache } from "../src/cache.ts";
import type { CheckRequest } from "../../shared/contract.ts";

const req = (url: string, name?: string): CheckRequest => ({
  source: { kind: "youtube", url },
  segments: [{ text: "x" }],
  ...(name && { politician: { name } }),
});

test("une même vidéo n'est analysée qu'une fois (la correction d'orateur force une nouvelle analyse)", async () => {
  const cache = new CheckCache(join(mkdtempSync(join(tmpdir(), "cache-")), "c.json"));
  let calls = 0;
  const run = async () => (calls++, { claims: [] });
  await cache.get(req("https://youtube.com/watch?v=a", "Barnier"), run);
  await cache.get(req("https://youtube.com/watch?v=a", "Barnier"), run);
  assert.equal(calls, 1);
  await cache.get(req("https://youtube.com/watch?v=a", "Bompard"), run, true);
  assert.equal(calls, 2);
});

test("accès public : un faux transcript n'est jamais resservi aux autres pour la même vidéo", async () => {
  const cache = new CheckCache(join(mkdtempSync(join(tmpdir(), "cache-")), "c.json"));
  const url = "https://youtube.com/watch?v=b";
  const fake = { claims: [{ id: "f", quote: "faux", verdict: "faux" as const, explanation: "x", sources: [] }] };
  await cache.get({ source: { kind: "youtube", url }, segments: [{ text: "texte inventé" }] }, async () => fake, false, false);
  let ran = false;
  const real = await cache.get({ source: { kind: "youtube", url }, segments: [{ text: "vraie transcription" }] },
    async () => { ran = true; return { claims: [] }; }, false, false);
  assert.equal(ran, true);
  assert.deepEqual(real, { claims: [] });
});

test("force relance l'analyse", async () => {
  const cache = new CheckCache(join(mkdtempSync(join(tmpdir(), "cache-")), "c.json"));
  let calls = 0;
  const run = async () => (calls++, { claims: [] });
  await cache.get(req("u"), run);
  await cache.get(req("u"), run, true);
  assert.equal(calls, 2);
});

test("le cache survit à un redémarrage, sauf les réponses de démo", async () => {
  const path = join(mkdtempSync(join(tmpdir(), "cache-")), "c.json");
  await new CheckCache(path).get(req("real"), async () => ({ claims: [] }));
  await new CheckCache(path).get(req("demo"), async () => ({ claims: [], demo: true }));
  let calls = 0;
  const reopened = new CheckCache(path);
  await reopened.get(req("real"), async () => (calls++, { claims: [] }));
  await reopened.get(req("demo"), async () => (calls++, { claims: [] }));
  assert.equal(calls, 1);
});

test("sans orateur, une analyse déjà faite pour la même vidéo est réutilisée", async () => {
  const dir = mkdtempSync(join(tmpdir(), "cache-"));
  const cache = new CheckCache(join(dir, "c.json"));
  const url = "https://www.youtube.com/watch?v=abc";
  const first = await cache.get({ source: { kind: "youtube", url, title: "t" }, segments: [{ text: "x" }], politician: { name: "Jean Dupont" } },
    async () => ({ claims: [{ id: "1", quote: "q", verdict: "vrai", explanation: "e", sources: [] }] }));
  let ran = false;
  const second = await cache.get({ source: { kind: "youtube", url, title: "t" }, segments: [{ text: "x" }] },
    async () => { ran = true; return { claims: [] }; });
  assert.equal(ran, false);
  assert.deepEqual(second, first);
});

import { DailyLimiter, clientIp } from "../src/ratelimit.ts";

test("quota journalier : par client et au total", () => {
  const l = new DailyLimiter(2, 3);
  assert.equal(l.take("a"), true);
  assert.equal(l.take("a"), true);
  assert.equal(l.take("a"), false); // limite du client
  assert.equal(l.take("b"), true);
  assert.equal(l.take("c"), false); // limite globale
  assert.equal(clientIp("1.2.3.4, 203.0.113.5", "10.0.0.1"), "203.0.113.5"); // « 1.2.3.4 » écrit par le client : ignoré
  assert.equal(clientIp("1.2.3.4, 203.0.113.5, 10.0.0.2", "10.0.0.1"), "203.0.113.5"); // proxy interne sauté
  assert.equal(clientIp("203.0.113.5, ::ffff:172.20.0.3, 10.1.2.3", undefined), "203.0.113.5");
  assert.equal(clientIp(undefined, "127.0.0.1"), "127.0.0.1");
});
