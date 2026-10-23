import { createHash } from "node:crypto";
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

  /**
   * Clé = page + orateur + empreinte du texte envoyé : en accès public, quelqu'un qui enverrait un faux
   * transcript pour une vraie vidéo n'écraserait que sa propre entrée. `trusted` (clé d'admin ou accès local) :
   * l'analyse est aussi enregistrée pour la vidéo entière, et réutilisée quel que soit le texte reçu.
   */
  async get(req: CheckRequest, run: () => Promise<CheckResponse>, force = false, trusted = true): Promise<CheckResponse> {
    const text = createHash("sha256").update(req.segments.map((s) => s.text).join("\n")).digest("hex").slice(0, 16);
    const exact = `${req.source.url}|${req.politician?.name ?? ""}|${text}`;
    const video = `${req.source.url}|*`;
    if (!force) {
      const hit = this.entries[exact] ?? this.entries[video];
      if (hit) return hit;
    }
    const res = await run();
    if (!res.demo && req.source.kind !== "selection") {
      this.entries[exact] = res;
      if (trusted) this.entries[video] = res;
      mkdirSync(dirname(this.path), { recursive: true });
      writeFileSync(this.path, JSON.stringify(this.entries));
    }
    return res;
  }
}
