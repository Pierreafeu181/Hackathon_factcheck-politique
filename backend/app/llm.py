"""Client Claude unique du projet. Ne pas instancier anthropic.Anthropic() ailleurs.

- Modèle : claude-opus-5-5 par défaut (surcharge : variable d'env LLM_MODEL).
- Opus 5.5 : pas de temperature / budget_tokens / prefill. On règle la profondeur via `effort`.
- Outils : recherche web (exécutée par l'API) + outils INSEE en direct (insee_api.py, exécutés ici),
  via `run_with_tools`, utilisé par la vérification web et par le chat.
- Fallbacks serveur activés (`fallbacks="default"`) : si une requête est refusée par les
  classifieurs de sécurité, l'API la rejoue sur un autre modèle dans le même appel.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import TypeVar

import anthropic
from dotenv import load_dotenv
from pydantic import BaseModel

from . import insee_api

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

MODEL = os.getenv("LLM_MODEL", "claude-opus-5-5")
FALLBACK_BETA = "server-side-fallback-2026-07-01"
WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search", "max_uses": 5}
PROMPTS_DIR = Path(__file__).parent / "prompts"

T = TypeVar("T", bound=BaseModel)

_client: anthropic.Anthropic | None = None


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def prompt(name: str) -> str:
    """Charge un prompt système depuis app/prompts/<name>.md."""
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


class LLMRefusal(RuntimeError):
    pass


def parse(system: str, user: str, schema: type[T], effort: str = "medium", max_tokens: int = 16000) -> T:
    """Appel LLM avec sortie structurée validée par Pydantic."""
    response = client().beta.messages.parse(
        model=MODEL,
        max_tokens=max_tokens,
        betas=[FALLBACK_BETA],
        fallbacks="default",
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"effort": effort},
        output_format=schema,
    )
    if response.stop_reason == "refusal":
        raise LLMRefusal(getattr(response.stop_details, "explanation", "refus"))
    return response.parsed_output


def run_with_tools(system: str, messages: list[dict], effort: str = "medium", max_tokens: int = 16000,
                   max_steps: int = 10) -> tuple[list, list[dict]]:
    """Laisse Claude chercher sur le web et interroger l'API INSEE jusqu'à sa réponse finale.

    Renvoie (blocs de contenu de toutes les réponses, séries INSEE lues avec leur URL).
    """
    messages = list(messages)
    blocks: list = []
    insee_seen: list[dict] = []
    for _ in range(max_steps):
        response = client().beta.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            betas=[FALLBACK_BETA],
            fallbacks="default",
            system=system,
            messages=messages,
            tools=[WEB_SEARCH_TOOL, *insee_api.TOOLS],
            output_config={"effort": effort},
        )
        if response.stop_reason == "refusal":
            raise LLMRefusal(getattr(response.stop_details, "explanation", "refus"))
        blocks.extend(response.content)
        if response.stop_reason == "tool_use":
            results = []
            for block in response.content:
                if block.type == "tool_use":
                    out, seen, is_error = insee_api.run_tool(block.name, block.input)
                    insee_seen.extend(seen)
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": out,
                                    **({"is_error": True} if is_error else {})})
            messages += [{"role": "assistant", "content": response.content}, {"role": "user", "content": results}]
        elif response.stop_reason == "pause_turn":
            # la recherche web n'est pas finie : on renvoie la réponse telle quelle pour continuer
            messages.append({"role": "assistant", "content": response.content})
        else:
            break
    return blocks, insee_seen


def web_research(system: str, user: str, effort: str = "medium") -> tuple[str, list[dict]]:
    """Vérification hors référentiel : web + API INSEE. Renvoie (texte final, sources vues).

    Les sources vues servent à vérifier que les sources citées existent vraiment.
    """
    blocks, seen = run_with_tools(system, [{"role": "user", "content": user}], effort=effort)
    text_parts: list[str] = []
    for block in blocks:
        if block.type == "text":
            text_parts.append(block.text)
        elif block.type == "web_search_tool_result" and isinstance(block.content, list):
            for r in block.content:
                seen.append({"title": getattr(r, "title", ""), "url": getattr(r, "url", "")})
    return "\n".join(text_parts).strip(), seen
