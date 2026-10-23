"""Client LLM unique du projet. Ne pas instancier de client Gemini ou Anthropic ailleurs.

Deux fournisseurs, choisis par LLM_PROVIDER (défaut : gemini si GEMINI_API_KEY est défini, sinon anthropic) :
- gemini : Gemini Flash, offre gratuite (modèle : GEMINI_MODEL, défaut gemini-3.5-flash-lite, secours gemini-3.1-flash-lite ; gemini-3.8-flash : 20 requêtes/jour en gratuit). Pas de recherche
  Google sur l'offre gratuite : la vérification passe par nos outils de données ouvertes (tools.py).
  Appels limités en parallèle et relancés automatiquement quand le quota par minute est atteint.
- anthropic : Claude (LLM_MODEL, défaut claude-sonnet-5-5), avec sa recherche web. Gardé pour le jour
  où il y a de nouveau des crédits.

API commune : parse() pour une sortie structurée, run_with_tools() pour une boucle d'outils.
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeVar

from dotenv import load_dotenv
from pydantic import BaseModel

from . import tools

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
log = logging.getLogger("factcheck.llm")

PROVIDER = os.getenv("LLM_PROVIDER") or ("gemini" if os.getenv("GEMINI_API_KEY") else "anthropic")
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite") if PROVIDER == "gemini" else os.getenv("LLM_MODEL", "claude-sonnet-5-5")
PROMPTS_DIR = Path(__file__).parent / "prompts"

# Anthropic (si LLM_PROVIDER=anthropic)
FALLBACK_BETA = "server-side-fallback-2026-07-01"
WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search", "max_uses": 5}

T = TypeVar("T", bound=BaseModel)


class LLMRefusal(RuntimeError):
    pass


@dataclass
class ToolRun:
    """Résultat d'une boucle d'outils, indépendant du fournisseur."""
    text: str = ""                                   # réponse finale (après le dernier appel d'outil)
    all_text: str = ""                               # tout le texte produit, phrases de travail comprises
    seen: list[dict] = field(default_factory=list)   # sources réellement consultées {title, url}
    cited: list[dict] = field(default_factory=list)  # sources citées dans la réponse (recherche web Claude)


def prompt(name: str) -> str:
    """Charge un prompt système depuis app/prompts/<name>.md."""
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


def parse(system: str, user: str, schema: type[T], effort: str = "medium", max_tokens: int = 16000) -> T:
    """Appel LLM avec sortie structurée validée par Pydantic."""
    return _gemini_parse(system, user, schema, max_tokens) if PROVIDER == "gemini" else _claude_parse(system, user, schema, effort, max_tokens)


def run_with_tools(system: str, messages: list[dict], effort: str = "medium", max_tokens: int = 16000,
                   max_steps: int = 10) -> ToolRun:
    """Laisse le modèle interroger nos sources (INSEE, Eurostat, data.gouv…) jusqu'à sa réponse finale.
    `messages` : [{"role": "user"|"assistant", "content": str}]."""
    if PROVIDER == "gemini":
        return _gemini_tools(system, messages, max_tokens, max_steps)
    return _claude_tools(system, messages, effort, max_tokens, max_steps)


def web_research(system: str, user: str, effort: str = "medium") -> tuple[str, list[dict]]:
    """Vérification hors référentiel. Renvoie (compte rendu, sources réellement consultées)."""
    run = run_with_tools(system, [{"role": "user", "content": user}], effort=effort)
    return run.all_text, run.seen


# ---------------------------------------------------------------- Gemini

_gemini_client = None
_gemini_slots = threading.Semaphore(int(os.getenv("GEMINI_MAX_PARALLEL", "2")))


_gemini_lock = threading.Lock()


def _gemini():
    """Client unique, créé sous verrou : deux threads qui en créeraient chacun un fermeraient celui de l'autre."""
    global _gemini_client
    with _gemini_lock:
        if _gemini_client is None:
            from google import genai
            _gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        return _gemini_client


FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.1-flash-lite")
_fallback_until = 0.0


def _gemini_call(contents, config):
    """generate_content avec relance sur quota (429) et surcharge (503) : l'offre gratuite est plafonnée par minute.
    Après deux surcharges, bascule sur le modèle de secours (moins demandé)."""
    global _fallback_until
    from google.genai import errors
    delay, overloaded = 5.0, 0
    # Bascule « collante » quelques minutes : une boucle d'outils garde le même modèle d'un appel à l'autre.
    model = FALLBACK_MODEL if time.time() < _fallback_until else MODEL
    for attempt in range(6):
        try:
            with _gemini_slots:
                return _gemini().models.generate_content(model=model, contents=contents, config=config)
        except errors.APIError as e:
            if e.code not in (429, 500, 503) or attempt == 5:
                raise
            if e.code == 503:
                overloaded += 1
                if overloaded >= 2 and model != FALLBACK_MODEL:
                    log.warning("%s surchargé, bascule sur %s pour 5 min", model, FALLBACK_MODEL)
                    model, _fallback_until = FALLBACK_MODEL, time.time() + 300
                    continue
            wait = delay
            if m := re.search(r"retryDelay['\": ]+(\d+)", str(e)):
                wait = float(m.group(1)) + 1
            if e.code == 429 and wait > 120:
                # Quota du jour épuisé (offre gratuite) : inutile d'attendre, on tente le modèle de secours.
                if model == FALLBACK_MODEL:
                    raise
                log.warning("quota du jour épuisé sur %s, bascule sur %s", model, FALLBACK_MODEL)
                model, _fallback_until = FALLBACK_MODEL, time.time() + 3600
                continue
            log.warning("Gemini %s, nouvel essai dans %.0f s", e.code, wait)
            time.sleep(min(wait, 60))
            delay = min(delay * 2, 60)


def _check_finish(resp) -> None:
    cand = (resp.candidates or [None])[0]
    reason = str(getattr(cand, "finish_reason", "") or "")
    if any(k in reason for k in ("SAFETY", "PROHIBITED", "BLOCKLIST", "RECITATION")):
        raise LLMRefusal(f"réponse bloquée par Gemini ({reason})")
    if getattr(resp, "prompt_feedback", None) and getattr(resp.prompt_feedback, "block_reason", None):
        raise LLMRefusal(f"demande bloquée par Gemini ({resp.prompt_feedback.block_reason})")


def _gemini_parse(system: str, user: str, schema: type[T], max_tokens: int) -> T:
    from google.genai import types
    resp = _gemini_call(user, types.GenerateContentConfig(
        system_instruction=system, max_output_tokens=max_tokens,
        response_mime_type="application/json", response_schema=schema))
    _check_finish(resp)
    if isinstance(resp.parsed, schema):
        return resp.parsed
    return schema.model_validate_json(resp.text or "")


def _gemini_tools(system: str, messages: list[dict], max_tokens: int, max_steps: int) -> ToolRun:
    from google.genai import types
    declarations = [types.FunctionDeclaration(name=t["name"], description=t["description"],
                                              parameters_json_schema=t["input_schema"]) for t in tools.available()]
    config = types.GenerateContentConfig(
        system_instruction=system, max_output_tokens=max_tokens,
        tools=[types.Tool(function_declarations=declarations)],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))
    contents = [types.Content(role="model" if m["role"] == "assistant" else "user", parts=[types.Part.from_text(text=m["content"])])
                for m in messages]
    run = ToolRun()
    texts: list[str] = []
    for _ in range(max_steps):
        resp = _gemini_call(contents, config)
        _check_finish(resp)
        content = resp.candidates[0].content
        step_text = "".join(p.text for p in (content.parts or []) if p.text and not getattr(p, "thought", False))
        texts.append(step_text)
        calls = resp.function_calls or []
        if not calls:
            run.text = step_text.strip()
            break
        contents.append(content)  # tel quel : Gemini 3 y attache ses signatures de raisonnement
        parts = []
        for call in calls:
            out, seen, is_error = tools.run_tool(call.name, dict(call.args or {}))
            run.seen.extend(seen)
            parts.append(types.Part.from_function_response(name=call.name, response={"error" if is_error else "result": out}))
        contents.append(types.Content(role="user", parts=parts))
    run.all_text = "\n".join(t for t in texts if t).strip()
    return run


# ---------------------------------------------------------------- Anthropic (Claude)

_claude_client = None


def client():
    """Client Anthropic (seulement si LLM_PROVIDER=anthropic)."""
    global _claude_client
    if _claude_client is None:
        import anthropic
        _claude_client = anthropic.Anthropic()
    return _claude_client


def _claude_parse(system: str, user: str, schema: type[T], effort: str, max_tokens: int) -> T:
    response = client().beta.messages.parse(
        model=MODEL, max_tokens=max_tokens, betas=[FALLBACK_BETA], fallbacks="default",
        system=system, messages=[{"role": "user", "content": user}],
        output_config={"effort": effort}, output_format=schema,
    )
    if response.stop_reason == "refusal":
        raise LLMRefusal(getattr(response.stop_details, "explanation", "refus"))
    return response.parsed_output


def _claude_tools(system: str, messages: list[dict], effort: str, max_tokens: int, max_steps: int) -> ToolRun:
    messages = list(messages)
    blocks: list = []
    run = ToolRun()
    for _ in range(max_steps):
        response = client().beta.messages.create(
            model=MODEL, max_tokens=max_tokens, betas=[FALLBACK_BETA], fallbacks="default",
            system=system, messages=messages, tools=[WEB_SEARCH_TOOL, *tools.available()],
            output_config={"effort": effort},
        )
        if response.stop_reason == "refusal":
            raise LLMRefusal(getattr(response.stop_details, "explanation", "refus"))
        blocks.extend(response.content)
        if response.stop_reason == "tool_use":
            results = []
            for block in response.content:
                if block.type == "tool_use":
                    out, seen, is_error = tools.run_tool(block.name, block.input)
                    run.seen.extend(seen)
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": out,
                                    **({"is_error": True} if is_error else {})})
            messages += [{"role": "assistant", "content": response.content}, {"role": "user", "content": results}]
        elif response.stop_reason == "pause_turn":
            # la recherche web n'est pas finie : on renvoie la réponse telle quelle pour continuer
            messages.append({"role": "assistant", "content": response.content})
        else:
            break
    last_tool = max((i for i, b in enumerate(blocks) if b.type in ("tool_use", "server_tool_use")), default=-1)
    run.all_text = "\n".join(b.text for b in blocks if b.type == "text").strip()
    run.text = "".join(b.text for b in blocks[last_tool + 1:] if b.type == "text").strip()
    for b in blocks:
        if b.type == "web_search_tool_result" and isinstance(b.content, list):
            run.seen.extend({"title": getattr(r, "title", ""), "url": getattr(r, "url", "")} for r in b.content)
        if b.type == "text":
            for c in getattr(b, "citations", None) or []:
                if getattr(c, "url", None):
                    run.cited.append({"title": getattr(c, "title", None) or c.url, "url": c.url})
    return run
