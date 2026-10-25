import { request as httpRequest } from "node:http";
import { request as httpsRequest } from "node:https";
import type { ChatRequest, ChatResponse, CheckRequest, CheckResponse, Claim, Evidence, Verdict } from "../../shared/contract.ts";

/** Délai maximal d'une analyse par le moteur (une longue interview peut dépasser 5 min, le délai par défaut de fetch). */
const ENGINE_TIMEOUT_MS = Number(process.env.ENGINE_TIMEOUT_MS) || 15 * 60_000;

/** POST JSON sans le délai de 5 min de fetch (undici) : seul ENGINE_TIMEOUT_MS s'applique. */
export function postJson(url: string, body: unknown, timeoutMs = ENGINE_TIMEOUT_MS,
  extraHeaders: Record<string, string> = {}): Promise<{ status: number; text: string }> {
  return new Promise((resolve, reject) => {
    const data = Buffer.from(JSON.stringify(body));
    const send = url.startsWith("https:") ? httpsRequest : httpRequest;
    const headers = { "Content-Type": "application/json", "Content-Length": String(data.length), ...extraHeaders };
    const req = send(url, { method: "POST", headers }, (res) => {
      const chunks: Buffer[] = [];
      res.on("data", (c: Buffer) => chunks.push(c));
      res.on("end", () => resolve({ status: res.statusCode ?? 0, text: Buffer.concat(chunks).toString("utf8") }));
      res.on("error", reject);
    });
    req.setTimeout(timeoutMs, () => req.destroy(new Error(`délai dépassé (${Math.round(timeoutMs / 60_000)} min)`)));
    req.on("error", reject);
    req.end(data);
  });
}

/**
 * Point d'entrée de l'analyse. Si CHECKER_URL est défini, on transmet la requête au moteur
 * de l'équipe ; sinon on répond avec le faux moteur de démo pour que l'extension reste utilisable.
 */
/**
 * `trusted` : analyse faite avec la clé d'administration (ou serveur local) ; seule celle-ci alimente les profils publics
 * et la mémoire des affirmations côté moteur. L'en-tête est posé ici, jamais recopié depuis la requête du client.
 */
export async function check(req: CheckRequest, trusted = false): Promise<CheckResponse> {
  const url = process.env.CHECKER_URL;
  if (!url) return demoCheck(req);
  const res = await postJson(url, req, ENGINE_TIMEOUT_MS, { "X-VerifPol-Trusted": trusted ? "1" : "0" });
  if (res.status !== 200) throw new Error(engineError("Moteur d'analyse", res));
  return JSON.parse(res.text) as CheckResponse;
}

/** Message d'erreur du moteur à montrer tel quel (ex. quota du jour épuisé), sinon le code HTTP. */
export function engineError(what: string, res: { status: number; text: string }): string {
  try {
    const detail = (JSON.parse(res.text) as { detail?: unknown }).detail;
    if (typeof detail === "string" && detail) return detail;
  } catch { /* pas du JSON */ }
  return `${what} : HTTP ${res.status}`;
}

/**
 * Questions du chat : transmises à CHAT_URL, ou par défaut à la route /chat du moteur de CHECKER_URL.
 * Sans moteur, une réponse de démo explique comment le brancher.
 */
export async function chat(req: ChatRequest): Promise<ChatResponse> {
  const url = process.env.CHAT_URL || (process.env.CHECKER_URL ? new URL("/chat", process.env.CHECKER_URL).href : "");
  if (!url) {
    return {
      answer: "[Démo] Le chat n'est pas branché. Lancez le backend Python et mettez CHECKER_URL=http://localhost:8000/check dans server/.env.",
      sources: [],
      demo: true,
    };
  }
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!res.ok) throw new Error(engineError("Chat", { status: res.status, text: await res.text() }));
  return res.json();
}

// --- Faux moteur de démo -------------------------------------------------------

const MAX_DEMO_CLAIMS = 8;

const OFFICIAL_SOURCES: [RegExp, Evidence][] = [
  [/chômage|emploi/i, { label: "INSEE – Taux de chômage (BIT)", url: "https://www.insee.fr/fr/statistiques/serie/001688527", official: true }],
  [/inflation|prix|pouvoir d'achat/i, { label: "INSEE – Indice des prix à la consommation (base 2015)", url: "https://www.insee.fr/fr/statistiques/serie/001759970", official: true }],
  [/dette|déficit/i, { label: "INSEE – Dette publique en % du PIB (Maastricht)", url: "https://www.insee.fr/fr/statistiques/serie/010777608", official: true }],
  [/vot|amendement|assemblée|loi/i, { label: "Assemblée nationale – Scrutins", url: "https://www.assemblee-nationale.fr/dyn/17/scrutins", official: true }],
];

const VERDICTS: Verdict[] = ["vrai", "trompeur", "faux", "invérifiable"];

/** Découpe en phrases, garde celles qui contiennent un chiffre, et invente un verdict stable. */
export function demoCheck(req: CheckRequest): CheckResponse {
  const claims: Claim[] = [];
  for (const segment of req.segments) {
    for (const sentence of splitSentences(segment.text)) {
      if (!/\d/.test(sentence) || claims.length >= MAX_DEMO_CLAIMS) continue;
      const sources = OFFICIAL_SOURCES.filter(([re]) => re.test(sentence)).map(([, ev]) => ev);
      claims.push({
        id: `demo-${claims.length}`,
        quote: sentence,
        verdict: sources.length ? VERDICTS[hash(sentence) % 3] : "invérifiable",
        explanation: "[Démo] Verdict fictif : le moteur d'analyse n'est pas encore branché (CHECKER_URL).",
        sources,
        ...(segment.start !== undefined && { start: segment.start }),
      });
    }
  }
  return { claims, demo: true };
}

function splitSentences(text: string): string[] {
  return (text.match(/[^.!?…]+[.!?…]*/g) ?? []).map((s) => s.trim()).filter(Boolean);
}

function hash(s: string): number {
  let h = 0;
  for (const c of s) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return h;
}
