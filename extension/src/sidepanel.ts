import type { CheckRequest, CheckResponse, Claim, EpisodeStatus, WatchEpisode, WatchResponse } from "../../shared/contract.ts";
import type { ExtractResult } from "./extract.ts";

const DEFAULT_BACKEND = "http://localhost:8790";
const WATCH_REFRESH_MS = 15_000;

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;

let backend = DEFAULT_BACKEND;
/** Onglet dont viennent les affirmations affichées (pour sauter au bon moment de la vidéo). */
let analyzedTabId: number | undefined;

// --- Appels au serveur ---------------------------------------------------------

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(backend + path, { ...init, headers: { "Content-Type": "application/json" } });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error ?? `Serveur : HTTP ${res.status}`);
  return body as T;
}

const checkClaims = (req: CheckRequest) => api<CheckResponse>("/api/check", { method: "POST", body: JSON.stringify(req) });

// --- Onglet « Cette page » -----------------------------------------------------

async function analyzeTab(tabId: number): Promise<void> {
  setStatus("page-status", "Lecture de la page…");
  $("claims").replaceChildren();
  $<HTMLButtonElement>("analyze").disabled = true;
  try {
    await chrome.scripting.executeScript({ target: { tabId }, files: ["extract.js"] });
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId },
      func: () => (globalThis as any).__verifpolExtract(),
    });
    const extracted = result as ExtractResult;
    if (!extracted.ok) throw new Error(extracted.error);
    if (!extracted.request.segments.length) throw new Error("Aucun texte trouvé sur cette page.");
    setStatus("page-status", `Analyse de ${extracted.request.segments.length} passages…`);
    analyzedTabId = tabId;
    showResult(await checkClaims(extracted.request));
  } catch (err) {
    setStatus("page-status", explain(err), true);
  } finally {
    $<HTMLButtonElement>("analyze").disabled = false;
  }
}

async function analyzeSelection(text: string, url: string, title: string): Promise<void> {
  showTab("page");
  setStatus("page-status", "Analyse de la sélection…");
  $("claims").replaceChildren();
  try {
    analyzedTabId = undefined;
    showResult(await checkClaims({ source: { kind: "selection", url, title }, segments: [{ text }] }));
  } catch (err) {
    setStatus("page-status", explain(err), true);
  }
}

function showResult(res: CheckResponse): void {
  setStatus("page-status", res.claims.length ? `${res.claims.length} affirmation(s) vérifiée(s).` : "Aucune affirmation vérifiable trouvée.");
  const list = $("claims");
  list.replaceChildren(...(res.demo ? [el("li", { className: "demo" }, "Mode démo : verdicts fictifs.")] : []), ...res.claims.map((c) => claimCard(c, analyzedTabId)));
}

function claimCard(claim: Claim, tabId: number | undefined): HTMLElement {
  const head = el("div", { className: "claim-head" }, el("span", { className: `verdict ${claim.verdict}` }, claim.verdict));
  if (claim.start !== undefined && tabId !== undefined) {
    const seek = el("button", { className: "seek", title: "Aller à ce moment de la vidéo" }, `▶ ${formatTime(claim.start)}`);
    seek.addEventListener("click", () => seekVideo(tabId, claim.start!));
    head.append(seek);
  }
  const sources = el("ul", { className: "sources" },
    ...claim.sources.filter((s) => /^https?:\/\//.test(s.url)).map((s) =>
      el("li", {}, el("a", { href: s.url, target: "_blank", rel: "noopener" }, s.label), ...(s.official ? [el("span", { className: "official" }, "source officielle")] : [])),
    ),
  );
  return el("li", { className: "claim" }, head, el("p", { className: "quote" }, `« ${claim.quote} »`), el("p", { className: "explanation" }, claim.explanation), sources);
}

async function seekVideo(tabId: number, seconds: number): Promise<void> {
  await chrome.tabs.update(tabId, { active: true });
  await chrome.scripting.executeScript({
    target: { tabId },
    func: (t: number) => {
      const video = document.querySelector("video");
      if (video) {
        video.currentTime = t;
        void video.play();
      }
    },
    args: [seconds],
  });
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
    el("div", { className: "episode-title" }, el("a", { href: ep.url, target: "_blank", rel: "noopener" }, ep.title)),
  );
  if (ep.error) card.append(el("p", { className: "status error" }, ep.error));
  if (ep.kind === "youtube") {
    const open = el("button", {}, "Ouvrir et vérifier");
    open.addEventListener("click", () => openAndAnalyze(ep.url));
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

/** Ouvre une vidéo dans un nouvel onglet et lance l'analyse une fois la page chargée. */
async function openAndAnalyze(url: string): Promise<void> {
  showTab("page");
  setStatus("page-status", "Ouverture de la vidéo…");
  const tab = await chrome.tabs.create({ url });
  const listener = (tabId: number, info: chrome.tabs.OnUpdatedInfo) => {
    if (tabId !== tab.id || info.status !== "complete") return;
    chrome.tabs.onUpdated.removeListener(listener);
    // Laisser à YouTube le temps d'afficher la description et le bouton de transcription.
    setTimeout(() => void analyzeTab(tabId), 2500);
  };
  chrome.tabs.onUpdated.addListener(listener);
}

// --- Utilitaires ---------------------------------------------------------------

function el<K extends keyof HTMLElementTagNameMap>(tag: K, props: Partial<HTMLElementTagNameMap[K]>, ...children: (Node | string)[]): HTMLElementTagNameMap[K] {
  const node = Object.assign(document.createElement(tag), props);
  node.append(...children);
  return node;
}

function setStatus(id: string, text: string, isError = false): void {
  const node = $(id);
  node.textContent = text;
  node.classList.toggle("error", isError);
}

function explain(err: unknown): string {
  const msg = (err as Error).message ?? String(err);
  if (msg === "Failed to fetch") return `Serveur injoignable (${backend}). Lancez-le avec « npm run dev:server ».`;
  if (msg.includes("Cannot access") || msg.includes("chrome://")) return "Chrome ne permet pas d'analyser cette page.";
  return msg;
}

function formatTime(s: number): string {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = String(Math.floor(s % 60)).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
}

let watchTimer: number | undefined;

function showTab(name: "page" | "watch"): void {
  document.querySelectorAll<HTMLElement>(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  $("tab-page").hidden = name !== "page";
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
  void analyzeSelection(pendingSelection.text, pendingSelection.url, pendingSelection.title);
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

  document.querySelectorAll<HTMLElement>(".tab").forEach((t) => t.addEventListener("click", () => showTab(t.dataset.tab as "page" | "watch")));

  $("analyze").addEventListener("click", async () => {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab?.id !== undefined) void analyzeTab(tab.id);
  });

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
  await consumePendingSelection();
}

void init();
