// Panneau latéral en mode chat : la vidéo YouTube ouverte est vérifiée automatiquement,
// le résultat arrive comme un message, et l'utilisateur pose ses questions dessous.

import type {
  ChatRequest, ChatResponse, CheckRequest, CheckResponse, Claim, EpisodeStatus, Segment, Verdict, WatchEpisode, WatchResponse,
} from "../../shared/contract.ts";
import type { ExtractResult } from "./extract.ts";
import { guessFromTitle } from "./speaker.ts";

const DEFAULT_BACKEND = "http://localhost:8790";
const WATCH_REFRESH_MS = 15_000;
const TIME_POLL_MS = 2_000;

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;

interface Page {
  tabId: number;
  url: string;
  kind: "youtube" | "article";
  videoId?: string;
  title: string;
  channel?: string;
  speaker?: string;
  claims: Claim[];
}

let backend = DEFAULT_BACKEND;
let current: Page | undefined;
let detecting: string | undefined; // page en cours de détection (plusieurs événements Chrome par navigation)
let history: ChatRequest["messages"] = [];
let busy = false;
let analyzing = 0; // analyses en cours (le bouton « Analyser » est désactivé pendant ce temps)

// --- Appels au serveur ---------------------------------------------------------

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(backend + path, { ...init, headers: { "Content-Type": "application/json" } });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error ?? `Serveur : HTTP ${res.status}`);
  return body as T;
}

const checkClaims = (req: CheckRequest, force = false) =>
  api<CheckResponse>(`/api/check${force ? "?force=1" : ""}`, { method: "POST", body: JSON.stringify(req) });

// --- Page courante -------------------------------------------------------------

const youtubeId = (url: string) => {
  const u = new URL(url);
  return u.hostname.endsWith("youtube.com") && u.pathname === "/watch" ? u.searchParams.get("v") ?? undefined : undefined;
};

async function refreshPage(): Promise<void> {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (tab?.id === undefined || !tab.url || !/^https?:/.test(tab.url)) return;
  const videoId = youtubeId(tab.url);
  const key = videoId ?? tab.url;
  if (key === (current?.videoId ?? current?.url) || key === detecting) return;
  if (!videoId && tab.status !== "complete") return; // article : attendre le titre définitif
  detecting = key;
  try {
    if (videoId) {
      const meta = await oembed(videoId);
      const title = meta.title ?? tab.title?.replace(/ - YouTube$/, "") ?? "";
      const speaker = await speakerFor(title, meta.channel);
      current = { tabId: tab.id, url: tab.url, kind: "youtube", videoId, title, channel: meta.channel, speaker, claims: [] };
      renderContext();
      void autoCheck(current);
    } else {
      current = { tabId: tab.id, url: tab.url, kind: "article", title: tab.title ?? tab.url, claims: [] };
      renderContext();
      showChips(["Vérifier cette page", "Quel est le taux de chômage aujourd'hui ?"]);
    }
  } finally {
    detecting = undefined;
  }
}

/** Titre et chaîne d'une vidéo, fiables même juste après une navigation (le DOM de YouTube est en retard). */
async function oembed(videoId: string): Promise<{ title?: string; channel?: string }> {
  try {
    const r = await fetch(`https://www.youtube.com/oembed?format=json&url=https://www.youtube.com/watch?v=${videoId}`);
    if (!r.ok) return {};
    const { title, author_name } = await r.json();
    return { title, channel: author_name };
  } catch {
    return {};
  }
}

// --- Orateur·rice --------------------------------------------------------------
// Le moteur a besoin de savoir qui parle (et ne stocke le résultat pour les profils qu'à cette condition).
// On le devine depuis le titre (« Michel Barnier : … ») ; la correction est retenue par chaîne.
// Jamais le nom de la chaîne : « RMC » ou « BFM Business » deviendraient des profils de politiques.

async function speakerFor(title: string, channel?: string): Promise<string | undefined> {
  const key = `speaker:${channel}`;
  const saved = channel ? ((await chrome.storage.local.get(key)) as Record<string, string>)[key] : undefined;
  return saved || guessFromTitle(title);
}

function renderContext(): void {
  if (!current) return;
  const page = current;
  $("analyze").textContent = page.kind === "youtube" ? "Analyser la vidéo" : "Analyser la page";
  const parts: (Node | string)[] = [el("span", { className: "ctx-title" }, `${page.kind === "youtube" ? "▶" : "📄"} ${page.title}`)];
  if (page.kind === "youtube") {
    const edit = el("button", { className: "link", title: "Corriger l'orateur·rice" }, `Orateur·rice : ${page.speaker ?? "inconnu·e, cliquez pour l'indiquer"} ✎`);
    edit.addEventListener("click", () => void editSpeaker(page));
    parts.push(edit);
  }
  $("ctx").replaceChildren(...parts);
}

async function editSpeaker(page: Page): Promise<void> {
  const name = prompt("Qui parle dans cette vidéo ?", page.speaker ?? "")?.trim();
  if (!name || name === page.speaker) return;
  page.speaker = name;
  if (page.channel) await chrome.storage.local.set({ [`speaker:${page.channel}`]: name });
  renderContext();
  void autoCheck(page, true);
}

// --- Vérification ----------------------------------------------------------------

async function autoCheck(page: Page, force = false, intro?: string): Promise<void> {
  const msg = botMessage(intro ?? (force ? `Je revérifie avec ${page.speaker} comme orateur·rice…` : "Je lis la page…"), true);
  setAnalyzing(+1);
  try {
    await chrome.scripting.executeScript({ target: { tabId: page.tabId }, files: ["extract.js"] });
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId: page.tabId },
      func: () => (globalThis as any).__verifpolExtract(),
    });
    const extracted = result as ExtractResult;
    let request: CheckRequest;
    if (extracted.ok) request = extracted.request;
    else if (extracted.noTranscript && page.videoId) request = await transcribeAudio(page, msg);
    else throw new Error(extracted.error);
    if (!request.segments.length) throw new Error("Je n'ai pas trouvé de texte à vérifier sur cette page.");
    msg.setText("J'extrais les affirmations et je les compare aux données officielles… (30 s à 2 min)");
    const req: CheckRequest = {
      ...request,
      source: { ...request.source, title: page.title },
      ...(page.speaker && { politician: { name: page.speaker } }),
    };
    const res = await checkClaims(req, force);
    page.claims = res.claims;
    showVerdicts(msg, page, res);
  } catch (err) {
    msg.fail(explain(err));
  } finally {
    setAnalyzing(-1);
  }
}

/** Vidéo sans sous-titres : le serveur télécharge l'audio (yt-dlp) et le fait transcrire par Deepgram. */
async function transcribeAudio(page: Page, msg: BotMessage): Promise<CheckRequest> {
  msg.setText("Pas de sous-titres YouTube : je fais transcrire l'audio par Deepgram… (20 s à 1 min)");
  try {
    const { segments } = await api<{ segments: Segment[] }>("/api/transcribe-youtube", {
      method: "POST",
      body: JSON.stringify({ videoId: page.videoId }),
    });
    return { source: { kind: "youtube", url: page.url, title: page.title }, segments };
  } catch (err) {
    throw new Error(`Cette vidéo n'a pas de sous-titres et je n'ai pas pu transcrire son audio : ${explain(err)} Vous pouvez quand même me poser vos questions.`);
  }
}

function setAnalyzing(delta: number): void {
  analyzing += delta;
  $<HTMLButtonElement>("analyze").disabled = analyzing > 0;
}

/** Bouton « Analyser » : relance l'analyse de la page ouverte en ignorant le cache du serveur. */
async function analyzeNow(): Promise<void> {
  if (!current) await refreshPage();
  if (!current) {
    botMessage("Ouvrez une vidéo YouTube ou un article, puis cliquez sur « Analyser ».");
    return;
  }
  showTab("chat");
  showChips([]);
  await autoCheck(current, true, current.kind === "youtube" ? "Je relance l'analyse de la vidéo…" : "J'analyse la page…");
}

async function checkSelection(text: string, url: string, title: string): Promise<void> {
  showTab("chat");
  userMessage(`Vérifie : « ${text} »`);
  const msg = botMessage("Je vérifie cette phrase…", true);
  try {
    const res = await checkClaims({ source: { kind: "selection", url, title }, segments: [{ text }] });
    showVerdicts(msg, undefined, res);
  } catch (err) {
    msg.fail(explain(err));
  }
}

const VERDICT_ORDER: Verdict[] = ["faux", "trompeur", "vrai", "invérifiable"];

function showVerdicts(msg: BotMessage, page: Page | undefined, res: CheckResponse): void {
  const n = res.claims.length;
  const where = page ? ` dans « ${page.title} »` : "";
  msg.setText(n
    ? `J'ai vérifié ${n} affirmation${n > 1 ? "s" : ""}${where}.`
    : `Je n'ai pas trouvé d'affirmation vérifiable${where}. Vous pouvez quand même me poser vos questions.`);
  if (res.demo) msg.body.prepend(el("div", { className: "demo" }, "Mode démo : verdicts fictifs (moteur non branché)."));
  if (n) msg.body.append(...verdictList(res.claims, page));
  msg.done();
  if (page) void saveHistory(page, res.claims);
  showChips(n ? ["Résume les verdicts", "Quel est le taux de chômage aujourd'hui ?"] : ["Quel est le taux de chômage aujourd'hui ?"]);
}

/** Filtres par verdict (cliquables) + liste d'affirmations, triée dans l'ordre de la vidéo. */
function verdictList(claims: Claim[], page: Page | undefined): HTMLElement[] {
  const sorted = [...claims].sort((a, b) => (a.start ?? Infinity) - (b.start ?? Infinity));
  const list = el("ol", { className: "claims" }, ...sorted.map((c) => claimItem(c, page)));
  const counts = new Map<Verdict, number>();
  for (const c of claims) counts.set(c.verdict, (counts.get(c.verdict) ?? 0) + 1);
  const filters = el("div", { className: "filters", role: "toolbar", ariaLabel: "Filtrer par verdict" });
  const select = (v: Verdict | "tout") => {
    filters.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.v === v)));
    list.querySelectorAll<HTMLElement>(".claim").forEach((li) => { li.hidden = v !== "tout" && li.dataset.verdict !== v; });
    list.scrollIntoView({ behavior: "smooth", block: "nearest" });
  };
  const button = (v: Verdict | "tout", label: string) => {
    const b = el("button", { className: `filter${v === "tout" ? "" : " tinted"}`, style: v === "tout" ? "" : `--c:var(--${v})` }, label);
    b.dataset.v = v;
    b.setAttribute("aria-pressed", String(v === "tout"));
    b.addEventListener("click", () => select(b.getAttribute("aria-pressed") === "true" && v !== "tout" ? "tout" : v));
    return b;
  };
  filters.append(button("tout", `Tout · ${claims.length}`),
    ...VERDICT_ORDER.filter((v) => counts.has(v)).map((v) => button(v, `${v} · ${counts.get(v)}`)));
  return [filters, list];
}

/** « Plutôt vrai : … Correction : … » → nuance, explication et correction séparées pour l'affichage. */
function splitExplanation(text: string): { nuance?: string; body: string; correction?: string } {
  const m = text.match(/^(Plutôt vrai|Imprécis)\s*:\s*/);
  let body = m ? text.slice(m[0].length) : text;
  let correction: string | undefined;
  const i = body.indexOf("Correction :");
  if (i >= 0) {
    correction = body.slice(i + "Correction :".length).trim();
    body = body.slice(0, i).trim();
  }
  return { nuance: m?.[1], body, correction };
}

/** Une affirmation : une ligne (verdict + citation + moment) qui se déplie sur le détail. */
function claimItem(claim: Claim, page: Page | undefined): HTMLElement {
  const { nuance, body, correction } = splitExplanation(claim.explanation);
  const row = el("summary", { className: "claim-row" },
    el("span", { className: "badge", style: `--c:var(--${claim.verdict})` }, claim.verdict),
    el("span", { className: "claim-quote" }, claim.quote));
  const actions = el("div", { className: "claim-actions" });
  if (claim.start !== undefined && page?.kind === "youtube") {
    const seek = el("button", { className: "seek", title: "Aller à ce moment de la vidéo" }, `▶ ${formatTime(claim.start)}`);
    seek.addEventListener("click", (e) => { e.preventDefault(); e.stopPropagation(); void seekVideo(page.tabId, claim.start!); });
    row.append(seek);
  }
  const why = el("button", { className: "link" }, "Pourquoi ce verdict ?");
  why.addEventListener("click", () => void ask(`Pourquoi « ${claim.verdict} » pour : « ${claim.quote} » ?`));
  actions.append(why);
  const sources = claim.sources.filter((s) => isWebUrl(s.url));
  const detail = el("div", { className: "claim-detail" },
    ...(nuance ? [el("p", { className: "nuance" }, nuance)] : []),
    el("p", { className: "explanation" }, body),
    ...(correction ? [el("div", { className: "correction" }, el("strong", {}, "Correction"), el("p", {}, correction))] : []),
    ...(sources.length ? [el("ul", { className: "sources" }, ...sources.map((s) =>
      el("li", {}, el("a", { href: s.url, target: "_blank", rel: "noopener" }, s.label),
        ...(s.official ? [el("span", { className: "official" }, "officielle")] : []))))] : []),
    actions,
  );
  const li = el("li", { className: "claim" }, el("details", { className: "claim-box" }, row, detail));
  li.dataset.verdict = claim.verdict;
  if (page?.videoId && claim.start !== undefined) {
    li.dataset.video = page.videoId;
    li.dataset.t = String(claim.start);
  }
  return li;
}

async function seekVideo(tabId: number, seconds: number): Promise<void> {
  await chrome.tabs.update(tabId, { active: true });
  await chrome.scripting.executeScript({
    target: { tabId },
    func: (t: number) => {
      // Pendant une pub YouTube, ou juste après, le lecteur ignore le saut :
      // on réessaie jusqu'à ce que la vidéo soit vraiment au bon moment (3 min max).
      const trySeek = (attempts: number) => {
        const video = document.querySelector("video");
        if (video && !document.querySelector(".ad-showing")) {
          if (Math.abs(video.currentTime - t) < 2) return;
          video.currentTime = t;
          void video.play();
        }
        if (attempts > 0) setTimeout(() => trySeek(attempts - 1), 500);
      };
      trySeek(360);
    },
    args: [seconds],
  });
}

/** Surligne la carte de l'affirmation en train d'être prononcée. */
async function pollPlayback(): Promise<void> {
  if (document.hidden || current?.kind !== "youtube" || !current.claims.length) return;
  const page = current;
  const [{ result }] = await chrome.scripting.executeScript({
    target: { tabId: page.tabId },
    func: () => (document.querySelector(".ad-showing") ? null : document.querySelector("video")?.currentTime ?? null),
  }).catch(() => [{ result: null }]);
  if (typeof result !== "number") return;
  const cards = [...document.querySelectorAll<HTMLElement>(`.claim[data-video="${page.videoId}"]`)];
  let live: HTMLElement | undefined;
  for (const c of cards) if (Number(c.dataset.t) <= result && result - Number(c.dataset.t) < 30) live = c;
  cards.forEach((c) => c.classList.toggle("live", c === live));
}

// --- Chat ----------------------------------------------------------------------

async function ask(text: string): Promise<void> {
  text = text.trim();
  if (!text || busy) return;
  if (text === "Vérifier cette page" && current) {
    showChips([]);
    userMessage(text);
    return autoCheck(current);
  }
  busy = true;
  $<HTMLButtonElement>("send").disabled = true;
  $<HTMLTextAreaElement>("question").value = "";
  fitInput();
  showChips([]);
  userMessage(text);
  history.push({ role: "user", content: text });
  const msg = botMessage("…", true);
  try {
    const res = await api<ChatResponse>("/api/chat", {
      method: "POST",
      body: JSON.stringify({
        messages: history,
        video_id: current?.videoId,
        title: current?.title,
        speaker: current?.speaker,
        claims: current?.claims,
      } satisfies ChatRequest),
    });
    history.push({ role: "assistant", content: res.answer });
    msg.setText(res.answer);
    const sources = res.sources.filter((s) => isWebUrl(s.url));
    if (sources.length) {
      msg.body.append(el("ul", { className: "sources" }, ...sources.map((s) =>
        el("li", {}, el("a", { href: s.url, target: "_blank", rel: "noopener" }, s.title)))));
    }
  } catch (err) {
    history.pop();
    msg.fail(explain(err));
  } finally {
    msg.done();
    busy = false;
    fitInput();
  }
}

/** Champ de saisie : grandit avec le texte ; envoi possible seulement s'il y a du texte. */
function fitInput(): void {
  const input = $<HTMLTextAreaElement>("question");
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 140)}px`;
  $<HTMLButtonElement>("send").disabled = busy || !input.value.trim();
}

function showChips(labels: string[]): void {
  $("chips").replaceChildren(...labels.map((label) => {
    const chip = el("button", { className: "chip" }, label);
    chip.addEventListener("click", () => void ask(label));
    return chip;
  }));
}

// --- Messages du fil -------------------------------------------------------------

interface BotMessage {
  body: HTMLElement;
  setText(text: string): void;
  done(): void;
  fail(text: string): void;
}

function userMessage(text: string): void {
  append(el("div", { className: "msg me" }, text));
}

/** Message de l'assistant, modifiable tant qu'il est en cours. */
function botMessage(text: string, pending = false): BotMessage {
  const p = el("p", {}, text);
  const body = el("div", { className: `msg bot${pending ? " pending" : ""}` }, p);
  append(body);
  return {
    body,
    setText: (t) => { p.textContent = t; scrollDown(); },
    done: () => { body.classList.remove("pending"); scrollDown(); },
    fail: (t) => { p.textContent = t; body.classList.remove("pending"); body.classList.add("error"); scrollDown(); },
  };
}

function append(node: HTMLElement): void {
  $("thread").append(node);
  scrollDown();
}

function scrollDown(): void {
  $("thread").scrollTop = $("thread").scrollHeight;
}

// --- Onglet « Veille » ---------------------------------------------------------

const STATUS_LABEL: Record<EpisodeStatus, string> = {
  en_attente: "en attente",
  transcription: "transcription…",
  analyse: "analyse…",
  fait: "vérifié",
  erreur: "erreur",
  a_ouvrir: "à ouvrir",
};

async function loadWatch(): Promise<void> {
  const history = await loadHistory();
  renderHistory(history);
  try {
    const data = await api<WatchResponse>("/api/watch");
    const last = data.lastPollAt ? new Date(data.lastPollAt).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" }) : "jamais";
    $("watch-meta").textContent = `Dernier passage : ${last}`;
    setStatus("watch-status", data.transcriptionEnabled ? "" : "Transcription désactivée : ajoutez DEEPGRAM_API_KEY dans server/.env.");
    $("episodes").replaceChildren(...data.episodes.map(episodeCard));
    renderSessionSummary(history, data.episodes);
  } catch (err) {
    setStatus("watch-status", explain(err), true);
    renderSessionSummary(history, []);
  }
}

// --- Historique (pages analysées, gardé dans le navigateur) -----------------------

interface HistoryEntry {
  key: string;
  url: string;
  title: string;
  kind: Page["kind"];
  videoId?: string;
  speaker?: string;
  at: string;
  session: string;
  claims: Claim[];
}

const HISTORY_MAX = 40;
let sessionId = "";

/** Une « session » dure jusqu'à la fermeture du navigateur (chrome.storage.session). */
async function initSession(): Promise<void> {
  const stored = (await chrome.storage.session.get("sessionId")) as { sessionId?: string };
  sessionId = stored.sessionId ?? crypto.randomUUID();
  if (!stored.sessionId) await chrome.storage.session.set({ sessionId });
}

async function loadHistory(): Promise<HistoryEntry[]> {
  return ((await chrome.storage.local.get("history")) as { history?: HistoryEntry[] }).history ?? [];
}

async function saveHistory(page: Page, claims: Claim[]): Promise<void> {
  const key = page.videoId ?? page.url;
  const entry: HistoryEntry = { key, url: page.url, title: page.title, kind: page.kind, videoId: page.videoId,
    speaker: page.speaker, at: new Date().toISOString(), session: sessionId, claims };
  const list = [entry, ...(await loadHistory()).filter((h) => h.key !== key)].slice(0, HISTORY_MAX);
  await chrome.storage.local.set({ history: list });
}

/** Ouvre (ou réactive) l'onglet de la page ; l'analyse revient du cache du serveur, sans nouvel appel à Claude. */
async function openPage(url: string, seconds?: number): Promise<void> {
  const target = seconds !== undefined && youtubeId(url) ? `https://www.youtube.com/watch?v=${youtubeId(url)}&t=${Math.floor(seconds)}s` : url;
  const [existing] = await chrome.tabs.query({ url: url.split("#")[0] });
  if (existing?.id !== undefined && seconds === undefined) await chrome.tabs.update(existing.id, { active: true });
  else await chrome.tabs.create({ url: target });
  showTab("chat");
}

function renderHistory(history: HistoryEntry[]): void {
  $("history-empty").hidden = history.length > 0;
  $("history").replaceChildren(...history.map((h) => {
    const counts = VERDICT_ORDER.map((v) => [v, h.claims.filter((c) => c.verdict === v).length] as const).filter(([, k]) => k);
    const when = new Date(h.at).toLocaleString("fr-FR", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
    const open = el("button", { className: "history-item", title: "Rouvrir : les verdicts reviennent sans nouvelle analyse" },
      el("span", { className: "history-title" }, `${h.kind === "youtube" ? "▶" : "📄"} ${h.title}`),
      el("span", { className: "meta" }, [when, h.speaker].filter(Boolean).join(" · ")),
      el("span", { className: "mini-counts" }, ...(counts.length
        ? counts.map(([v, k]) => el("span", { className: "mini", style: `--c:var(--${v})` }, `${k} ${v}`))
        : [el("span", { className: "meta" }, "aucune affirmation vérifiable")])));
    open.addEventListener("click", () => void openPage(h.url));
    return el("li", {}, open);
  }));
}

/**
 * Affirmations fausses ou trompeuses de la session (pages vues + podcasts de la veille du jour).
 * Une même phrase vue à plusieurs endroits (vidéo revue, extrait repris par un podcast) n'apparaît qu'une fois.
 */
function renderSessionSummary(history: HistoryEntry[], episodes: WatchEpisode[]): void {
  type Seen = { title: string; url: string; seconds?: number };
  const bad = (c: Claim) => c.verdict === "faux" || c.verdict === "trompeur";
  const today = new Date().toDateString();
  const found: { claim: Claim; seen: Seen }[] = [
    ...history.filter((h) => h.session === sessionId).flatMap((h) =>
      h.claims.filter(bad).map((claim) => ({ claim, seen: { title: h.title, url: h.url, seconds: h.kind === "youtube" ? claim.start : undefined } }))),
    ...episodes.filter((e) => e.claims && new Date(e.publishedAt).toDateString() === today).flatMap((e) =>
      e.claims!.filter(bad).map((claim) => ({ claim, seen: { title: `${e.feedName} – ${e.title}`, url: e.url } }))),
  ];
  const byQuote = new Map<string, { claim: Claim; seen: Seen[] }>();
  for (const { claim, seen } of found) {
    const key = claim.quote.toLowerCase().normalize("NFD").replace(/[^a-z0-9]+/g, " ").trim();
    const entry = byQuote.get(key) ?? byQuote.set(key, { claim, seen: [] }).get(key)!;
    if (!entry.seen.some((s) => s.url === seen.url)) entry.seen.push(seen);
  }
  const items = [...byQuote.values()].sort((a, b) => VERDICT_ORDER.indexOf(a.claim.verdict) - VERDICT_ORDER.indexOf(b.claim.verdict));
  const nFaux = items.filter((i) => i.claim.verdict === "faux").length;
  const nTromp = items.length - nFaux;
  $("summary-meta").textContent = `cette session${items.length ? ` · ${nFaux} faux · ${nTromp} trompeur${nTromp > 1 ? "s" : ""}` : ""}`;
  $("summary-empty").hidden = items.length > 0;
  $("session-summary").replaceChildren(...items.map(({ claim, seen }) => {
    const { body, correction } = splitExplanation(claim.explanation);
    const row = el("summary", { className: "claim-row" },
      el("span", { className: "badge", style: `--c:var(--${claim.verdict})` }, claim.verdict),
      el("span", { className: "claim-quote" }, claim.quote),
      ...(seen.length > 1 ? [el("span", { className: "seen-count", title: "Vue dans plusieurs sources" }, `×${seen.length}`)] : []));
    const links = seen.map(({ title, url, seconds }) => {
      const go = el("button", { className: "link" }, seconds !== undefined ? `▶ ${formatTime(seconds)} · ${title}` : title);
      go.addEventListener("click", () => void (isWebUrl(url) && openPage(url, seconds)));
      return el("li", {}, go);
    });
    return el("li", { className: "claim" }, el("details", { className: "claim-box" }, row,
      el("div", { className: "claim-detail" },
        el("p", { className: "explanation" }, body),
        ...(correction ? [el("div", { className: "correction" }, el("strong", {}, "Correction"), el("p", {}, correction))] : []),
        el("p", { className: "seen-label" }, seen.length > 1 ? `Vue dans ${seen.length} sources` : "Vue dans"),
        el("ul", { className: "seen" }, ...links))));
  }));
}

function episodeCard(ep: WatchEpisode): HTMLElement {
  const date = new Date(ep.publishedAt).toLocaleString("fr-FR", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  const card = el("li", { className: "episode" },
    el("div", { className: "meta" }, el("span", {}, ep.feedName), el("span", {}, `${date} · ${STATUS_LABEL[ep.status]}`)),
    el("div", { className: "episode-title" }, isWebUrl(ep.url) ? el("a", { href: ep.url, target: "_blank", rel: "noopener" }, ep.title) : ep.title),
  );
  if (ep.error) card.append(el("p", { className: "status error" }, ep.error));
  if (ep.kind === "youtube" && isWebUrl(ep.url)) {
    const open = el("button", {}, "Ouvrir et vérifier");
    // La vérification automatique se lance quand l'onglet de la vidéo devient actif.
    open.addEventListener("click", () => { showTab("chat"); void chrome.tabs.create({ url: ep.url }); });
    card.append(open);
  }
  if (ep.claims) {
    card.append(el("details", {},
      el("summary", {}, `${ep.claims.length} affirmation(s)`),
      ...verdictList(ep.claims, undefined),
    ));
  }
  return card;
}

// --- Utilitaires ---------------------------------------------------------------

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  props: Partial<Omit<HTMLElementTagNameMap[K], "style">> & { style?: string },
  ...children: (Node | string)[]
): HTMLElementTagNameMap[K] {
  const { style, ...rest } = props;
  const node = Object.assign(document.createElement(tag), rest);
  if (style) node.style.cssText = style;
  node.append(...children);
  return node;
}

const isWebUrl = (url: string) => /^https?:\/\//.test(url);

function setStatus(id: string, text: string, isError = false): void {
  const node = $(id);
  node.textContent = text;
  node.classList.toggle("error", isError);
}

function explain(err: unknown): string {
  const msg = (err as Error).message ?? String(err);
  if (msg === "Failed to fetch") return `Je n'arrive pas à joindre le serveur (${backend}). Lancez-le avec « npm run dev:server ».`;
  if (msg.includes("Cannot access") || msg.includes("chrome://")) return "Chrome ne permet pas d'analyser cette page.";
  return msg;
}

function formatTime(s: number): string {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = String(Math.floor(s % 60)).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
}

let watchTimer: ReturnType<typeof setInterval> | undefined;

function showTab(name: "chat" | "watch"): void {
  document.querySelectorAll<HTMLElement>(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  $("tab-chat").hidden = name !== "chat";
  $("tab-watch").hidden = name !== "watch";
  clearInterval(watchTimer);
  if (name === "watch") {
    void loadWatch();
    watchTimer = setInterval(() => void loadWatch(), WATCH_REFRESH_MS);
  }
}

async function consumePendingSelection(): Promise<void> {
  const { pendingSelection } = (await chrome.storage.session.get("pendingSelection")) as {
    pendingSelection?: { text: string; url: string; title: string };
  };
  if (!pendingSelection) return;
  await chrome.storage.session.remove("pendingSelection");
  void checkSelection(pendingSelection.text, pendingSelection.url, pendingSelection.title);
}

// --- Démarrage -----------------------------------------------------------------

async function init(): Promise<void> {
  const stored = (await chrome.storage.sync.get("backend")) as { backend?: string };
  backend = stored.backend || DEFAULT_BACKEND;
  const input = $<HTMLInputElement>("backend");
  input.value = backend;
  input.addEventListener("change", () => {
    backend = input.value.replace(/\/+$/, "") || DEFAULT_BACKEND;
    void chrome.storage.sync.set({ backend });
  });

  document.querySelectorAll<HTMLElement>(".tab").forEach((t) => t.addEventListener("click", () => showTab(t.dataset.tab as "chat" | "watch")));

  $("ask").addEventListener("submit", (e) => { e.preventDefault(); void ask($<HTMLTextAreaElement>("question").value); });
  $("question").addEventListener("input", fitInput);
  fitInput();
  $("question").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void ask($<HTMLTextAreaElement>("question").value); }
  });

  $("analyze").addEventListener("click", () => void analyzeNow());
  $("reload").addEventListener("click", () => chrome.runtime.reload());

  $("refresh").addEventListener("click", async () => {
    try {
      await api("/api/watch/refresh", { method: "POST" });
      setStatus("watch-status", "Veille relancée…");
      setTimeout(() => void loadWatch(), 3000);
    } catch (err) {
      setStatus("watch-status", explain(err), true);
    }
  });

  chrome.storage.session.onChanged.addListener((changes) => {
    if (changes.pendingSelection?.newValue) void consumePendingSelection();
  });

  // YouTube change d'URL sans recharger la page : Chrome le signale via onUpdated.
  chrome.tabs.onActivated.addListener(() => void refreshPage());
  chrome.tabs.onUpdated.addListener((_id, change) => { if (change.url || change.status === "complete") void refreshPage(); });
  setInterval(() => void pollPlayback(), TIME_POLL_MS);

  const hello = botMessage("Bonjour ! Je vérifie les affirmations des responsables politiques à partir des données publiques.");
  hello.body.append(el("ul", { className: "hello" },
    el("li", {}, "Ouvrez une vidéo YouTube : je la vérifie toute seule."),
    el("li", {}, "Sur un article : « Analyser la page » en haut."),
    el("li", {}, "Une phrase précise : sélectionnez-la, puis clic droit."),
    el("li", {}, "Ensuite, posez vos questions ci-dessous.")));
  showChips(["Quel est le taux de chômage aujourd'hui ?"]);
  await initSession();
  await consumePendingSelection();
  await refreshPage();
}

void init();
