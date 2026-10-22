import { spawn } from "node:child_process";
import { mkdtemp, readdir, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

/** Identifiant de vidéo YouTube (11 caractères). */
export const YOUTUBE_ID = /^[A-Za-z0-9_-]{11}$/;

const MAX_BYTES = 200 * 1024 * 1024;
const TIMEOUT_MS = 3 * 60_000;

/** Plateformes vidéo prises en charge (même liste que VIDEO_PAGES dans l'extension, plus YouTube). */
export const VIDEO_HOSTS = [
  "youtube.com", "youtu.be", "tiktok.com", "instagram.com", "x.com", "twitter.com", "facebook.com", "fb.watch",
  "dailymotion.com", "dai.ly", "vimeo.com", "twitch.tv", "france.tv", "arte.tv", "rumble.com", "linkedin.com",
  "threads.net", "threads.com",
];

/**
 * Adresse de vidéo acceptée : https/http sur une plateforme connue uniquement. yt-dlp télécharge depuis ce Mac :
 * une liste blanche (plutôt qu'une liste noire d'IP privées, contournable par DNS ou redirection) évite
 * d'en faire un relais vers le réseau local.
 */
export function mediaUrl(raw: string): string {
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    throw new Error("Adresse de vidéo invalide.");
  }
  const host = url.hostname.toLowerCase();
  const known = VIDEO_HOSTS.some((h) => host === h || host.endsWith(`.${h}`));
  if (!/^https?:$/.test(url.protocol) || url.username || url.password || url.port || !known) {
    throw new Error("Plateforme vidéo non prise en charge.");
  }
  url.hash = "";
  return url.href;
}

/**
 * Télécharge la piste audio d'une vidéo avec yt-dlp, puis ffmpeg la convertit en m4a léger
 * (brew install yt-dlp ffmpeg) : YouTube, TikTok, Instagram, X, Facebook, Dailymotion, Vimeo, Twitch,
 * france.tv… Ça marche depuis le Mac de l'utilisateur, alors que les plateformes bloquent souvent les
 * serveurs hébergés. Le lien audio obtenu n'est valable que pour l'IP qui l'a demandé : on ne peut pas
 * le passer à Deepgram, on télécharge le fichier.
 */
export async function downloadAudio(rawUrl: string, maxSeconds = 7200): Promise<{ audio: Buffer; contentType: string }> {
  const url = mediaUrl(rawUrl);
  const dir = await mkdtemp(join(tmpdir(), "verifpol-"));
  try {
    const args = [
      "--ignore-config", "--no-playlist", "--quiet", "--no-warnings",
      // piste audio seule si elle existe, sinon la plus petite vidéo avec du son (Dailymotion, X…)
      "-f", "bestaudio/worst[acodec!=none]/worst",
      "--max-filesize", `${MAX_BYTES}`,
      "--match-filter", `duration<=?${maxSeconds}`, // « ? » : accepté si la plateforme ne donne pas la durée
      // Instagram, Facebook… exigent souvent un compte : option explicite pour réutiliser la session d'un navigateur.
      ...(process.env.YTDLP_COOKIES_FROM_BROWSER ? ["--cookies-from-browser", process.env.YTDLP_COOKIES_FROM_BROWSER] : []),
      "-x", "--audio-format", "m4a", "--audio-quality", "7",
      "-o", join(dir, "audio.%(ext)s"),
      "--", url,
    ];
    await run(process.env.YTDLP_PATH || "yt-dlp", args);
    const file = (await readdir(dir)).find((f) => f.startsWith("audio."));
    if (!file) throw new Error(`Vidéo trop longue (plus de ${maxSeconds / 3600} h), trop lourde ou indisponible.`);
    return { audio: await readFile(join(dir, file)), contentType: "audio/mp4" };
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

function run(bin: string, args: string[]): Promise<void> {
  return new Promise((resolve, reject) => {
    const child = spawn(bin, args, { stdio: ["ignore", "ignore", "pipe"] });
    let stderr = "";
    let failure: Error | undefined;
    const timer = setTimeout(() => {
      failure = new Error("Téléchargement de l'audio trop long (plus de 3 min).");
      child.kill("SIGKILL");
    }, TIMEOUT_MS);
    child.stderr.on("data", (c: Buffer) => (stderr = (stderr + c.toString()).slice(-800)));
    child.on("error", (err: NodeJS.ErrnoException) => {
      failure ??= err.code === "ENOENT" ? new Error("yt-dlp n'est pas installé sur le serveur (brew install yt-dlp ffmpeg).") : err;
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      if (failure) return reject(failure);
      if (code !== 0) return reject(new Error(`La plateforme a refusé le téléchargement de l'audio (${explainYtdlp(stderr) || `code ${code}`}).`));
      resolve();
    });
  });
}

/** Messages d'erreur yt-dlp les plus courants, en clair. */
function explainYtdlp(stderr: string): string {
  if (/log ?in|cookies|private|authentication/i.test(stderr)) {
    return "vidéo privée ou réservée aux comptes connectés ; voir YTDLP_COOKIES_FROM_BROWSER dans server/.env.example";
  }
  if (/unsupported url/i.test(stderr)) return "plateforme non prise en charge";
  if (/no video formats|no formats|no video could be found/i.test(stderr)) return "aucune vidéo dans cette page";
  if (/ffmpeg|ffprobe/i.test(stderr)) return "ffmpeg manquant (brew install ffmpeg)";
  return stderr.replace(/^ERROR:\s*/m, "").trim().slice(0, 200);
}
