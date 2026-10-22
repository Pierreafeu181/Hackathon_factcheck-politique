"""API FactCheck Politique. Lancer : uvicorn app.main:app --reload --port 8000
Doc interactive : http://localhost:8000/docs
"""
from __future__ import annotations

import logging
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from . import check_api, db, referentiel
from .extract import extract_claims
from .models import (AnalyzeRequest, AnalyzeResponse, CheckRequest, CheckResponse, ClaimResult, PoliticianProfile,
                     Speech)
from .transcript import fetch_youtube, from_raw_text, to_prompt_text, video_id_from_url
from .verify import verify

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("factcheck")

app = FastAPI(title="FactCheck Politique", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])  # hackathon : extension Chrome
db.init()


@app.get("/health")
def health():
    return {"ok": True, "indicators": len(referentiel.load())}


@app.get("/indicators")
def indicators():
    return {k: {"label": s.label, "unit": s.unit, "last": s.obs[-1], "url": s.url} for k, s in referentiel.load().items()}


# ---------------------------------------------------------------- Lot B + C : analyse


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(req: AnalyzeRequest):
    video_id = req.video_id or (video_id_from_url(req.url) if req.url else None)
    speech_id = f"yt:{video_id}" if video_id else f"txt:{uuid.uuid4().hex[:12]}"

    if not req.force and (cached := db.get_speech(speech_id)):
        speech, results = cached
        return AnalyzeResponse(speech=speech, results=results, stats=_stats(results))

    # 1. transcript
    if isinstance(req.transcript, str):
        segments = from_raw_text(req.transcript)
    elif req.transcript:
        segments = req.transcript
    elif video_id:
        try:
            segments = fetch_youtube(video_id)
        except Exception as e:
            raise HTTPException(422, f"Transcript YouTube indisponible ({e.__class__.__name__}). "
                                     "Envoyer le transcript dans le champ `transcript`.")
    else:
        raise HTTPException(400, "Fournir video_id, url ou transcript.")

    # 2. extraction
    claims = extract_claims(to_prompt_text(segments), req.speaker.name, req.categories, req.date)
    log.info("%s : %d affirmations vérifiables", speech_id, len(claims))

    # 3. vérification (en parallèle)
    with ThreadPoolExecutor(max_workers=6) as pool:
        verifications = list(pool.map(lambda c: verify(c, req.date, req.use_web), claims))

    # 4. stockage
    speech = Speech(id=speech_id, video_id=video_id, url=req.url, title=req.title, date=req.date, speaker=req.speaker)
    db.save_speech(speech, db.dump_transcript(segments))
    results = [ClaimResult(id=f"{speech_id}#{i}", speech_id=speech_id, claim=c, verification=v)
               for i, (c, v) in enumerate(zip(claims, verifications))]
    for r in results:
        db.save_result(r, req.speaker)
    return AnalyzeResponse(speech=speech, results=results, stats=_stats(results))


def _stats(results: list[ClaimResult]) -> dict[str, int]:
    return dict(Counter(r.verification.verdict.value for r in results))


@app.post("/check", response_model=CheckResponse, response_model_exclude_none=True)
def check(req: CheckRequest):
    """Moteur d'analyse du serveur Node : mettre CHECKER_URL=http://localhost:8000/check dans server/.env"""
    if not any(s.text.strip() for s in req.segments):
        raise HTTPException(400, "Aucun texte à analyser.")
    return check_api.check(req)


@app.get("/videos/{video_id}/claims", response_model=AnalyzeResponse)
def video_claims(video_id: str):
    found = db.get_speech(f"yt:{video_id}")
    if not found:
        raise HTTPException(404, "Vidéo pas encore analysée")
    speech, results = found
    return AnalyzeResponse(speech=speech, results=results, stats=_stats(results))


# ---------------------------------------------------------------- Lot D : profils


@app.get("/politicians", response_model=list[PoliticianProfile])
def politicians():
    return db.list_politicians()


@app.get("/politicians/{pid}", response_model=PoliticianProfile)
def politician(pid: str):
    p = db.profile(pid)
    if not p:
        raise HTTPException(404, "Inconnu")
    return p
