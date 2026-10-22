"""POST /check : le backend Python comme « moteur d'analyse » du serveur Node (CHECKER_URL).

Reçoit un CheckRequest (shared/contract.ts), fait tourner le pipeline extraction → vérification,
renvoie un CheckResponse. Le contrat Node n'a que 4 verdicts : on ramène les nôtres dessus et
on garde la nuance dans l'explication.
"""
from __future__ import annotations

import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

from . import db
from .extract import extract_claims
from .models import (Category, CheckClaim, CheckRequest, CheckResponse, ClaimResult, Evidence, ExtractedClaim,
                     Method, Speech, TranscriptSegment, Verdict, Verification)
from .transcript import to_prompt_text, video_id_from_url
from .verify import verify

MAX_CLAIMS = int(os.getenv("CHECK_MAX_CLAIMS", "15"))
# Tous les thèmes : le référentiel couvre l'emploi, le reste part en recherche web.
CATEGORIES = [c for c in Category if c != Category.autre]

VERDICT_MAP = {
    Verdict.vrai: "vrai",
    Verdict.plutot_vrai: "vrai",
    Verdict.imprecis: "trompeur",
    Verdict.trompeur: "trompeur",
    Verdict.faux: "faux",
    Verdict.inverifiable: "invérifiable",
}
NUANCE = {Verdict.plutot_vrai: "Plutôt vrai", Verdict.imprecis: "Imprécis"}
OFFICIAL_DOMAINS = ("insee.fr", "gouv.fr", "dares.travail-emploi.gouv.fr", "francetravail.fr", "assemblee-nationale.fr",
                    "senat.fr", "legifrance.gouv.fr", "ec.europa.eu", "banque-france.fr", "ccomptes.fr", "data.gouv.fr")


def is_official(url: str, method: Method) -> bool:
    if method == Method.referentiel:
        return True
    host = urlparse(url).hostname or ""
    return any(host == d or host.endswith("." + d) for d in OFFICIAL_DOMAINS)


def to_contract(claim_id: str, claim: ExtractedClaim, v: Verification, with_start: bool) -> CheckClaim:
    parts = []
    if v.verdict in NUANCE:
        parts.append(f"{NUANCE[v.verdict]} :")
    parts.append(v.explanation)
    if v.correction:
        parts.append(f"Correction : {v.correction}")
    return CheckClaim(
        id=claim_id,
        quote=claim.quote,
        verdict=VERDICT_MAP[v.verdict],
        explanation=" ".join(parts),
        sources=[Evidence(label=f"{s.publisher} – {s.title}", url=s.url, official=is_official(s.url, v.method))
                 for s in v.sources],
        start=claim.timestamp_start if with_start else None,
    )


def check(req: CheckRequest) -> CheckResponse:
    with_start = any(s.start is not None for s in req.segments)
    segments = [TranscriptSegment(start=s.start or 0.0, text=s.text) for s in req.segments if s.text.strip()]
    speaker = req.politician.name if req.politician else "l'orateur principal (nom non fourni)"

    claims = extract_claims(to_prompt_text(segments), speaker, CATEGORIES, req.date)[:MAX_CLAIMS]
    with ThreadPoolExecutor(max_workers=6) as pool:
        verifications = list(pool.map(lambda c: verify(c, req.date), claims))

    video_id = video_id_from_url(req.source.url) if req.source.kind == "youtube" else None
    speech_id = f"yt:{video_id}" if video_id else "url:" + hashlib.sha1(req.source.url.encode()).hexdigest()[:12]
    ids = [f"{speech_id}#{i}" for i in range(len(claims))]

    if req.politician:  # stockage pour les profils seulement si on sait qui parle
        speech = Speech(id=speech_id, video_id=video_id, url=req.source.url, title=req.source.title,
                        date=req.date, speaker=req.politician)
        db.save_speech(speech, db.dump_transcript(segments))
        for cid, c, v in zip(ids, claims, verifications):
            db.save_result(ClaimResult(id=cid, speech_id=speech_id, claim=c, verification=v), req.politician)

    return CheckResponse(claims=[to_contract(cid, c, v, with_start) for cid, c, v in zip(ids, claims, verifications)])
