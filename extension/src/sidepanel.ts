// Panneau latéral en mode chat : la vidéo YouTube ouverte est vérifiée automatiquement,
// le résultat arrive comme un message, et l'utilisateur pose ses questions dessous.

import type {
  ChatRequest, ChatResponse, CheckRequest, CheckResponse, Claim, EpisodeStatus, Verdict, WatchEpisode, WatchResponse,
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
    if (!extracted.ok) throw new Error(extracted.error);
    if (!extracted.request.segments.length) throw new Error("Je n'ai pas trouvé de texte à vérifier sur cette page.");
    msg.setText("J'extrais les affirmations et je les compare aux données officielles… (30 s à 2 min)");
    const req: CheckRequest = {
      ...extracted.request,
      source: { ...extracted.request.source, title: page.title },
      ...(page.speaker && { politician: { name: page.speaker } }),
    };
    const res = await checkClaims(req, force);
    page.claims = res.claims;
    showVerdicts(msg, page, res);
  } catch (err) {
    msg.setText(explain(err));
    msg.done();
  } finally {
    setAnalyzing(-1);
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
    msg.setText(explain(err));
    msg.done();
  }
}

function showVerdicts(msg: BotMessage, page: Page | undefined, res: CheckResponse): void {
  const n = res.claims.length;
  const where = page ? ` dans « ${page.title} »` : "";
  msg.setText(n
    ? `J'ai vérifié ${n} affirmation${n > 1 ? "s" : ""}${where} :`
    : `Je n'ai pas trouvé d'affirmation vérifiable${where}. Vous pouvez quand même me poser vos questions.`);
  if (res.demo) msg.body.prepend(el("div", { className: "demo" }, "Mode démo : verdicts fictifs (moteur non branché)."));
  if (n) {
    const counts = new Map<Verdict, number>();
    for (const c of res.claims) counts.set(c.verdict, (counts.get(c.verdict) ?? 0) + 1);
    msg.body.append(
      el("div", { className: "stats" }, ...[...counts].map(([v, k]) => el("span", { className: "verdict", style: `--c:var(--${v})` }, `${v} · ${k}`))),
      el("ol", { className: "claims" }, ...res.claims.map((c) => claimCard(c, page))),
    );
  }
  msg.done();
  showChips(n ? ["Résume les verdicts", "Quel est le taux de chômage aujourd'hui ?"] : ["Quel est le taux de chômage aujourd'hui ?"]);
}

function claimCard(claim: Claim, page: Page | undefined): HTMLElement {
  const head = el("div", { className: "claim-head" }, el("span", { className: "verdict" }, claim.verdict));
  if (claim.start !== undefined && page?.kind === "youtube") {
    const seek = el("button", { className: "seek", title: "Aller à ce moment de la vidéo" }, `▶ ${formatTime(claim.start)}`);
    seek.addEventListener("click", () => void seekVideo(page.tabId, claim.start!));
    head.append(seek);
  }
  const why = el("button", { className: "link" }, "Pourquoi ?");
  why.addEventListener("click", () => void ask(`Pourquoi « ${claim.verdict} » pour : « ${claim.quote} » ?`));
  const card = el("li", { className: "claim", style: `--c:var(--${claim.verdict})` },
    head,
    el("p", { className: "quote" }, `« ${claim.quote} »`),
    el("p", { className: "explanation" }, claim.explanation),
    el("ul", { className: "sources" }, ...claim.sources.filter((s) => isWebUrl(s.url)).map((s) =>
      el("li", {}, el("a", { href: s.url, target: "_blank", rel: "noopener" }, s.label),
        ...(s.official ? [el("span", { className: "official" }, "source officielle")] : [])))),
    why,
  );
  if (page?.videoId && claim.start !== undefined) {
    card.dataset.video = page.videoId;
    card.dataset.t = String(claim.start);
  }
  return card;
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
    msg.setText(explain(err));
  } finally {
    msg.done();
    busy = false;
    $<HTMLButtonElement>("send").disabled = false;
  }
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
  try {
    const data = await api<WatchResponse>("/api/watch");
    const last = data.lastPollAt ? new Date(data.lastPollAt).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" }) : "jamais";
    $("watch-meta").textContent = `Dernier passage : ${last}`;
    setStatus("watch-status", data.transcriptionEnabled ? "" : "Transcription désactivée : ajoutez DEEPGRAM_API_KEY dans server/.env.");
    $("episodes").replaceChildren(...data.episodes.map(episodeCard));
  } catch (err) {
    setStatus("watch-status", explain(err), true);
  }
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
      el("ol", { className: "claims" }, ...ep.claims.map((c) => claimCard(c, undefined))),
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

  botMessage("Bonjour ! Ouvrez une vidéo YouTube d'un·e responsable politique : je vérifie automatiquement ses affirmations, puis vous pouvez me poser vos questions. Sur un article, demandez « Vérifier cette page », ou sélectionnez une phrase puis clic droit.");
  showChips(["Quel est le taux de chômage aujourd'hui ?"]);
  await consumePendingSelection();
  await refreshPage();
}

void init();
