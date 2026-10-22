"""Lot B — Récupération du transcript.

Ordre de priorité :
1. transcript fourni dans la requête (envoyé par l'extension ou collé à la main) ;
2. youtube-transcript-api (marche depuis une IP perso, souvent bloqué depuis le cloud).
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from .models import TranscriptSegment

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
        buf.append(s.text.replace("\n", " "))
    if buf:
        out.append(f"[{int(start)}s] " + " ".join(buf))
    return "\n".join(out)
