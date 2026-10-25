import { test } from "node:test";
import assert from "node:assert/strict";
import { demoCheck } from "../src/checker.ts";

test("le moteur de démo ne garde que les phrases chiffrées et conserve l'horodatage", () => {
  const res = demoCheck({
    source: { kind: "youtube", url: "https://www.youtube.com/watch?v=x" },
    segments: [
      { text: "Bonjour à tous.", start: 0 },
      { text: "Le chômage est passé sous les 7 % en 2025. Merci de m'avoir invité.", start: 42 },
    ],
  });
  assert.equal(res.demo, true);
  assert.equal(res.claims.length, 1);
  assert.equal(res.claims[0].quote, "Le chômage est passé sous les 7 % en 2025.");
  assert.equal(res.claims[0].start, 42);
  assert.ok(res.claims[0].sources.some((s) => s.official && s.url.includes("insee.fr")));
});

test("le moteur de démo renvoie toujours le même verdict pour la même phrase", () => {
  const req = { source: { kind: "article" as const, url: "u" }, segments: [{ text: "La dette atteint 3 300 milliards d'euros." }] };
  assert.equal(demoCheck(req).claims[0].verdict, demoCheck(req).claims[0].verdict);
});

test("postJson : attend au-delà du délai de fetch, abandonne après le délai demandé", async () => {
  const { createServer } = await import("node:http");
  const { postJson } = await import("../src/checker.ts");
  const server = createServer((req, res) => {
    const delay = req.url === "/lent" ? 400 : 50;
    setTimeout(() => { res.writeHead(200, { "Content-Type": "application/json" }); res.end('{"ok":true}'); }, delay);
  });
  await new Promise<void>((r) => server.listen(0, "127.0.0.1", r));
  const { port } = server.address() as { port: number };
  try {
    const ok = await postJson(`http://127.0.0.1:${port}/rapide`, { x: 1 }, 1000);
    assert.equal(ok.status, 200);
    assert.deepEqual(JSON.parse(ok.text), { ok: true });
    await assert.rejects(postJson(`http://127.0.0.1:${port}/lent`, { x: 1 }, 100), /délai dépassé/);
  } finally {
    server.closeAllConnections();
    server.close();
  }
});

test("engineError : message du moteur relayé (quota du jour), code HTTP sinon", async () => {
  const { engineError } = await import("../src/checker.ts");
  assert.equal(engineError("Moteur", { status: 503, text: '{"detail":"Quota du jour épuisé"}' }), "Quota du jour épuisé");
  assert.equal(engineError("Moteur", { status: 500, text: "Internal Server Error" }), "Moteur : HTTP 500");
});
