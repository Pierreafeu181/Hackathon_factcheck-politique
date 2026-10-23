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

/**
 * IP du client derrière le proxy de l'hébergeur. Le client peut écrire ce qu'il veut au début de
 * X-Forwarded-For : seule la valeur ajoutée par notre proxy compte, en comptant depuis la droite
 * (TRUSTED_PROXY_HOPS, 1 par défaut = dernier élément). Sans en-tête : l'adresse de la connexion.
 */
export function clientIp(forwarded: string | undefined, direct: string | undefined, hops = Number(process.env.TRUSTED_PROXY_HOPS ?? 1)): string {
  const chain = (forwarded ?? "").split(",").map((s) => s.trim()).filter(Boolean);
  return chain[chain.length - Math.max(1, hops)] || chain[0] || direct || "inconnu";
}
