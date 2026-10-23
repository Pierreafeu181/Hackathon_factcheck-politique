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
  kind: "youtube" | "video" | "article"; // video : TikTok, Instagram, X… (audio transcrit par le serveur)
  videoId?: string;
  title: string;
  channel?: string;
  speaker?: string;
  claims: Claim[];
}

let backend = DEFAULT_BACKEND;
let apiToken = ""; // clé d'accès d'un serveur hébergé (vide en local)
let current: Page | undefined;
let detecting: string | undefined; // page en cours de détection (plusieurs événements Chrome par navigation)
let history: ChatRequest["messages"] = [];
let busy = false;
let analyzing = 0; // analyses en cours (le bouton « Analyser » est désactivé pendant ce temps)

// --- Appels au serveur ---------------------------------------------------------

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(backend + path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(apiToken && { "X-VerifPol-Token": apiToken }) },
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error ?? `Serveur : HTTP ${res.status}`);
  return body as T;
}

const checkClaims = (req: CheckRequest, force = false) =>
  api<CheckResponse>(`/api/check${force ? "?force=1" : ""}`, { method: "POST", body: JSON.stringify(req) });

// --- Page courante -------------------------------------------------------------

const youtubeId = (url: string) => {
  const u = new URL(url);
  if (u.hostname.endsWith("youtube.com") && u.pathname === "/watch") return u.searchParams.get("v") ?? undefined;
  if (u.hostname.endsWith("youtube.com") && u.pathname.startsWith("/shorts/")) return u.pathname.split("/")[2] || undefined;
  if (u.hostname === "youtu.be") return u.pathname.slice(1) || undefined;
  return undefined;
};

/** Pages vidéo des autres plateformes : l'audio est téléchargé et transcrit par le serveur (yt-dlp + Deepgram). */
const VIDEO_PAGES: [RegExp, RegExp][] = [
  [/(^|\.)tiktok\.com$/, /\/video\/\d+/],
  [/(^|\.)instagram\.com$/, /^\/(reels?|p|tv)\/[\w-]+/],
  [/(^|\.)(x|twitter)\.com$/, /\/status\/\d+/],
  [/(^|\.)facebook\.com$/, /\/(watch|reel|videos)\b|\/share\/[rv]\//],
  [/^fb\.watch$/, /./],
  [/(^|\.)dailymotion\.com$/, /^\/video\//],
  [/^dai\.ly$/, /./],
  [/(^|\.)vimeo\.com$/, /^\/\d+/],
  [/(^|\.)twitch\.tv$/, /\/(videos|clip)\//],
  [/(^|\.)france\.tv$/, /\.html$/],
  [/(^|\.)arte\.tv$/, /\/videos\//],
  [/(^|\.)rumble\.com$/, /^\/v/],
  [/(^|\.)linkedin\.com$/, /^\/posts\//],
  [/(^|\.)threads\.(net|com)$/, /\/post\//],
];
const isVideoPage = (url: string) => {
  const u = new URL(url);
  return VIDEO_PAGES.some(([host, path]) => host.test(u.hostname) && path.test(u.pathname));
};
/** Réseaux où un post peut n'être que du texte ou une photo : on vérifie qu'il y a bien une vidéo. */
const MAYBE_VIDEO = /(^|\.)(x|twitter|facebook|linkedin|threads|instagram)\.(com|net)$/;

/** Attend jusqu'à 4 s qu'un lecteur <video> apparaisse (les réseaux sociaux chargent la vidéo après la page). */
async function pageHasVideo(tabId: number): Promise<boolean> {
  const [{ result }] = await chrome.scripting.executeScript({
    target: { tabId },
    func: async () => {
      for (let i = 0; i < 8; i++) {
        if (document.querySelector("video")) return true;
        await new Promise((r) => setTimeout(r, 500));
      }
      return false;
    },
  }).catch(() => [{ result: false }]);
  return result === true;
}
const isVideo = (page?: Page) => page?.kind === "youtube" || page?.kind === "video";
/** Clé d'une page pour le surlignage pendant la lecture et l'historique. */
const mediaKey = (page: Page) => page.videoId ?? page.url;

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
      setSuggestions([]);
      void autoCheck(current);
    } else if (isVideoPage(tab.url) && (!MAYBE_VIDEO.test(new URL(tab.url).hostname) || await pageHasVideo(tab.id))) {
      const title = tab.title ?? tab.url;
      current = { tabId: tab.id, url: tab.url, kind: "video", title, speaker: guessFromTitle(title), claims: [] };
      renderContext();
      setSuggestions([]);
      void autoCheck(current);
    } else {
      current = { tabId: tab.id, url: tab.url, kind: "article", title: tab.title ?? tab.url, claims: [] };
      renderContext();
      if (await looksLikeArticle(tab.id)) void autoCheck(current, false, "Je lis l'article…");
      else setSuggestions([], ["Analyser la page"]);
    }
  } finally {
    detecting = undefined;
  }
}

/** Article de presse ? (balises des sites d'info, ou un long bloc <article>). Les accueils et recherches sont ignorés. */
async function looksLikeArticle(tabId: number): Promise<boolean> {
  const [{ result }] = await chrome.scripting.executeScript({
    target: { tabId },
    func: () => {
      const og = document.querySelector<HTMLMetaElement>('meta[property="og:type"]')?.content ?? "";
      const ld = [...document.querySelectorAll('script[type="application/ld+json"]')].some((s) =>
        /"@type"\s*:\s*\[?\s*"(News|Reportage|Analysis|Opinion)?Article"/.test(s.textContent ?? ""));
      const text = document.querySelector("article")?.textContent?.length ?? 0;
      return (og === "article" || ld) ? text > 600 || document.body.innerText.length > 2500 : text > 2500;
    },
  }).catch(() => [{ result: false }]);
  return result === true;
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
  $("analyze").textContent = isVideo(page) ? "Analyser la vidéo" : "Analyser la page";
  const parts: (Node | string)[] = [el("span", { className: "ctx-title" }, `${isVideo(page) ? "▶" : "📄"} ${page.title}`)];
  if (isVideo(page)) {
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
    let request: CheckRequest;
    if (page.kind === "video") {
      request = await transcribeAudio(page, msg);
    } else {
      await chrome.scripting.executeScript({ target: { tabId: page.tabId }, files: ["extract.js"] });
      const [{ result }] = await chrome.scripting.executeScript({
        target: { tabId: page.tabId },
        func: () => (globalThis as any).__verifpolExtract(),
      });
      const extracted = result as ExtractResult;
      if (extracted.ok) request = extracted.request;
      else if (extracted.noTranscript && page.videoId) request = await transcribeAudio(page, msg);
      else throw new Error(extracted.error);
    }
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

/** Vidéo sans texte lisible (YouTube sans sous-titres, TikTok, Instagram…) : le serveur télécharge l'audio et Deepgram le transcrit. */
async function transcribeAudio(page: Page, msg: BotMessage): Promise<CheckRequest> {
  msg.setText(page.kind === "youtube"
    ? "Pas de sous-titres YouTube : je fais transcrire l'audio… (20 s à 1 min)"
    : "Je récupère l'audio de la vidéo et je le fais transcrire… (20 s à 1 min)");
  try {
    const { segments } = await api<{ segments: Segment[] }>("/api/transcribe", {
      method: "POST",
      body: JSON.stringify(page.videoId ? { videoId: page.videoId } : { url: page.url }),
    });
    // « podcast » = audio transcrit (le contrat ne connaît pas encore les autres plateformes vidéo)
    return { source: { kind: page.kind === "youtube" ? "youtube" : "podcast", url: page.url, title: page.title }, segments };
  } catch (err) {
    throw new Error(`Je n'ai pas pu télécharger cette vidéo : ${explain(err)} Lancez-la et cliquez sur « ● Direct » : j'écouterai le son de l'onglet pendant la lecture.`);
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
  setSuggestions(contextQuestions(current.claims));
  await autoCheck(current, true, isVideo(current) ? "Je relance l'analyse de la vidéo…" : "J'analyse la page…");
}

// --- Direct : son de l'onglet → Deepgram en streaming → verdicts au fil de l'eau ------------

interface LiveSession {
  page: Page;
  ws: WebSocket;
  /** Capture de l'onglet (tabCapture) : le panneau enregistre lui-même. */
  stream?: MediaStream;
  audio?: AudioContext;
  recorder?: MediaRecorder;
  /** Repli : le lecteur de la page enregistre et envoie ses morceaux par ce port. */
  port?: chrome.runtime.Port;
  msg: BotMessage;
  status: HTMLElement;
  feed: HTMLElement;
  list: HTMLOListElement;
  claims: Claim[];
}
let live: LiveSession | undefined;

function setLiveButton(on: boolean): void {
  const b = $<HTMLButtonElement>("live");
  b.classList.toggle("on", on);
  b.textContent = on ? "■ Arrêter" : "● Direct";
}

/** Moment de la vidéo au démarrage, pour que ▶ renvoie au bon endroit (0 si pas de lecteur). */
async function playbackTime(tabId: number): Promise<number> {
  const [{ result }] = await chrome.scripting.executeScript({
    target: { tabId },
    func: () => document.querySelector("video")?.currentTime ?? 0,
  }).catch(() => [{ result: 0 }]);
  return typeof result === "number" ? result : 0;
}

async function toggleLive(menuStreamId?: string): Promise<void> {
  if (live) return stopLive();
  if (!current) await refreshPage();
  const page = current;
  if (!page) {
    botMessage("Ouvrez l'onglet à écouter (direct, TV, vidéo), puis cliquez sur « ● Direct ».");
    return;
  }
  showTab("chat");
  const msg = botMessage("Je capte le son de l'onglet…", true);
  // 1) Capture de l'onglet : tout le son, mais Chrome l'exige après un clic sur l'icône depuis cet onglet.
  // 2) Sinon, le lecteur <video> de la page : pas besoin de ce clic, marche sur la plupart des sites.
  let stream: MediaStream | undefined;
  let audio: AudioContext | undefined;
  try {
    const streamId = menuStreamId ?? await chrome.tabCapture.getMediaStreamId({ targetTabId: page.tabId });
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { mandatory: { chromeMediaSource: "tab", chromeMediaSourceId: streamId } },
    } as unknown as MediaStreamConstraints);
    // La capture coupe le son de l'onglet : on le renvoie vers les haut-parleurs.
    audio = new AudioContext();
    audio.createMediaStreamSource(stream).connect(audio.destination);
  } catch {
    const ok = await pageHasPlayer(page.tabId);
    if (!ok) {
      msg.fail("Je ne trouve pas de lecteur dans cette page. Faites un clic droit sur la page → « ● Vérifier en direct » (ou Alt+Maj+L) : Chrome m'autorise alors à capter tout le son de l'onglet.");
      return;
    }
  }
  const status = el("p", { className: "live-status" }, "Connexion au serveur…");
  const feed = el("div", { className: "live-feed" });
  const list = el("ol", { className: "claims" });
  msg.setText(`En direct : « ${page.title} »`);
  msg.body.classList.remove("pending");
  msg.body.append(status, feed, list);
  page.claims = [];
  const ws = new WebSocket(`${backend.replace(/^http/, "ws")}/api/live${apiToken ? `?token=${encodeURIComponent(apiToken)}` : ""}`);
  live = { page, ws, stream, audio, msg, status, feed, list, claims: page.claims };
  setLiveButton(true);
  const offset = await playbackTime(page.tabId);
  ws.onopen = () => ws.send(JSON.stringify({ type: "start", url: page.url, title: page.title, speaker: page.speaker, offset }));
  ws.onmessage = (e) => onLiveMessage(JSON.parse(String(e.data)));
  ws.onerror = () => { status.textContent = explain(new Error("Failed to fetch")); };
  ws.onclose = () => endLive();
  stream?.getAudioTracks()[0]?.addEventListener("ended", () => stopLive()); // onglet fermé
}

/** Frame qui contient le lecteur à écouter (de préférence celui qui joue, sinon le plus grand), y compris dans une iframe. */
async function playerFrame(tabId: number): Promise<number | undefined> {
  const results = await chrome.scripting.executeScript({
    target: { tabId, allFrames: true },
    func: () => Math.max(0, ...[...document.querySelectorAll<HTMLMediaElement>("video, audio")].map((m) =>
      (m.paused ? 1 : 1_000_000) + m.clientWidth * m.clientHeight)),
  }).catch(() => []);
  const best = results.filter((r) => typeof r.result === "number" && r.result > 0).sort((a, b) => (b.result as number) - (a.result as number))[0];
  return best?.frameId;
}

async function pageHasPlayer(tabId: number): Promise<boolean> {
  return (await playerFrame(tabId)) !== undefined;
}

/**
 * Repli sans tabCapture : dans la page, on enregistre le son du lecteur le plus grand (captureStream)
 * et on renvoie les morceaux au panneau par un port. Le son reste audible. Ne marche pas sur les
 * vidéos protégées (DRM) ou servies depuis un autre domaine sans CORS : elles donnent du silence.
 */
async function startPlayerRecorder(s: LiveSession): Promise<void> {
  chrome.runtime.onConnect.addListener(function onPort(port) {
    if (port.name !== "verifpol-live" || port.sender?.tab?.id !== s.page.tabId) return;
    chrome.runtime.onConnect.removeListener(onPort);
    s.port = port;
    port.onMessage.addListener((m: { chunk?: number[]; error?: string }) => {
      if (m.error) s.status.textContent = m.error;
      else if (m.chunk && s.ws.readyState === WebSocket.OPEN) s.ws.send(new Uint8Array(m.chunk));
    });
    port.onDisconnect.addListener(() => { if (live === s) stopLive(); });
  });
  const frameId = await playerFrame(s.page.tabId);
  await chrome.scripting.executeScript({
    target: { tabId: s.page.tabId, frameIds: frameId !== undefined ? [frameId] : [0] },
    func: () => {
      const players = [...document.querySelectorAll<HTMLMediaElement>("video, audio")];
      const media = players.find((m) => !m.paused) ?? players.sort((a, b) => (b.clientWidth * b.clientHeight) - (a.clientWidth * a.clientHeight))[0];
      const port = chrome.runtime.connect({ name: "verifpol-live" });
      const capture = (media as HTMLMediaElement & { captureStream?: () => MediaStream })?.captureStream;
      if (!media || !capture) {
        port.postMessage({ error: "Ce lecteur ne permet pas de capter le son. Cliquez sur l'icône Vérif'Pol depuis cet onglet, puis réessayez." });
        return port.disconnect();
      }
      const tracks = capture.call(media).getAudioTracks();
      const recorder = new MediaRecorder(new MediaStream(tracks), { mimeType: "audio/webm;codecs=opus" });
      recorder.ondataavailable = async (e) => {
        if (e.data.size) port.postMessage({ chunk: Array.from(new Uint8Array(await e.data.arrayBuffer())) });
      };
      port.onMessage.addListener((m: { stop?: boolean }) => { if (m.stop && recorder.state === "recording") recorder.stop(); });
      port.onDisconnect.addListener(() => recorder.state === "recording" && recorder.stop());
      recorder.start(250);
      if (media.paused) void media.play().catch(() => undefined);
    },
  });
}

function onLiveMessage(m: { type: string; text?: string; start?: number; claims?: Claim[]; error?: string }): void {
  const s = live;
  if (!s) return;
  if (m.type === "ready") {
    s.status.textContent = "J'écoute. Les verdicts arrivent toutes les ~45 s de parole.";
    if (s.stream) {
      s.recorder = new MediaRecorder(s.stream, { mimeType: "audio/webm;codecs=opus" });
      s.recorder.ondataavailable = (e) => { if (e.data.size && s.ws.readyState === WebSocket.OPEN) s.ws.send(e.data); };
      s.recorder.start(250);
    } else {
      void startPlayerRecorder(s).catch((err) => { s.status.textContent = `Capture impossible : ${explain(err)}`; });
    }
  } else if (m.type === "transcript" && m.text) {
    s.feed.append(el("span", {}, m.text));
    while (s.feed.childElementCount > 3) s.feed.firstElementChild!.remove();
    scrollDown();
  } else if (m.type === "checking") {
    s.status.textContent = "Je vérifie le dernier passage…";
  } else if (m.type === "claims" && m.claims) {
    s.claims.push(...m.claims);
    s.list.append(...m.claims.map((c) => claimItem(c, s.page)));
    s.status.textContent = `J'écoute · ${s.claims.length} affirmation${s.claims.length > 1 ? "s" : ""} vérifiée${s.claims.length > 1 ? "s" : ""}`;
    setSuggestions(contextQuestions(s.claims));
    scrollDown();
  } else if (m.type === "error" && m.error) {
    s.status.textContent = m.error;
  }
}

function stopLive(): void {
  const s = live;
  if (!s) return;
  s.status.textContent = "J'arrête et je vérifie le dernier passage…";
  s.recorder?.state === "recording" && s.recorder.stop();
  s.port?.postMessage({ stop: true });
  s.stream?.getTracks().forEach((t) => t.stop());
  if (s.audio && s.audio.state !== "closed") void s.audio.close();
  if (s.ws.readyState === WebSocket.OPEN) s.ws.send(JSON.stringify({ type: "stop" }));
  else endLive();
}

/** Le serveur a fini (ou la connexion est tombée) : bilan et historique. */
function endLive(): void {
  const s = live;
  if (!s) return;
  live = undefined;
  setLiveButton(false);
  s.port?.disconnect();
  s.stream?.getTracks().forEach((t) => t.stop());
  if (s.audio && s.audio.state !== "closed") void s.audio.close();
  const n = s.claims.length;
  s.status.classList.remove("live-status");
  s.status.textContent = `Direct terminé · ${n} affirmation${n > 1 ? "s" : ""} vérifiée${n > 1 ? "s" : ""}.`;
  if (n) void saveHistory(s.page, s.claims);
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
  setSuggestions(contextQuestions(res.claims));
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
  if (claim.start !== undefined && page && isVideo(page)) {
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
  if (page && isVideo(page) && claim.start !== undefined) {
    li.dataset.video = mediaKey(page);
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
  if (document.hidden || !isVideo(current) || !current!.claims.length) return;
  const page = current!;
  const [{ result }] = await chrome.scripting.executeScript({
    target: { tabId: page.tabId },
    func: () => (document.querySelector(".ad-showing") ? null : document.querySelector("video")?.currentTime ?? null),
  }).catch(() => [{ result: null }]);
  if (typeof result !== "number") return;
  const cards = [...document.querySelectorAll<HTMLElement>(".claim[data-video]")].filter((c) => c.dataset.video === mediaKey(page));
  let live: HTMLElement | undefined;
  for (const c of cards) if (Number(c.dataset.t) <= result && result - Number(c.dataset.t) < 30) live = c;
  cards.forEach((c) => c.classList.toggle("live", c === live));
}

// --- Chat ----------------------------------------------------------------------

async function ask(text: string): Promise<void> {
  text = text.trim();
  if (!text || busy) return;
  if ((text === "Analyser la page" || text === "Vérifier cette page") && current) {
    setSuggestions(contextQuestions(current.claims));
    userMessage(text);
    return autoCheck(current);
  }
  busy = true;
  $<HTMLButtonElement>("send").disabled = true;
  $<HTMLTextAreaElement>("question").value = "";
  fitInput();
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

// --- Suggestions de questions (elles tournent toutes les quelques secondes) -------

const GENERIC_QUESTIONS = [
  "Quel est le taux de chômage aujourd'hui ?",
  "Quelle est l'inflation sur un an ?",
  "Où en est la dette publique ?",
  "Le chômage des jeunes a-t-il baissé depuis 2017 ?",
  "Combien de demandeurs d'emploi en catégorie A ?",
  "Chômage BIT ou France Travail : quelle différence ?",
  "Le taux d'emploi est-il à un niveau record ?",
  "La dette publique dépasse-t-elle 3 500 milliards ?",
  "Comment vérifies-tu les affirmations ?",
];
const CHIPS_SHOWN = 2;
const CHIPS_ROTATE_MS = 5_000;
let chipPool: string[] = [];
let chipPinned: string[] = [];
let chipIndex = 0;

const shuffle = <T,>(items: T[]) => items.map((v) => [Math.random(), v] as const).sort((a, b) => a[0] - b[0]).map(([, v]) => v);

/** Questions liées à ce qu'on vient de vérifier (affirmations fausses ou trompeuses en tête). */
function contextQuestions(claims: Claim[]): string[] {
  const short = (q: string) => (q.length > 48 ? `${q.slice(0, 46).trimEnd()}…` : q);
  const flagged = claims.filter((c) => c.verdict === "faux" || c.verdict === "trompeur").slice(0, 3);
  return [
    ...(claims.length ? ["Résume les verdicts"] : []),
    ...flagged.map((c) => `Pourquoi « ${short(c.quote)} » est ${c.verdict} ?`),
    ...(claims.some((c) => c.sources.some((s) => s.official)) ? ["Quelles sources officielles as-tu utilisées ?"] : []),
  ];
}

/** `pinned` reste affiché (actions) ; le reste défile, questions du contexte d'abord. */
function setSuggestions(context: string[], pinned: string[] = []): void {
  chipPinned = pinned;
  chipPool = [...context, ...shuffle(GENERIC_QUESTIONS.filter((q) => !context.includes(q)))];
  chipIndex = 0;
  renderChips();
}

function renderChips(): void {
  const shown = Array.from({ length: Math.min(CHIPS_SHOWN, chipPool.length) }, (_, i) => chipPool[(chipIndex + i) % chipPool.length]);
  $("chips").replaceChildren(...[...chipPinned, ...shown].map((label, i) => {
    const chip = el("button", { className: `chip${i < chipPinned.length ? " pinned" : ""}` }, label);
    chip.addEventListener("click", () => void ask(label));
    return chip;
  }));
}

function rotateChips(): void {
  const box = $("chips");
  if (document.hidden || box.matches(":hover") || chipPool.length <= CHIPS_SHOWN) return;
  box.classList.add("fading");
  setTimeout(() => {
    chipIndex = (chipIndex + CHIPS_SHOWN) % chipPool.length;
    renderChips();
    box.classList.remove("fading");
  }, 250);
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
  // Autres plateformes : pas de paramètre de temps fiable, on rouvre la vidéo au début.
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
      el("span", { className: "history-title" }, `${h.kind === "article" ? "📄" : "▶"} ${h.title}`),
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
      h.claims.filter(bad).map((claim) => ({ claim, seen: { title: h.title, url: h.url, seconds: h.kind !== "article" ? claim.start : undefined } }))),
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

/** Direct demandé par clic droit ou Alt+Maj+L : le service worker a déjà obtenu l'identifiant du flux. */
async function consumePendingLive(): Promise<void> {
  const { pendingLive } = (await chrome.storage.session.get("pendingLive")) as {
    pendingLive?: { tabId: number; streamId?: string; error?: string; at: number };
  };
  if (!pendingLive || Date.now() - pendingLive.at > 30_000) return;
  await chrome.storage.session.remove("pendingLive");
  if (live) stopLive();
  await refreshPage();
  if (current?.tabId !== pendingLive.tabId) return;
  void toggleLive(pendingLive.streamId);
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
  const stored = (await chrome.storage.sync.get(["backend", "apiToken"])) as { backend?: string; apiToken?: string };
  backend = stored.backend || DEFAULT_BACKEND;
  apiToken = stored.apiToken ?? "";
  const tokenInput = $<HTMLInputElement>("token");
  tokenInput.value = apiToken;
  tokenInput.addEventListener("change", () => {
    apiToken = tokenInput.value.trim();
    void chrome.storage.sync.set({ apiToken });
  });
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
  $("live").addEventListener("click", () => void toggleLive());
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
    if (changes.pendingLive?.newValue) void consumePendingLive();
  });

  // YouTube change d'URL sans recharger la page : Chrome le signale via onUpdated.
  chrome.tabs.onActivated.addListener(() => void refreshPage());
  chrome.tabs.onUpdated.addListener((_id, change) => { if (change.url || change.status === "complete") void refreshPage(); });
  setInterval(() => void pollPlayback(), TIME_POLL_MS);

  const hello = botMessage("Bonjour ! Je vérifie les affirmations des responsables politiques à partir des données publiques.");
  hello.body.append(el("ul", { className: "hello" },
    el("li", {}, "Ouvrez une vidéo YouTube : je la vérifie toute seule."),
    el("li", {}, "Un article de presse, un TikTok, un Reel, une vidéo X : pareil."),
    el("li", {}, "Un direct, la TV, une vidéo réservée aux abonnés : « ● Direct », ou clic droit → « Vérifier en direct »."),
    el("li", {}, "Une phrase précise : sélectionnez-la, puis clic droit."),
    el("li", {}, "Ensuite, posez vos questions ci-dessous.")));
  setSuggestions([]);
  setInterval(rotateChips, CHIPS_ROTATE_MS);
  await initSession();
  await consumePendingSelection();
  await refreshPage();
  await consumePendingLive();
}

void init();
