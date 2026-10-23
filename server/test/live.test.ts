import { test } from "node:test";
import assert from "node:assert/strict";
import { Batcher, resultToSegment } from "../src/live.ts";

test("une phrase finale de Deepgram devient un segment horodaté, avec l'intervenant majoritaire", () => {
  const msg = {
    type: "Results", is_final: true, start: 12.34,
    channel: { alternatives: [{ transcript: "Le chômage est à 8 %.", words: [{ speaker: 1 }, { speaker: 1 }, { speaker: 0 }] }] },
  };
  assert.deepEqual(resultToSegment(msg, 100), { text: "Le chômage est à 8 %.", start: 112.3, speaker: "1" });
  assert.equal(resultToSegment({ ...msg, is_final: false }), undefined); // résultat provisoire ignoré
  assert.equal(resultToSegment({ ...msg, channel: { alternatives: [{ transcript: " " }] } }), undefined);
});

test("un passage part à l'analyse après ~700 caractères, ou après 60 s s'il y a assez de texte", () => {
  const b = new Batcher();
  b.add({ text: "a".repeat(300) });
  assert.equal(b.ready(), false);
  b.add({ text: "b".repeat(450) });
  assert.equal(b.ready(), true);
  assert.equal(b.take().length, 2);
  assert.equal(b.ready(), false);
  b.add({ text: "c".repeat(100) });
  assert.equal(b.ready(Date.now() + 61_000), true);
});
