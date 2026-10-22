import { test } from "node:test";
import assert from "node:assert/strict";
import { guestSegments, mergeSegments, utterancesToSegments } from "../src/deepgram.ts";
import { downloadAudio, mediaUrl, YOUTUBE_ID } from "../src/media-audio.ts";

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

test("les phrases d'un même intervenant sont regroupées en blocs, et la longueur totale est plafonnée", () => {
  const segments = [
    { text: "a".repeat(100), start: 0, speaker: "0" },
    { text: "b".repeat(100), start: 5, speaker: "0" },
    { text: "c".repeat(100), start: 9, speaker: "1" },
    { text: "d".repeat(100), start: 12, speaker: "1" },
  ];
  const merged = mergeSegments(segments, 150, 1000);
  assert.deepEqual(merged.map((s) => [s.start, s.speaker, s.text.length]), [[0, "0", 201], [9, "1", 201]]);
  assert.deepEqual(mergeSegments(segments, 150, 250).map((s) => s.text.length), [201]); // 3e et 4e phrases coupées
  assert.equal(segments[0].text.length, 100); // pas de mutation de l'entrée
});

test("seules les adresses web publiques sont passées à yt-dlp", async () => {
  assert.ok(YOUTUBE_ID.test("J43DDa090TI"));
  assert.ok(!YOUTUBE_ID.test("--exec=rm -rf"));
  assert.equal(mediaUrl("https://www.tiktok.com/@a/video/123#x"), "https://www.tiktok.com/@a/video/123");
  for (const bad of ["file:///etc/passwd", "http://localhost:8000/check", "http://192.168.1.1/", "http://[::1]/", "--exec=ls", "http://nas.local/v"]) {
    assert.throws(() => mediaUrl(bad), /invalide|non autorisée/, bad);
  }
  await assert.rejects(downloadAudio("http://127.0.0.1/x"), /non autorisée/);
});
