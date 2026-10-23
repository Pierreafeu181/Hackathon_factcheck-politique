import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import type { CheckRequest, CheckResponse } from "../../shared/contract.ts";

/**
 * Garde les résultats d'analyse par page et par orateur : la vérification automatique de
 * l'extension repasse souvent sur les mêmes vidéos, et chaque analyse coûte des appels à Claude.
 * Les réponses du faux moteur de démo ne sont pas gardées.
 */
export class CheckCache {
  private entries: Record<string, CheckResponse>;

  constructor(private path: string) {
    try {
      this.entries = JSON.parse(readFileSync(path, "utf8"));
    } catch {
      this.entries = {};
    }
  }

  async get(req: CheckRequest, run: () => Promise<CheckResponse>, force = false): Promise<CheckResponse> {
    const key = `${req.source.url}|${req.politician?.name ?? ""}`;
    if (!force && this.entries[key]) return this.entries[key];
    // Orateur inconnu côté extension : la même vidéo déjà analysée (ex. pré-analyse de démo) suffit.
    if (!force && !req.politician?.name) {
      const known = Object.keys(this.entries).find((k) => k.startsWith(`${req.source.url}|`));
      if (known) return this.entries[known];
    }
    const res = await run();
    if (!res.demo && req.source.kind !== "selection") {
      this.entries[key] = res;
      mkdirSync(dirname(this.path), { recursive: true });
      writeFileSync(this.path, JSON.stringify(this.entries));
    }
    return res;
  }
}
