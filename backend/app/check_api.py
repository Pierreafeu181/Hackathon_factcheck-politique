"""POST /check : le backend Python comme « moteur d'analyse » du serveur Node (CHECKER_URL).

Reçoit un CheckRequest (shared/contract.ts), fait tourner le pipeline extraction → vérification,
renvoie un CheckResponse. Le contrat Node n'a que 4 verdicts : on ramène les nôtres dessus et
on garde la nuance dans l'explication.
"""
from __future__ import annotations

import hashlib
import os
import re
import unicodedata
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, wait
from urllib.parse import urlparse

from . import db
from .extract import extract_claims
from .models import (Category, CheckClaim, CheckRequest, CheckResponse, ClaimResult, Evidence, ExtractedClaim,
                     Method, Speech, TranscriptSegment, Verdict, Verification)
from .transcript import to_prompt_text, video_id_from_url
from .verify import verify

MAX_CLAIMS = int(os.getenv("CHECK_MAX_CLAIMS", "15"))
# Au-delà, on répond avec ce qui est prêt : les recherches continuent et leurs résultats, gardés en mémoire (verify.py),
# servent à la prochaine analyse. Personne n'attend 10 min devant le panneau.
DEADLINE_S = float(os.getenv("CHECK_DEADLINE_S", "240"))
PENDING = ("Vérification encore en cours au moment de répondre (recherche dans les sources officielles) : "
           "relancez l'analyse dans quelques minutes pour obtenir le verdict.")
BUSY = "Serveur très sollicité : cette affirmation n'a pas pu être vérifiée maintenant. Relancez l'analyse un peu plus tard."
_pool = ThreadPoolExecutor(max_workers=int(os.getenv("CHECK_WORKERS", "6")))
# File partagée entre toutes les requêtes : bornée, pour qu'une longue vidéo ne retarde pas indéfiniment les autres.
MAX_BACKLOG = int(os.getenv("CHECK_MAX_BACKLOG", "30"))
_backlog = threading.BoundedSemaphore(MAX_BACKLOG)
log = logging.getLogger(__name__)


def _submit(claim, date):
    """Place une vérification dans la file partagée, ou None si elle est pleine."""
    if not _backlog.acquire(blocking=False):
        return None
    future = _pool.submit(verify, claim, date)
    future.add_done_callback(lambda _: _backlog.release())  # aussi appelé si la tâche est annulée
    return future
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


def _name(text: str) -> list[str]:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.findall(r"[a-z]+", text)


def same_person(author: str | None, politician: str) -> bool:
    """« Farandou », « Jean-Pierre Farandou », « le ministre Jean-Pierre Farandou » → même personne (le nom de famille suffit)."""
    words, target = _name(author or ""), _name(politician)
    return bool(target) and words != ["article"] and target[-1] in words


def author_label(author: str | None) -> str | None:
    if not author:
        return None
    return "Affirmé par l'article" if author.strip().lower() == "article" else f"Affirmé par {author.strip()}"


def to_contract(claim_id: str, claim: ExtractedClaim, v: Verification, with_start: bool) -> CheckClaim:
    parts = []
    if label := author_label(claim.author):  # article : qui avance l'affirmation (le contrat n'a pas de champ dédié)
        parts.append(f"{label}.")
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

    article = req.source.kind == "article"
    claims = extract_claims(to_prompt_text(segments), speaker, CATEGORIES, req.date, article=article)[:MAX_CLAIMS]
    futures = [_submit(c, req.date) for c in claims]
    wait([f for f in futures if f], timeout=DEADLINE_S)
    for f in futures:
        if f:
            f.cancel()  # pas encore commencée : retirée de la file ; déjà en cours : continue (résultat gardé en mémoire)
    pending = {i for i, f in enumerate(futures) if f is None or not f.done() or f.cancelled()}
    verifications = []
    for f in futures:
        if f is None:
            verifications.append(Verification(verdict=Verdict.inverifiable, method=Method.aucun, confidence=0.0,
                                              explanation=BUSY))
        elif f.cancelled() or not f.done():
            verifications.append(Verification(verdict=Verdict.inverifiable, method=Method.aucun, confidence=0.0,
                                              explanation=PENDING))
        elif f.exception():
            log.warning("vérification impossible : %s", f.exception())
            verifications.append(Verification(verdict=Verdict.inverifiable, method=Method.aucun, confidence=0.0,
                                              explanation="La vérification de cette affirmation a échoué."))
        else:
            verifications.append(f.result())
    if pending:
        log.warning("%d vérification(s) encore en cours après %.0f s", len(pending), DEADLINE_S)

    video_id = video_id_from_url(req.source.url) if req.source.kind == "youtube" else None
    speech_id = f"yt:{video_id}" if video_id else "url:" + hashlib.sha1(req.source.url.encode()).hexdigest()[:12]
    ids = [f"{speech_id}#{i}" for i in range(len(claims))]

    if req.politician:  # stockage pour les profils seulement si on sait qui parle
        speech = Speech(id=speech_id, video_id=video_id, url=req.source.url, title=req.source.title,
                        date=req.date, speaker=req.politician)
        db.save_speech(speech, db.dump_transcript(segments))
        for i, (cid, c, v) in enumerate(zip(ids, claims, verifications)):
            if i in pending:
                continue  # pas de verdict provisoire dans le profil
            if article and not same_person(c.author, req.politician.name):
                continue  # fait de l'article ou d'une autre personne citée : pas dans le profil de la personnalité
            db.save_result(ClaimResult(id=cid, speech_id=speech_id, claim=c, verification=v), req.politician)

    return CheckResponse(claims=[to_contract(cid, c, v, with_start) for cid, c, v in zip(ids, claims, verifications)])
