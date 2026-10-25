"""Lot B — Extraction des affirmations vérifiables depuis un transcript."""
from __future__ import annotations

import datetime as dt

from . import llm, referentiel
from .models import Category, ExtractedClaim, ExtractionResult


def extract_claims(transcript_text: str, speaker: str, categories: list[Category], date: str | None = None,
                   article: bool = False) -> list[ExtractedClaim]:
    """`article=True` : on extrait aussi les faits avancés par l'article et par chaque personne citée (champ author)."""
    system = llm.prompt("extract").replace("{{INDICATORS}}", referentiel.indicators_for_prompt())
    if article:
        system += "\n" + llm.prompt("extract_article")
    user = (
        f"Orateur : {speaker}\n"
        # Sans date, certains modèles (Gemini) n'extraient rien : on donne la date d'analyse.
        f"Date du discours : {date or f'inconnue (analyse du {dt.date.today().isoformat()}, propos probablement récents)'}\n"
        f"Catégories à couvrir : {', '.join(c.value for c in categories)}\n\n"
        f"<transcript>\n{transcript_text}\n</transcript>"
    )
    result = llm.parse(system, user, ExtractionResult, effort="medium")
    wanted = {c.value for c in categories}
    claims = [c for c in result.claims if c.checkable and c.category.value in wanted]
    for c in claims:
        if article:
            c.timestamp_start = None
        else:
            c.author = None  # discours : tout est de l'orateur
    return claims
