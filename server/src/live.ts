import type { IncomingMessage } from "node:http";
import type { Duplex } from "node:stream";
import WebSocket, { WebSocketServer } from "ws";
import type { Claim, CheckRequest, CheckResponse, Segment } from "../../shared/contract.ts";

/**
 * Vérification en direct (WebSocket /api/live).
 *
 * L'extension capture le son de l'onglet (chrome.tabCapture) et envoie des morceaux webm/opus.
 * On les relaie à Deepgram en streaming ; chaque phrase finale revient au panneau, et toutes les
 * ~45 s de parole on envoie le nouveau passage au moteur d'analyse. Les verdicts repartent au panneau.
 *
 * Messages client → serveur : {type:"start", url, title, speaker?, offset?} puis de l'audio binaire,
 * {type:"stop"} pour finir. Serveur → client : {type:"ready"} · {type:"transcript", text, start}
 * · {type:"checking"} · {type:"claims", claims} · {type:"error", error} · {type:"done"}.
 */

const BATCH_CHARS = 700; // ~45 s de parole
const BATCH_MAX_MS = 60_000;
const MAX_SESSION_MS = 2 * 3600_000;

type Start = { type: "start"; url: string; title?: string; speaker?: string; offset?: number };
type Send = (msg: object) => void;

interface LiveOptions {
  deepgramKey?: string;
  model: string;
  check: (req: CheckRequest) => Promise<CheckResponse>;
  allowed: (req: IncomingMessage) => boolean;
}

/** Une phrase finale de Deepgram → segment horodaté (temps du flux + décalage de la vidéo au départ). */
export function resultToSegment(msg: any, offset = 0): Segment | undefined {
  if (msg?.type !== "Results" || !msg.is_final) return undefined;
  const alt = msg.channel?.alternatives?.[0];
  const text = (alt?.transcript ?? "").trim();
  if (!text) return undefined;
  const speakers = new Map<number, number>();
  for (const w of alt.words ?? []) if (typeof w.speaker === "number") speakers.set(w.speaker, (speakers.get(w.speaker) ?? 0) + 1);
  const speaker = [...speakers].sort((a, b) => b[1] - a[1])[0]?.[0];
  return { text, start: Math.round((offset + (msg.start ?? 0)) * 10) / 10, ...(speaker !== undefined && { speaker: String(speaker) }) };
}

/** Accumule les phrases et décide quand envoyer un passage au moteur. */
export class Batcher {
  private pending: Segment[] = [];
  private since = Date.now();
  add(s: Segment): void {
    if (!this.pending.length) this.since = Date.now();
    this.pending.push(s);
  }
  ready(now = Date.now()): boolean {
    const chars = this.pending.reduce((n, s) => n + s.text.length, 0);
    return chars >= BATCH_CHARS || (chars > 80 && now - this.since >= BATCH_MAX_MS);
  }
  take(): Segment[] {
    const out = this.pending;
    this.pending = [];
    return out;
  }
}

export function attachLive(server: { on(event: "upgrade", cb: (req: IncomingMessage, socket: Duplex, head: Buffer) => void): unknown }, opts: LiveOptions): void {
  // Le client annonce « verifpol, <clé> » ; on ne renvoie que « verifpol » (la clé ne repart jamais).
  const wss = new WebSocketServer({ noServer: true, maxPayload: 1024 * 1024,
    handleProtocols: (protocols) => (protocols.has("verifpol") ? "verifpol" : false) });
  let active = 0;
  server.on("upgrade", (req, socket, head) => {
    try {
      if (new URL(req.url ?? "/", "http://x").pathname !== "/api/live") return socket.destroy();
      if (!opts.allowed(req)) {
        socket.write("HTTP/1.1 403 Forbidden\r\n\r\n");
        return socket.destroy();
      }
      wss.handleUpgrade(req, socket, head, (ws) => session(ws));
    } catch {
      socket.destroy(); // une requête malformée ne doit jamais faire tomber le serveur
    }
  });

  function session(client: WebSocket): void {
    const send: Send = (msg) => client.readyState === WebSocket.OPEN && client.send(JSON.stringify(msg));
    if (!opts.deepgramKey) {
      send({ type: "error", error: "Le direct a besoin de Deepgram : ajoutez DEEPGRAM_API_KEY dans server/.env." });
      return client.close();
    }
    if (active >= 1) {
      send({ type: "error", error: "Une vérification en direct est déjà en cours (une seule à la fois)." });
      return client.close();
    }
    active++;
    let start: Start | undefined;
    let dg: WebSocket | undefined;
    const queue: Buffer[] = [];
    const batcher = new Batcher();
    let checking: Promise<void> = Promise.resolve();
    let closed = false;
    const all: Claim[] = [];

    const runCheck = (final = false) => {
      if (!start || (!final && !batcher.ready())) return;
      const segments = batcher.take();
      if (!segments.length) return;
      const s = start;
      checking = checking.then(async () => {
        send({ type: "checking" });
        try {
          const res = await opts.check({ source: { kind: "podcast", url: s.url, title: s.title ?? s.url }, segments,
            ...(s.speaker && { politician: { name: s.speaker } }) });
          // Identifiants uniques sur toute la session (le moteur numérote chaque passage à partir de 0).
          const claims = res.claims.map((c, i) => ({ ...c, id: `${c.id}~${all.length + i}` }));
          all.push(...claims);
          send({ type: "claims", claims, demo: res.demo });
        } catch (err) {
          send({ type: "error", error: `Analyse du passage impossible : ${(err as Error).message}` });
        }
      });
    };
    const timer = setInterval(() => runCheck(), 5_000);
    const maxTimer = setTimeout(() => stop("Durée maximale atteinte (2 h)."), MAX_SESSION_MS);

    const stop = (reason?: string) => {
      if (closed) return;
      closed = true;
      clearInterval(timer);
      clearTimeout(maxTimer);
      if (reason) send({ type: "error", error: reason });
      if (dg?.readyState === WebSocket.OPEN) dg.send(JSON.stringify({ type: "CloseStream" }));
      // Laisse Deepgram renvoyer ses dernières phrases, puis analyse le reste.
      setTimeout(() => {
        dg?.close();
        runCheck(true);
        void checking.then(() => {
          send({ type: "done" });
          client.close();
          active--;
        });
      }, 1500);
    };

    client.on("message", (data, isBinary) => {
      if (closed) return;
      if (!isBinary) {
        let msg: any;
        try {
          msg = JSON.parse(data.toString());
        } catch {
          return;
        }
        if (msg.type === "stop") return stop();
        if (msg.type !== "start" || start || typeof msg.url !== "string" || !/^https?:\/\//.test(msg.url)) return;
        start = { type: "start", url: msg.url.slice(0, 2000), title: String(msg.title ?? "").slice(0, 300),
          speaker: msg.speaker ? String(msg.speaker).slice(0, 120) : undefined, offset: Number(msg.offset) || 0 };
        const params = new URLSearchParams({ model: opts.model, language: "fr", smart_format: "true", punctuate: "true",
          diarize: "true", interim_results: "false" });
        dg = new WebSocket(`wss://api.deepgram.com/v1/listen?${params}`, { headers: { Authorization: `Token ${opts.deepgramKey}` } });
        dg.on("open", () => {
          send({ type: "ready" });
          for (const chunk of queue.splice(0)) dg!.send(chunk);
        });
        dg.on("message", (raw) => {
          let msg: any;
          try {
            msg = JSON.parse(raw.toString());
          } catch {
            return;
          }
          const seg = resultToSegment(msg, start?.offset);
          if (seg) {
            batcher.add(seg);
            send({ type: "transcript", text: seg.text, start: seg.start });
          }
        });
        dg.on("unexpected-response", (_req, res) => stop(`Deepgram a refusé le flux (HTTP ${res.statusCode}).`));
        dg.on("error", (err) => stop(`Deepgram : ${err.message}`));
        dg.on("close", () => { if (!closed) stop("Deepgram a fermé le flux."); });
        return;
      }
      const chunk = data as Buffer;
      if (dg?.readyState === WebSocket.OPEN) dg.send(chunk);
      else if (queue.length < 400) queue.push(chunk);
    });
    client.on("close", () => stop());
    client.on("error", () => stop());
  }
}
