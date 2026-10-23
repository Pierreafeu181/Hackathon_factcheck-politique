import { isIP } from "node:net";

/**
 * Quotas journaliers en mémoire, par client et au total. Accès public (sans clé) : protège les quotas
 * Gemini, le crédit Deepgram et le crédit Aiven contre un usage abusif. Remis à zéro chaque jour (UTC).
 */
export class DailyLimiter {
  private day = "";
  private counts = new Map<string, number>();
  private total = 0;

  constructor(private perClient: number, private global: number) {}

  /** Consomme une unité ; renvoie false si le client ou le total a atteint sa limite du jour. */
  take(client: string): boolean {
    const today = new Date().toISOString().slice(0, 10);
    if (today !== this.day) {
      this.day = today;
      this.counts.clear();
      this.total = 0;
    }
    const used = this.counts.get(client) ?? 0;
    if (used >= this.perClient || this.total >= this.global) return false;
    if (!this.counts.has(client) && this.counts.size >= 50_000) {
      this.counts.delete(this.counts.keys().next().value!); // garde-fou mémoire : on oublie le plus ancien
    }
    this.counts.set(client, used + 1);
    this.total++;
    return true;
  }
}

const PRIVATE = /^(10\.|127\.|192\.168\.|169\.254\.|172\.(1[6-9]|2\d|3[01])\.|100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.|::1$|f[cd][0-9a-f]{2}:|fe80:)/i;

/**
 * IP du visiteur derrière les proxys de l'hébergeur. Le client peut écrire ce qu'il veut au début de
 * X-Forwarded-For ; les proxys ajoutent à la fin. On lit donc depuis la droite en sautant les adresses
 * de réseau privé (proxys internes) : la première adresse publique est celle du visiteur.
 */
export function clientIp(forwarded: string | undefined, direct: string | undefined, maxHops = 3): string {
  const chain = (forwarded ?? "").split(",").map((s) => s.trim().replace(/^::ffff:/, "")).filter(Boolean);
  // Au plus `maxHops` proxys internes sautés ; jamais l'élément le plus à gauche par défaut (écrit par le client).
  for (let i = chain.length - 1, hops = 0; i >= 0 && hops <= maxHops; i--, hops++) {
    if (!isIP(chain[i])) return direct || "inconnu";
    if (!PRIVATE.test(chain[i])) return chain[i];
  }
  return direct || "inconnu";
}
