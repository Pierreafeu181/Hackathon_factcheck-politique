import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { parseFeed } from "../src/rss.ts";

const fixture = (name: string) => readFileSync(new URL(`./fixtures/${name}`, import.meta.url), "utf8");

test("podcast : chaque épisode a un titre, une date et un lien MP3", () => {
  const items = parseFeed(fixture("podcast.xml"), { id: "rtl", name: "RTL", kind: "podcast", url: "" });
  assert.equal(items.length, 2);
  for (const item of items) {
    assert.ok(item.title.length > 0);
    assert.match(item.audioUrl ?? "", /^https:\/\/.+\.mp3/);
    assert.ok(!Number.isNaN(Date.parse(item.publishedAt)));
    assert.ok(item.id.startsWith("rtl:"));
  }
});

test("youtube : chaque vidéo a un lien watch et pas de MP3", () => {
  const items = parseFeed(fixture("youtube.xml"), { id: "ps", name: "Public Sénat", kind: "youtube", url: "" });
  assert.equal(items.length, 2);
  assert.equal(items[0].title, "La Corse sera-t-elle bientôt autonome ?");
  assert.equal(items[0].url, "https://www.youtube.com/watch?v=MAXmELWgC0s");
  assert.equal(items[0].audioUrl, undefined);
  assert.equal(items[0].id, "ps:MAXmELWgC0s");
});

test("les épisodes sont triés du plus récent au plus ancien", () => {
  const items = parseFeed(fixture("podcast.xml"), { id: "rtl", name: "RTL", kind: "podcast", url: "" });
  assert.ok(Date.parse(items[0].publishedAt) >= Date.parse(items[1].publishedAt));
});
