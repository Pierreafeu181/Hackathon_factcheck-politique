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

test("une même vidéo avec le même orateur n'est analysée qu'une fois", async () => {
  const cache = new CheckCache(join(mkdtempSync(join(tmpdir(), "cache-")), "c.json"));
  let calls = 0;
  const run = async () => (calls++, { claims: [] });
  await cache.get(req("https://youtube.com/watch?v=a", "Barnier"), run);
  await cache.get(req("https://youtube.com/watch?v=a", "Barnier"), run);
  assert.equal(calls, 1);
  await cache.get(req("https://youtube.com/watch?v=a", "Bompard"), run);
  assert.equal(calls, 2);
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
