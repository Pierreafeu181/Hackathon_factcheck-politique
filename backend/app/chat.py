"""Lot A — Chat du panneau : questions libres sur la vidéo en cours et sur les chiffres.

Le chat n'est pas dans le contrat gelé (il ne produit pas de verdict) : ses modèles vivent ici.
Il réutilise le client Claude de llm.py, le référentiel et les verdicts déjà stockés.
"""
from __future__ import annotations

import json
from typing import Literal, Optional

from pydantic import BaseModel, Field

from . import db, llm, referentiel
from .models import CheckClaim

MAX_TRANSCRIPT_CHARS = 60_000
MAX_TURNS = 20


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=40)
    video_id: Optional[str] = Field(default=None, max_length=20)
    title: Optional[str] = Field(default=None, max_length=300)
    speaker: Optional[str] = Field(default=None, max_length=120)
    # Verdicts déjà affichés par l'extension (format contract.ts) : contexte prioritaire sur la base.
    claims: list[CheckClaim] = Field(default=[], max_length=30)


class ChatSource(BaseModel):
    title: str
    url: str


class ChatResponse(BaseModel):
    answer: str
    sources: list[ChatSource]


def answer(req: ChatRequest) -> ChatResponse:
    system = (llm.prompt("chat")
              .replace("{{INDICATORS}}", referentiel.indicators_for_prompt())
              .replace("{{CONTEXT}}", _context(req)))
    messages: list[dict] = [m.model_dump() for m in req.messages[-MAX_TURNS:]]
    text_parts: list[str] = []
    sources: dict[str, ChatSource] = {}
    for _ in range(4):
        response = llm.client().beta.messages.create(
            model=llm.MODEL,
            max_tokens=4000,
            betas=[llm.FALLBACK_BETA],
            fallbacks="default",
            system=system,
            messages=messages,
            tools=[llm.WEB_SEARCH_TOOL],
            output_config={"effort": "low"},
        )
        if response.stop_reason == "refusal":
            raise llm.LLMRefusal(getattr(response.stop_details, "explanation", "refus"))
        for block in response.content:
            if block.type != "text":
                continue
            text_parts.append(block.text)
            # Seules les pages réellement citées par la recherche web deviennent des sources.
            for c in getattr(block, "citations", None) or []:
                url = getattr(c, "url", None)
                if url:
                    sources.setdefault(url, ChatSource(title=getattr(c, "title", None) or url, url=url))
        if response.stop_reason != "pause_turn":
            break
        messages.append({"role": "assistant", "content": response.content})
    return ChatResponse(answer="".join(text_parts).strip(), sources=list(sources.values()))


def _context(req: ChatRequest) -> str:
    if req.claims:
        lines = [f"Vidéo ou page « {req.title or '?'} »" + (f", orateur·rice : {req.speaker}" if req.speaker else ""),
                 "", "Verdicts rendus :"]
        lines += [f"- [{int(c.start or 0)}s] « {c.quote} » → {c.verdict} : {c.explanation}" for c in req.claims]
        if req.video_id and (transcript := _transcript(f"yt:{req.video_id}")):
            lines += ["", "<transcript>", transcript, "</transcript>"]
        return "\n".join(lines)
    if not req.video_id:
        return f"Page : {req.title}" if req.title else "Aucune vidéo ouverte."
    found = db.get_speech(f"yt:{req.video_id}")
    if not found:
        return f"Vidéo « {req.title or req.video_id} » : pas encore analysée."
    speech, results = found
    lines = [f"Vidéo « {speech.title} », orateur·rice : {speech.speaker.name}"
             + (f" ({speech.speaker.party})" if speech.speaker.party else "")
             + (f", le {speech.date}" if speech.date else ""),
             "", "Verdicts rendus :"]
    for r in results:
        c, v = r.claim, r.verification
        lines.append(f"- [{int(c.timestamp_start or 0)}s] « {c.quote} » → {v.verdict.value} "
                     f"(méthode {v.method.value}) : {v.explanation}"
                     + (f" Correction : {v.correction}" if v.correction else ""))
    if not results:
        lines.append("(aucune affirmation vérifiable sur l'emploi)")
    if transcript := _transcript(speech.id):
        lines += ["", "<transcript>", transcript, "</transcript>"]
    return "\n".join(lines)


def _transcript(speech_id: str) -> str:
    with db.connect() as c:
        row = c.execute("SELECT transcript FROM speeches WHERE id=?", (speech_id,)).fetchone()
    if not row or not row["transcript"]:
        return ""
    segments = json.loads(row["transcript"])
    text = " ".join(f"[{int(s.get('start', 0))}s] {s.get('text', '')}" for s in segments)
    # Le transcript est une donnée non fiable : on empêche qu'il ferme la balise qui l'entoure.
    return text.replace("<", "‹").replace(">", "›")[:MAX_TRANSCRIPT_CHARS]
