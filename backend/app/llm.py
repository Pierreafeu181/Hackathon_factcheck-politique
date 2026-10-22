"""Client Claude unique du projet. Ne pas instancier anthropic.Anthropic() ailleurs.

- Modèle : claude-opus-5-5 par défaut (surcharge : variable d'env LLM_MODEL).
- Opus 5.5 : pas de temperature / budget_tokens / prefill. On règle la profondeur via `effort`.
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


def web_research(system: str, user: str, effort: str = "medium", max_continuations: int = 3) -> tuple[str, list[dict]]:
    """Laisse Claude chercher sur le web. Renvoie (texte final, résultats de recherche vus).

    Les résultats vus servent à vérifier que les sources citées existent vraiment.
    """
    messages: list[dict] = [{"role": "user", "content": user}]
    seen: list[dict] = []
    text_parts: list[str] = []
    for _ in range(max_continuations + 1):
        response = client().beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            betas=[FALLBACK_BETA],
            fallbacks="default",
            system=system,
            messages=messages,
            tools=[WEB_SEARCH_TOOL],
            output_config={"effort": effort},
        )
        if response.stop_reason == "refusal":
            raise LLMRefusal(getattr(response.stop_details, "explanation", "refus"))
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "web_search_tool_result" and isinstance(block.content, list):
                for r in block.content:
                    seen.append({"title": getattr(r, "title", ""), "url": getattr(r, "url", "")})
        if response.stop_reason != "pause_turn":
            break
        # pause_turn : la recherche n'est pas finie, on renvoie la réponse telle quelle pour continuer.
        messages.append({"role": "assistant", "content": response.content})
    return "\n".join(text_parts).strip(), seen
