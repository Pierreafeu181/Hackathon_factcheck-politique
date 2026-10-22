import type { CheckRequest, CheckResponse, Claim, Evidence, Verdict } from "../../shared/contract.ts";

/**
 * Point d'entrée de l'analyse. Si CHECKER_URL est défini, on transmet la requête au moteur
 * de l'équipe ; sinon on répond avec le faux moteur de démo pour que l'extension reste utilisable.
 */
export async function check(req: CheckRequest): Promise<CheckResponse> {
  const url = process.env.CHECKER_URL;
  if (!url) return demoCheck(req);
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!res.ok) throw new Error(`Moteur d'analyse : HTTP ${res.status}`);
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
