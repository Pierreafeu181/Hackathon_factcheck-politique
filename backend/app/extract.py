"""Lot B — Extraction des affirmations vérifiables depuis un transcript."""
from __future__ import annotations

from . import llm, referentiel
from .models import Category, ExtractedClaim, ExtractionResult


def extract_claims(transcript_text: str, speaker: str, categories: list[Category], date: str | None = None) -> list[ExtractedClaim]:
    system = llm.prompt("extract").replace("{{INDICATORS}}", referentiel.indicators_for_prompt())
    user = (
        f"Orateur : {speaker}\n"
        f"Date du discours : {date or 'inconnue'}\n"
        f"Catégories à couvrir : {', '.join(c.value for c in categories)}\n\n"
        f"<transcript>\n{transcript_text}\n</transcript>"
    )
    result = llm.parse(system, user, ExtractionResult, effort="medium")
    wanted = {c.value for c in categories}
    return [c for c in result.claims if c.checkable and c.category.value in wanted]
