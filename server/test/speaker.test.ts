import { test } from "node:test";
import assert from "node:assert/strict";
import { guessFromTitle } from "../../extension/src/speaker.ts";

test("l'orateur est deviné depuis les titres courants des chaînes politiques", () => {
  assert.equal(guessFromTitle("Michel Barnier : « Il faut rétablir l’ordre et l’autorité »"), "Michel Barnier");
  assert.equal(guessFromTitle("Face à Face : Manuel Bompard - 22/10"), "Manuel Bompard");
  assert.equal(guessFromTitle("🔴 Réunion à Matignon, suites du 17 octobre : Manuel Bompard, invité de BFMTV !"), "Manuel Bompard");
  assert.equal(guessFromTitle("L'invité politique Sud Radio - Jean-Didier Berger, Ministre délégué"), "Jean-Didier Berger");
});

test("pas de nom inventé quand le titre n'en contient pas", () => {
  assert.equal(guessFromTitle("La Corse sera-t-elle bientôt autonome ?"), undefined);
  assert.equal(guessFromTitle("Les mathématiciens désemparés face aux progrès de l'IA"), undefined);
});
