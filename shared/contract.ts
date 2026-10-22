// Format d'échange entre l'extension, le serveur de veille et le moteur d'analyse.
// C'est le seul fichier que les trois parties doivent respecter : toute modification
// se discute en équipe.

export type Verdict = "vrai" | "trompeur" | "faux" | "invérifiable";

export type SourceKind = "article" | "youtube" | "selection" | "podcast";

/** Un morceau de texte à analyser. `start` est en secondes (vidéo ou audio). */
export interface Segment {
  text: string;
  start?: number;
  speaker?: string;
}

/** POST /api/check */
export interface CheckRequest {
  source: {
    kind: SourceKind;
    url: string;
    title?: string;
  };
  segments: Segment[];
  /** Qui parle. Si fourni, le moteur Python stocke le résultat pour les profils. */
  politician?: { name: string; party?: string };
  /** Date du discours, AAAA-MM-JJ. */
  date?: string;
}

export interface Evidence {
  label: string;
  url: string;
  /** true si la source est une donnée officielle (INSEE, Assemblée, Légifrance…). */
  official: boolean;
}

export interface Claim {
  id: string;
  /** La phrase exacte telle que prononcée ou écrite. */
  quote: string;
  verdict: Verdict;
  explanation: string;
  sources: Evidence[];
  /** Moment (en secondes) où la phrase est dite, si connu. */
  start?: number;
}

export interface CheckResponse {
  claims: Claim[];
  /** true quand la réponse vient du faux moteur de démo. */
  demo?: boolean;
}

export type EpisodeStatus =
  | "en_attente"
  | "transcription"
  | "analyse"
  | "fait"
  | "erreur"
  /** Vidéo YouTube : le serveur ne peut pas lire la transcription, il faut l'ouvrir avec l'extension. */
  | "a_ouvrir";

export interface WatchEpisode {
  id: string;
  feedId: string;
  feedName: string;
  kind: "podcast" | "youtube";
  title: string;
  /** Page de l'épisode ou de la vidéo. */
  url: string;
  audioUrl?: string;
  publishedAt: string;
  status: EpisodeStatus;
  error?: string;
  claims?: Claim[];
}

/** GET /api/watch */
export interface WatchResponse {
  episodes: WatchEpisode[];
  lastPollAt?: string;
  transcriptionEnabled: boolean;
}

/** POST /api/chat (serveur Node → moteur Python /chat) */
export interface ChatRequest {
  messages: { role: "user" | "assistant"; content: string }[];
  video_id?: string;
  title?: string;
  speaker?: string;
  /** Verdicts déjà affichés, donnés au chat comme contexte. */
  claims?: Claim[];
}

export interface ChatResponse {
  answer: string;
  sources: { title: string; url: string }[];
  /** true quand la réponse vient du faux chat de démo. */
  demo?: boolean;
}
