"""Lot C — Routeur de vérification.

1. Référentiel officiel (data/referentiel) : verdict, explication et correction produits en code, sans LLM.
2. Sinon, recherche web par le LLM (confiance plafonnée à 0,7).
3. Sinon, `inverifiable`.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
import unicodedata
from collections import OrderedDict
from urllib.parse import urlparse

from . import llm, open_data, referentiel
from .models import ClaimType, ExtractedClaim, Method, Unit, Verdict, Verification, WebVerification

log = logging.getLogger(__name__)

WEB_CONFIDENCE_CAP = 0.7
WEB_CACHE_TTL, WEB_CACHE_MAX = 24 * 3600, 500
_web_cache: OrderedDict[str, tuple[float, Verification]] = OrderedDict()
_web_cache_lock = threading.Lock()


def _canon(text: str) -> str:
    """Casse, accents et ponctuation ignorés ; les lettres non latines sont gardées (jamais de clé vide par effacement)."""
    text = "".join(ch for ch in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(ch))
    return " ".join(re.findall(r"\w+", text))


def cache_key(claim: ExtractedClaim, speech_date: str | None) -> str:
    """Empreinte de tout ce qui entre dans le prompt ou le calcul du verdict : mêmes entrées → même vérification."""
    canon = claim.model_dump(mode="json", exclude={"timestamp_start", "checkable", "category"})
    canon.update(claim=_canon(claim.claim), quote=_canon(claim.quote), geo=_canon(claim.geo), date=(speech_date or "")[:10])
    return hashlib.sha256(json.dumps(canon, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


# Jamais des preuves : sources modifiables par tous, réseaux sociaux, plateformes de blogs.
UNRELIABLE_HOSTS = ("wikipedia.org", "wikiwix.com", "x.com", "twitter.com", "facebook.com", "instagram.com", "tiktok.com",
                    "reddit.com", "medium.com", "substack.com", "blogspot.com", "over-blog.com", "quora.com")


def unreliable(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in UNRELIABLE_HOSTS)


SEVERITY = {Verdict.vrai: 0, Verdict.plutot_vrai: 1, Verdict.imprecis: 2, Verdict.trompeur: 3, Verdict.faux: 3,
            Verdict.inverifiable: -1}


def rate_verdict(claim: ExtractedClaim, official: float | None) -> tuple[Verdict, float] | None:
    """Taux affirmé vs taux officiel trouvé par le modèle : verdict avec les tolérances du référentiel."""
    if claim.claim_type != ClaimType.niveau or claim.unit != Unit.pourcent or claim.value is None or official is None:
        return None
    if not (0 <= claim.value <= 100 and 0 <= official <= 100):
        return None
    gap = referentiel._gap(claim.value, official, claim.bound)
    verdict = referentiel._grade(gap, referentiel.RATE_TOL)
    if claim.bound and gap > 0 and verdict in (Verdict.vrai, Verdict.plutot_vrai):
        verdict = Verdict.imprecis
    return verdict, gap


def cached(claim: ExtractedClaim, speech_date: str | None) -> Verification | None:
    """Vérification web déjà faite pour cette affirmation (mémoire 24 h), sans rien relancer."""
    with _web_cache_lock:
        hit = _web_cache.get(cache_key(claim, speech_date))
    return hit[1].model_copy(deep=True) if hit and time.time() - hit[0] < WEB_CACHE_TTL else None


# Rapprochement systématique avec les fact-checks déjà publiés (comme Full Fact, Squash ou Chequeabot) : gratuit pour le
# quota Gemini. Sans éditeur humain pour valider la correspondance, le fact-check ne décide jamais seul : il est donné au
# modèle, qui juge s'il porte bien sur la même affirmation.
FACTCHECK_MIN_OVERLAP = 0.3
_STOP = {"selon", "depuis", "cette", "entre", "leurs", "notre", "votre", "avoir",
         "etait", "sont", "plus", "moins", "tous", "toutes", "dans", "pour", "avec", "sans", "elle", "ils"}


def _stems(text: str) -> set[str]:
    return {w[:5] for w in re.findall(r"[a-z0-9]+", open_data._norm(text)) if len(w) > 3 and w not in _STOP}


def published_factchecks(claim: ExtractedClaim, limit: int = 3) -> list[dict]:
    """Fact-checks publiés (Google Fact Check) dont l'affirmation recoupe celle-ci, du plus proche au moins proche."""
    if not os.getenv("GOOGLE_FACTCHECK_API_KEY"):
        return []
    try:
        found = open_data.factcheck_search(claim.claim[:200]).get("fact_checks", [])
    except Exception as e:  # service tiers : jamais bloquant
        log.info("Google Fact Check indisponible : %s", e)
        return []
    mine = _stems(f"{claim.claim} {claim.quote}")
    scored = []
    for fc in found:
        theirs = _stems(f"{fc.get('affirmation') or ''} {fc.get('titre') or ''}")
        overlap = len(mine & theirs) / max(len(mine), 1)
        if fc.get("url") and overlap >= FACTCHECK_MIN_OVERLAP:
            scored.append((overlap, fc))
    return [fc for _, fc in sorted(scored, key=lambda x: -x[0])[:limit]]


def verify(claim: ExtractedClaim, speech_date: str | None = None, use_web: bool = True) -> Verification:
    result = referentiel.check(claim, speech_date)
    if result is not None:
        return _from_referentiel(claim, result)
    key = cache_key(claim, speech_date)
    with _web_cache_lock:  # déjà vérifiée (mémoire 24 h) : gratuit, même hors budget de recherche
        hit = _web_cache.get(key)
        if hit and time.time() - hit[0] < WEB_CACHE_TTL:
            _web_cache.move_to_end(key)
            return hit[1].model_copy(deep=True)
    if use_web:
        try:
            result = _from_web(claim, speech_date)
        except Exception as e:  # la démo ne doit pas planter sur une affirmation
            log.warning("vérification web impossible : %s", e)
        else:
            if result.sources:  # seulement les verdicts sourcés : un échec passager ne doit pas rester en mémoire
                with _web_cache_lock:
                    _web_cache[key] = (time.time(), result)
                    while len(_web_cache) > WEB_CACHE_MAX:
                        _web_cache.popitem(last=False)
            return result
    return Verification(
        verdict=Verdict.inverifiable, method=Method.aucun, confidence=0.0,
        explanation="Aucune donnée officielle du référentiel ne couvre cette affirmation et la recherche web n'a pas abouti.",
    )


def _from_referentiel(claim: ExtractedClaim, r: referentiel.CheckResult) -> Verification:
    """Verdict, explication et correction viennent du code : aucun appel au LLM, et le texte ne peut pas
    contredire le chiffre."""
    return Verification(
        verdict=r.verdict, method=Method.referentiel,
        official_value=r.official_value, official_period=r.official_period,
        correction=r.correction, explanation=r.explanation, sources=r.sources, confidence=r.confidence,
    )


def _from_web(claim: ExtractedClaim, speech_date: str | None) -> Verification:
    user = (f"Affirmation : {claim.claim}\nCitation : « {claim.quote} »\n"
            f"Date du discours : {speech_date or 'inconnue'}")
    published = published_factchecks(claim)
    if published:
        user += ("\n\nFact-checks déjà publiés par des rédactions, trouvés automatiquement : ne t'en sers que s'ils portent "
                 "bien sur la même affirmation (même chiffre, même sujet, même période), et cite alors leur URL.\n"
                 + "\n".join(f"- {fc.get('media')} ({fc.get('date') or 'date inconnue'}) : « {fc.get('affirmation')} » → "
                              f"{fc.get('verdict')}. {fc.get('titre') or ''} {fc['url']}" for fc in published))
    findings, seen = llm.web_research(llm.prompt("verify_web"), user)
    seen = seen + [{"title": f"{fc.get('media')} – {fc.get('titre') or fc.get('affirmation')}", "url": fc["url"]}
                   for fc in published]
    structured = llm.parse(
        "Convertis ce compte rendu de vérification en JSON conforme au schéma. N'invente aucune source : "
        "garde uniquement les URL présentes dans le texte.",
        findings, WebVerification, effort="low", max_tokens=4000,
    )
    seen_urls = {s["url"] for s in seen}
    sources = [s for s in structured.sources if s.url in seen_urls and not unreliable(s.url)]
    verdict = structured.verdict if sources else Verdict.inverifiable
    explanation = structured.explanation
    if verdict != Verdict.inverifiable and (graded := rate_verdict(claim, structured.official_value)):
        code_verdict, gap = graded
        if SEVERITY[code_verdict] > SEVERITY[verdict]:  # le code ne fait que durcir un verdict trop indulgent
            verdict = code_verdict
            explanation += f" Écart de {gap:.1f} point avec la valeur officielle : verdict calculé par le comparateur."
    return Verification(
        verdict=verdict, method=Method.web,
        official_value=structured.official_value, official_period=structured.official_period,
        correction=structured.correction, explanation=explanation, sources=sources,
        confidence=min(structured.confidence, WEB_CONFIDENCE_CAP) if sources else 0.0,
    )
