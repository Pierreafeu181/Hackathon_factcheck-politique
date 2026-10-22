import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import type { WatchEpisode, WatchResponse } from "../../shared/contract.ts";
import { check } from "./checker.ts";
import { guestSegments, transcribeUrl } from "./deepgram.ts";
import { fetchFeed, type Feed } from "./rss.ts";

interface Options {
  feeds: Feed[];
  statePath: string;
  deepgramKey?: string;
  deepgramModel?: string;
  maxPerFeed: number;
}

interface State {
  episodes: WatchEpisode[];
  lastPollAt?: string;
}

/**
 * Surveille les flux RSS : chaque nouvel épisode de podcast est transcrit par Deepgram,
 * réduit aux phrases de l'invité, puis envoyé à l'analyse. Les vidéos YouTube sont seulement
 * listées : leur transcription se lit depuis l'extension.
 */
export class Watcher {
  private state: State;
  private polling = false;

  constructor(private opts: Options) {
    this.state = load(opts.statePath);
    // Un épisode resté « en cours » vient d'un arrêt du serveur : on le relance.
    for (const ep of this.state.episodes) if (ep.status === "transcription" || ep.status === "analyse") ep.status = "en_attente";
  }

  snapshot(): WatchResponse {
    const episodes = [...this.state.episodes].sort((a, b) => Date.parse(b.publishedAt) - Date.parse(a.publishedAt));
    return { episodes, lastPollAt: this.state.lastPollAt, transcriptionEnabled: Boolean(this.opts.deepgramKey) };
  }

  async poll(): Promise<void> {
    if (this.polling) return;
    this.polling = true;
    try {
      for (const feed of this.opts.feeds) {
        try {
          const items = (await fetchFeed(feed)).slice(0, this.opts.maxPerFeed);
          for (const item of items) {
            if (this.state.episodes.some((e) => e.id === item.id)) continue;
            this.state.episodes.push({
              ...item,
              feedId: feed.id,
              feedName: feed.name,
              kind: feed.kind,
              status: feed.kind === "youtube" ? "a_ouvrir" : "en_attente",
            });
          }
        } catch (err) {
          console.error(`[veille] ${feed.name} :`, (err as Error).message);
        }
      }
      this.state.lastPollAt = new Date().toISOString();
      this.save();
      for (const ep of this.state.episodes.filter((e) => e.status === "en_attente")) await this.process(ep);
    } finally {
      this.polling = false;
    }
  }

  start(intervalMinutes: number): void {
    void this.poll();
    setInterval(() => void this.poll(), intervalMinutes * 60_000);
  }

  private async process(ep: WatchEpisode): Promise<void> {
    if (!this.opts.deepgramKey || !ep.audioUrl) return;
    try {
      this.update(ep, { status: "transcription" });
      const segments = guestSegments(await transcribeUrl(ep.audioUrl, this.opts.deepgramKey, this.opts.deepgramModel));
      this.update(ep, { status: "analyse" });
      const { claims } = await check({ source: { kind: "podcast", url: ep.url, title: ep.title }, segments });
      this.update(ep, { status: "fait", claims });
    } catch (err) {
      this.update(ep, { status: "erreur", error: (err as Error).message });
    }
  }

  private update(ep: WatchEpisode, patch: Partial<WatchEpisode>): void {
    Object.assign(ep, patch);
    console.log(`[veille] ${ep.feedName} – ${ep.title} : ${ep.status}`);
    this.save();
  }

  private save(): void {
    mkdirSync(dirname(this.opts.statePath), { recursive: true });
    writeFileSync(this.opts.statePath, JSON.stringify(this.state, null, 2));
  }
}

function load(path: string): State {
  try {
    return JSON.parse(readFileSync(path, "utf8"));
  } catch {
    return { episodes: [] };
  }
}
