"""Lot C — Google Fact Check Tools : les fact-checks déjà publiés par les rédactions.

Interrogé en premier par verify.py : si un journaliste a déjà vérifié l'affirmation
(AFP Factuel, Les Décodeurs, CheckNews, franceinfo…), on reprend son verdict et on renvoie vers son article.
Sans clé GOOGLE_FACTCHECK_API_KEY, le module ne fait rien.
"""
from __future__ import annotations

import difflib
import os
import re
import unicodedata
from typing import Callable

import httpx

from .models import ExtractedClaim, Method, Source, Verdict, Verification

API_URL = "https://factchecktools.googleapis.com/v1alpha1/claims:search"
MAX_AGE_DAYS = 1095
MIN_SIMILARITY = 0.5
CONFIDENCE = 0.8

# Ordre important : « plutôt vrai » avant « vrai », « partiellement faux » avant « faux », « inexact » avant « exact ».
RATINGS: list[tuple[tuple[str, ...], Verdict]] = [
    (("plutot vrai", "mostly true", "en partie vrai", "partiellement vrai"), Verdict.plutot_vrai),
    (("partiellement faux", "en partie faux", "trompeur", "misleading", "manque de contexte", "missing context",
      "sorti de son contexte", "exagere", "half true"), Verdict.trompeur),
    (("faux", "false", "inexact", "infonde", "incorrect"), Verdict.faux),
    (("imprecis", "approximatif"), Verdict.imprecis),
    (("vrai", "true", "exact", "correct"), Verdict.vrai),
]

_STOPWORDS = {"les", "des", "une", "est", "que", "qui", "pour", "dans", "par", "sur", "pas", "plus", "avec", "aux",
              "son", "ses", "leur", "cette", "ces", "été", "ete", "ont", "sont", "the", "and"}


class FactCheckError(Exception):
    """Erreur d'appel à l'API. Le message ne contient jamais l'URL (elle porte la clé)."""


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+(?:[.,][0-9]+)?", _norm(text))


def similarity(a: str, b: str) -> float:
    """Proximité entre deux formulations : suite de mots, ou recouvrement des mots porteurs de sens."""
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return 0.0
    seq = difflib.SequenceMatcher(None, wa, wb).ratio()
    ca = {w for w in wa if len(w) > 2 and w not in _STOPWORDS}
    cb = {w for w in wb if len(w) > 2 and w not in _STOPWORDS}
    overlap = len(ca & cb) / min(len(ca), len(cb)) if ca and cb else 0.0
    return max(seq, overlap)


def rating_to_verdict(rating: str | None) -> Verdict | None:
    text = _norm(rating or "")
    for needles, verdict in RATINGS:
        if any(n in text for n in needles):
            return verdict
    return None


def search(query: str) -> list[dict]:
    key = os.getenv("GOOGLE_FACTCHECK_API_KEY")
    if not key or not query.strip():
        return []
    params = {"query": query[:300], "languageCode": "fr", "maxAgeDays": MAX_AGE_DAYS, "pageSize": 10, "key": key}
    try:
        r = httpx.get(API_URL, params=params, timeout=10)
    except httpx.HTTPError as e:
        raise FactCheckError(type(e).__name__) from None
    if r.status_code != 200:
        raise FactCheckError(f"HTTP {r.status_code}")
    return r.json().get("claims", [])


def check(claim: ExtractedClaim, fetch: Callable[[str], list[dict]] = search) -> Verification | None:
    """Verdict d'une rédaction sur une affirmation proche, ou None si aucun fact-check ne correspond."""
    texts = [t for t in (claim.claim, claim.quote) if t and t.strip(" …")]
    for query in dict.fromkeys(texts):
        best: tuple[float, dict, dict, Verdict] | None = None
        for item in fetch(query):
            score = max(similarity(item.get("text", ""), t) for t in texts)
            if score < MIN_SIMILARITY:
                continue
            for review in item.get("claimReview", []):
                if review.get("languageCode", "fr") != "fr" or not review.get("url"):
                    continue
                verdict = rating_to_verdict(review.get("textualRating"))
                if verdict is not None and (best is None or score > best[0]):
                    best = (score, item, review, verdict)
        if best:
            return _to_verification(*best[1:])
    return None


def _to_verification(item: dict, review: dict, verdict: Verdict) -> Verification:
    publisher = (review.get("publisher") or {}).get("name") or (review.get("publisher") or {}).get("site") or "Rédaction"
    date = (review.get("reviewDate") or item.get("claimDate") or "")[:10]
    rating = review.get("textualRating", "")
    title = review.get("title") or "Article de vérification"
    when = f" le {date}" if date else ""
    explanation = f"Déjà vérifié par {publisher}{when} : « {rating} ». {title}"
    note = f"Affirmation vérifiée : « {item.get('text', '')} »"
    if item.get("claimant"):
        note += f" ({item['claimant']})"
    return Verification(
        verdict=verdict, method=Method.factcheck, explanation=explanation, confidence=CONFIDENCE,
        sources=[Source(title=title, url=review["url"], publisher=publisher, note=note)],
    )
