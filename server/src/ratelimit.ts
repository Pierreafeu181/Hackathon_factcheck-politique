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
    this.counts.set(client, used + 1);
    this.total++;
    if (this.counts.size > 50_000) this.counts.clear(); // garde-fou mémoire
    return true;
  }
}

/** IP du client derrière le proxy de l'hébergeur (premier élément de X-Forwarded-For), sinon l'adresse directe. */
export function clientIp(forwarded: string | undefined, direct: string | undefined): string {
  return (forwarded?.split(",")[0] ?? "").trim() || direct || "inconnu";
}
