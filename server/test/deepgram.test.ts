import { test } from "node:test";
import assert from "node:assert/strict";
import { guestSegments, utterancesToSegments } from "../src/deepgram.ts";

test("les phrases Deepgram deviennent des segments horodatés avec l'intervenant", () => {
  const segments = utterancesToSegments({
    results: {
      utterances: [
        { start: 0.5, end: 3, transcript: "Bonjour, vous êtes notre invité.", speaker: 0 },
        { start: 3.2, end: 9, transcript: "Le chômage a baissé de 2 points.", speaker: 1 },
      ],
    },
  });
  assert.deepEqual(segments, [
    { text: "Bonjour, vous êtes notre invité.", start: 0.5, speaker: "0" },
    { text: "Le chômage a baissé de 2 points.", start: 3.2, speaker: "1" },
  ]);
});

test("l'invité est l'intervenant qui parle le plus", () => {
  const segments = [
    { text: "Question courte ?", speaker: "0" },
    { text: "Une très longue réponse de l'invité politique avec beaucoup de chiffres.", speaker: "1" },
    { text: "Relance ?", speaker: "0" },
    { text: "Encore une longue réponse de l'invité.", speaker: "1" },
  ];
  assert.deepEqual(
    guestSegments(segments).map((s) => s.speaker),
    ["1", "1"],
  );
});

test("sans information d'intervenant, on garde tout", () => {
  const segments = [{ text: "a" }, { text: "b" }];
  assert.deepEqual(guestSegments(segments), segments);
});
