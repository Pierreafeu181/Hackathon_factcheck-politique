import type { Segment } from "../../shared/contract.ts";

interface DeepgramResponse {
  results?: {
    utterances?: { start: number; end: number; transcript: string; speaker?: number }[];
  };
}

/**
 * Transcrit un fichier audio à partir de son URL (Deepgram le télécharge lui-même),
 * avec séparation des voix pour distinguer l'invité du journaliste.
 */
export function transcribeUrl(audioUrl: string, apiKey: string, model = "nova-3"): Promise<Segment[]> {
  return listen(JSON.stringify({ url: audioUrl }), "application/json", apiKey, model);
}

/** Transcrit un fichier audio déjà téléchargé (ex. piste audio d'une vidéo YouTube sans sous-titres). */
export function transcribeAudio(audio: Uint8Array, contentType: string, apiKey: string, model = "nova-3"): Promise<Segment[]> {
  return listen(new Blob([new Uint8Array(audio)]), contentType, apiKey, model);
}

async function listen(body: BodyInit, contentType: string, apiKey: string, model: string): Promise<Segment[]> {
  const params = new URLSearchParams({
    model,
    language: "fr",
    diarize: "true",
    utterances: "true",
    smart_format: "true",
    punctuate: "true",
  });
  const res = await fetch(`https://api.deepgram.com/v1/listen?${params}`, {
    method: "POST",
    headers: { Authorization: `Token ${apiKey}`, "Content-Type": contentType },
    body,
  });
  if (!res.ok) throw new Error(`Deepgram : HTTP ${res.status} ${await res.text()}`);
  return utterancesToSegments(await res.json());
}

export function utterancesToSegments(body: DeepgramResponse): Segment[] {
  return (body.results?.utterances ?? []).map((u) => ({
    text: u.transcript,
    start: u.start,
    ...(u.speaker !== undefined && { speaker: String(u.speaker) }),
  }));
}

/** Garde uniquement les phrases de l'invité, supposé être l'intervenant qui parle le plus. */
export function guestSegments(segments: Segment[]): Segment[] {
  const chars = new Map<string, number>();
  for (const s of segments) if (s.speaker) chars.set(s.speaker, (chars.get(s.speaker) ?? 0) + s.text.length);
  if (chars.size === 0) return segments;
  const guest = [...chars].sort((a, b) => b[1] - a[1])[0][0];
  return segments.filter((s) => s.speaker === guest);
}

/**
 * Regroupe les phrases consécutives d'un même intervenant en blocs d'environ `chunkChars` caractères
 * (horodatés au début du bloc), et coupe au-delà de `maxChars` : même format que les sous-titres YouTube.
 */
export function mergeSegments(segments: Segment[], chunkChars = 400, maxChars = 30_000): Segment[] {
  const out: Segment[] = [];
  let total = 0;
  for (const s of segments) {
    if ((total += s.text.length) > maxChars) break;
    const last = out.at(-1);
    if (last && last.speaker === s.speaker && last.text.length < chunkChars) last.text += " " + s.text;
    else out.push({ ...s });
  }
  return out;
}
