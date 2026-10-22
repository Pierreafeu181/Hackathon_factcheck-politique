"""Lot B — Récupération du transcript.

Ordre de priorité :
1. transcript fourni dans la requête (envoyé par l'extension ou collé à la main) ;
2. youtube-transcript-api (marche depuis une IP perso, souvent bloqué depuis le cloud) ;
3. transcription de l'audio par ElevenLabs Scribe, avec diarisation (vidéo sans sous-titres).
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .models import TranscriptSegment

AUDIO_MAX_SECONDS = int(os.getenv("AUDIO_MAX_SECONDS", "1200"))  # 20 min d'audio au plus par vidéo
SEGMENT_MAX_SECONDS = 30.0
PAUSE_SECONDS = 1.0

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def video_id_from_url(url: str) -> str | None:
    if _ID_RE.match(url):
        return url
    u = urlparse(url)
    if u.hostname in {"youtu.be"}:
        return u.path.lstrip("/")[:11] or None
    if u.hostname and "youtube" in u.hostname:
        if u.path == "/watch":
            return parse_qs(u.query).get("v", [None])[0]
        m = re.match(r"^/(?:live|shorts|embed)/([A-Za-z0-9_-]{11})", u.path)
        if m:
            return m.group(1)
    return None


def fetch_youtube(video_id: str, languages: tuple[str, ...] = ("fr", "en")) -> list[TranscriptSegment]:
    from youtube_transcript_api import YouTubeTranscriptApi  # import local : dépendance lourde

    fetched = YouTubeTranscriptApi().fetch(video_id, languages=list(languages))
    return [TranscriptSegment(start=s.start, duration=s.duration, text=s.text) for s in fetched]


def fetch_audio_segments(video_id: str, max_seconds: int = AUDIO_MAX_SECONDS) -> list[TranscriptSegment]:
    """Télécharge l'audio (yt-dlp) et le transcrit avec ElevenLabs Scribe v2, voix séparées."""
    import imageio_ffmpeg  # imports locaux : dépendances lourdes, inutiles si l'extension fournit le texte
    import yt_dlp
    from elevenlabs.client import ElevenLabs

    key = os.getenv("ELEVENLABS_API_KEY")
    if not key:
        raise RuntimeError("Pas de transcription YouTube et ELEVENLABS_API_KEY absente : impossible de transcrire l'audio.")
    with tempfile.TemporaryDirectory() as tmp:
        # Audio le plus léger, puis coupe à max_seconds avec le ffmpeg embarqué par imageio-ffmpeg
        # (le téléchargement partiel de yt-dlp exige un ffmpeg installé sur la machine).
        opts = {"format": "worstaudio[acodec!=none]/bestaudio/best", "outtmpl": f"{tmp}/source.%(ext)s",
                "quiet": True, "noprogress": True, "retries": 5, "fragment_retries": 5}
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
        source = next(Path(tmp).glob("source.*"))
        audio = Path(tmp) / "clip.flac"
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-i", str(source), "-t", str(max_seconds),
                        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "flac", str(audio)], check=True)
        with audio.open("rb") as f:
            result = ElevenLabs(api_key=key).speech_to_text.convert(
                file=f, model_id="scribe_v2", language_code="fr", diarize=True, timestamps_granularity="word")
    return words_to_segments(result.words or [])


def _field(word: Any, name: str) -> Any:
    return word.get(name) if isinstance(word, dict) else getattr(word, name, None)


def words_to_segments(words: list[Any], offset: float = 0.0) -> list[TranscriptSegment]:
    """Regroupe les mots horodatés en segments : nouveau segment à chaque changement de voix,
    après une pause de plus d'1 s, ou au-delà de 30 s."""
    voices: dict[str, str] = {}
    segments: list[TranscriptSegment] = []
    text: list[str] = []
    start = end = 0.0
    speaker: str | None = None

    def flush() -> None:
        if re.search(r"\w", "".join(text)):  # ignore les segments réduits à une ponctuation
            segments.append(TranscriptSegment(start=round(offset + start, 2), duration=round(end - start, 2),
                                              text="".join(text).strip(), speaker=speaker))
        text.clear()

    for word in words:
        kind = _field(word, "type") or "word"
        if kind == "audio_event":
            continue
        if kind == "spacing":
            text.append(_field(word, "text") or " ")
            continue
        raw = _field(word, "speaker_id")
        voice = voices.setdefault(raw, f"Voix {len(voices) + 1}") if raw else None
        w_start, w_end = float(_field(word, "start") or 0.0), float(_field(word, "end") or 0.0)
        if text and (voice != speaker or w_start - end > PAUSE_SECONDS or w_end - start > SEGMENT_MAX_SECONDS):
            flush()
        if not text:
            start, speaker = w_start, voice
        text.append(_field(word, "text") or "")
        end = w_end
    flush()
    return segments


def from_raw_text(text: str) -> list[TranscriptSegment]:
    """Transcript collé à la main : pas de timestamps, on découpe par lignes non vides."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    return [TranscriptSegment(start=0.0, text=l) for l in lines]


def to_prompt_text(segments: list[TranscriptSegment], window: float = 20.0) -> str:
    """Regroupe les segments par fenêtres de ~20 s, préfixées de [123s], pour que le LLM
    puisse renvoyer un timestamp_start exploitable par l'extension."""
    out: list[str] = []
    buf: list[str] = []
    start = segments[0].start if segments else 0.0
    for s in segments:
        if buf and s.start - start >= window:
            out.append(f"[{int(start)}s] " + " ".join(buf))
            buf, start = [], s.start
        text = s.text.replace("\n", " ")
        buf.append(f"({s.speaker}) {text}" if s.speaker else text)
    if buf:
        out.append(f"[{int(start)}s] " + " ".join(buf))
    return "\n".join(out)
