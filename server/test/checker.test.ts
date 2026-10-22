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
