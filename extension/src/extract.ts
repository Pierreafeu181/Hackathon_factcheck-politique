// Injecté dans l'onglet à analyser. Expose `__verifpolExtract()` qui renvoie le texte de la page
// (article) ou la transcription horodatée (YouTube), au format du contrat.

import { Readability } from "@mozilla/readability";
import type { CheckRequest, Segment } from "../../shared/contract.ts";

export type ExtractResult = { ok: true; request: CheckRequest } | { ok: false; error: string };

const MAX_CHARS = 30_000;
const CHUNK_CHARS = 400;

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

async function extract(): Promise<ExtractResult> {
  try {
    const url = location.href;
    const title = document.title;
    if (location.hostname.endsWith("youtube.com") && location.pathname === "/watch") {
      return { ok: true, request: { source: { kind: "youtube", url, title }, segments: await youtubeSegments() } };
    }
    return { ok: true, request: { source: { kind: "article", url, title }, segments: articleSegments() } };
  } catch (err) {
    return { ok: false, error: (err as Error).message };
  }
}

// --- Articles ------------------------------------------------------------------

function articleSegments(): Segment[] {
  const article = new Readability(document.cloneNode(true) as Document).parse();
  let paragraphs: string[] = [];
  if (article?.content) {
    const doc = new DOMParser().parseFromString(article.content, "text/html");
    paragraphs = [...doc.querySelectorAll("p, li, h1, h2, h3, blockquote")].map((el) => clean(el.textContent));
  }
  if (!paragraphs.some(Boolean)) paragraphs = document.body.innerText.split("\n").map(clean);
  return capLength(paragraphs.filter((p) => p.length > 30).map((text) => ({ text })));
}

// --- YouTube -------------------------------------------------------------------

async function youtubeSegments(): Promise<Segment[]> {
  const videoId = new URLSearchParams(location.search).get("v");
  const g = globalThis as { __verifpolTranscriptFor?: string | null };
  let lines = g.__verifpolTranscriptFor === videoId ? readTranscript() : [];
  if (!lines.length) {
    // La transcription n'est chargée qu'à l'ouverture du panneau « Afficher la transcription ».
    // Juste après une navigation, YouTube n'a pas encore affiché la nouvelle description, et le panneau
    // peut encore montrer la vidéo précédente : on réessaie d'ouvrir toutes les 3 s, 20 s au total.
    const before = readTranscript()[0]?.text;
    let sawButton = false;
    for (let i = 0; i < 40 && !lines.length; i++) {
      const panelOpen = [...document.querySelectorAll("ytd-engagement-panel-section-list-renderer")].some((p) =>
        /transcript/i.test(p.getAttribute("target-id") ?? "") && p.getAttribute("visibility") === "ENGAGEMENT_PANEL_VISIBILITY_EXPANDED");
      if (i % 6 === 0 && !panelOpen) {
        document.querySelector<HTMLElement>("#description-inline-expander #expand, ytd-text-inline-expander #expand")?.click();
        const button = document.querySelector<HTMLElement>("ytd-video-description-transcript-section-renderer button");
        if (button) {
          sawButton = true;
          button.click();
        }
      }
      await sleep(500);
      const found = readTranscript();
      if (found.length && found[0].text !== before) lines = found;
    }
    if (!sawButton) throw new Error("Cette vidéo n'a pas de transcription : je ne peux pas la vérifier automatiquement. Vous pouvez quand même me poser vos questions.");
    g.__verifpolTranscriptFor = videoId;
  }
  if (!lines.length) throw new Error("La transcription YouTube n'a pas pu être lue.");
  return capLength(mergeLines(lines));
}

/** Lit les lignes du panneau de transcription (nouvelle et ancienne mise en page de YouTube). */
function readTranscript(): Segment[] {
  const modern = [...document.querySelectorAll("transcript-segment-view-model")].map((el) => ({
    start: parseTimestamp(el.querySelector(".ytwTranscriptSegmentViewModelTimestamp")?.textContent),
    text: clean(el.querySelector("[role=text], .ytAttributedStringHost")?.textContent),
  }));
  const legacy = [...document.querySelectorAll("ytd-transcript-segment-renderer")].map((el) => ({
    start: parseTimestamp(el.querySelector(".segment-timestamp")?.textContent),
    text: clean(el.querySelector(".segment-text")?.textContent),
  }));
  return (modern.length ? modern : legacy).filter((l) => l.text);
}

/** Regroupe les lignes courtes des sous-titres en blocs de quelques phrases, horodatés au début du bloc. */
function mergeLines(lines: Segment[]): Segment[] {
  const out: Segment[] = [];
  for (const line of lines) {
    const last = out.at(-1);
    if (last && last.text.length < CHUNK_CHARS) last.text += " " + line.text;
    else out.push({ ...line });
  }
  return out;
}

function parseTimestamp(raw: string | null | undefined): number | undefined {
  if (!raw) return undefined;
  const parts = raw.trim().split(":").map(Number);
  if (parts.some(Number.isNaN)) return undefined;
  return parts.reduce((acc, n) => acc * 60 + n, 0);
}

// --- Commun --------------------------------------------------------------------

function clean(s: string | null | undefined): string {
  return (s ?? "").replace(/\s+/g, " ").trim();
}

function capLength(segments: Segment[]): Segment[] {
  let total = 0;
  return segments.filter((s) => (total += s.text.length) <= MAX_CHARS);
}

(globalThis as any).__verifpolExtract = extract;
