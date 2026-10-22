import { spawn } from "node:child_process";

/** Identifiant de vidéo YouTube (11 caractères). Vérifié avant de le passer à yt-dlp. */
export const YOUTUBE_ID = /^[A-Za-z0-9_-]{11}$/;

const MAX_BYTES = 200 * 1024 * 1024;
const TIMEOUT_MS = 3 * 60_000;

/**
 * Télécharge la piste audio d'une vidéo YouTube avec yt-dlp (doit être installé : brew install yt-dlp).
 * Ça marche depuis le Mac de l'utilisateur, alors que YouTube bloque les serveurs hébergés.
 * On ne peut pas passer le lien audio à Deepgram : il n'est valable que pour l'IP qui l'a demandé.
 */
export function downloadYoutubeAudio(videoId: string, maxSeconds = 7200): Promise<{ audio: Buffer; contentType: string }> {
  if (!YOUTUBE_ID.test(videoId)) return Promise.reject(new Error("Identifiant de vidéo YouTube invalide."));
  const args = [
    "-f", "bestaudio[ext=m4a]/bestaudio",
    "--no-playlist", "--quiet", "--no-warnings",
    "--match-filter", `duration<=${maxSeconds}`,
    "-o", "-",
    `https://www.youtube.com/watch?v=${videoId}`,
  ];
  return new Promise((resolve, reject) => {
    const child = spawn(process.env.YTDLP_PATH || "yt-dlp", args, { stdio: ["ignore", "pipe", "pipe"] });
    const chunks: Buffer[] = [];
    let size = 0;
    let stderr = "";
    let failure: Error | undefined;
    const stop = (err: Error) => {
      failure ??= err;
      child.kill("SIGKILL");
    };
    const timer = setTimeout(() => stop(new Error("Téléchargement de l'audio trop long (plus de 3 min).")), TIMEOUT_MS);
    child.stdout.on("data", (c: Buffer) => {
      size += c.length;
      if (size > MAX_BYTES) stop(new Error("Piste audio trop volumineuse."));
      else chunks.push(c);
    });
    child.stderr.on("data", (c: Buffer) => (stderr = (stderr + c.toString()).slice(-500)));
    child.on("error", (err: NodeJS.ErrnoException) =>
      stop(err.code === "ENOENT" ? new Error("yt-dlp n'est pas installé sur le serveur (brew install yt-dlp).") : err));
    child.on("close", (code) => {
      clearTimeout(timer);
      if (failure) return reject(failure);
      if (code !== 0) return reject(new Error(`YouTube a refusé le téléchargement de l'audio (${stderr.trim() || `code ${code}`}).`));
      if (!size) return reject(new Error(`Vidéo trop longue (plus de ${maxSeconds / 3600} h) ou indisponible.`));
      resolve({ audio: Buffer.concat(chunks), contentType: "audio/mp4" });
    });
  });
}
