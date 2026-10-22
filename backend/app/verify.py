"""Lot C — Routeur de vérification.

1. Référentiel officiel (data/referentiel) : verdict calculé en code, le LLM ne fait que rédiger.
2. Sinon, recherche web par le LLM (confiance plafonnée à 0,7).
3. Sinon, `inverifiable`.
"""
from __future__ import annotations

import json
import logging

from . import llm, referentiel
from .models import ExplanationText, ExtractedClaim, Method, Verdict, Verification, WebVerification

log = logging.getLogger(__name__)

WEB_CONFIDENCE_CAP = 0.7


def verify(claim: ExtractedClaim, speech_date: str | None = None, use_web: bool = True) -> Verification:
    result = referentiel.check(claim)
    if result is not None:
        return _from_referentiel(claim, result)
    if use_web:
        try:
            return _from_web(claim, speech_date)
        except Exception as e:  # la démo ne doit pas planter sur une affirmation
            log.warning("vérification web impossible : %s", e)
    return Verification(
        verdict=Verdict.inverifiable, method=Method.aucun, confidence=0.0,
        explanation="Aucune donnée officielle du référentiel ne couvre cette affirmation et la recherche web n'a pas abouti.",
    )


def _from_referentiel(claim: ExtractedClaim, r: referentiel.CheckResult) -> Verification:
    user = json.dumps({
        "affirmation": claim.claim,
        "citation": claim.quote,
        "verdict_calcule": r.verdict.value,
        "constat_chiffre": r.facts,
        "sources": [s.model_dump() for s in r.sources],
    }, ensure_ascii=False, indent=1)
    try:
        text = llm.parse(llm.prompt("verify_explain"), user, ExplanationText, effort="low", max_tokens=2000)
        explanation, correction = text.explanation, text.correction
    except Exception as e:
        log.warning("rédaction LLM impossible, on garde le constat brut : %s", e)
        explanation, correction = r.facts, None
    if r.verdict == Verdict.vrai:
        correction = None
    return Verification(
        verdict=r.verdict, method=Method.referentiel,
        official_value=r.official_value, official_period=r.official_period,
        correction=correction, explanation=explanation, sources=r.sources, confidence=r.confidence,
    )


def _from_web(claim: ExtractedClaim, speech_date: str | None) -> Verification:
    user = (f"Affirmation : {claim.claim}\nCitation : « {claim.quote} »\n"
            f"Date du discours : {speech_date or 'inconnue'}")
    findings, seen = llm.web_research(llm.prompt("verify_web"), user)
    structured = llm.parse(
        "Convertis ce compte rendu de vérification en JSON conforme au schéma. N'invente aucune source : "
        "garde uniquement les URL présentes dans le texte.",
        findings, WebVerification, effort="low", max_tokens=4000,
    )
    seen_urls = {s["url"] for s in seen}
    sources = [s for s in structured.sources if s.url in seen_urls] or structured.sources[:0]
    verdict = structured.verdict if sources else Verdict.inverifiable
    return Verification(
        verdict=verdict, method=Method.web,
        official_value=structured.official_value, official_period=structured.official_period,
        correction=structured.correction, explanation=structured.explanation, sources=sources,
        confidence=min(structured.confidence, WEB_CONFIDENCE_CAP) if sources else 0.0,
    )
