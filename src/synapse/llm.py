"""LiteLLM wrapper with per-agent routing and Ollama fallback.

Usage:
    response = await call_llm("intake", messages, response_format=MyModel)
"""
from __future__ import annotations
import json
import logging
from typing import Any, Type, TypeVar

from pydantic import BaseModel

from synapse.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


def _get_litellm():
    import litellm as _litellm
    _litellm.set_verbose = False
    _litellm.drop_params = True
    return _litellm


def _build_messages(system: str, user: str) -> list[dict]:
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


async def call_llm(
    agent: str,
    messages: list[dict],
    *,
    response_format: Type[T] | None = None,
    temperature: float = 0.1,
    max_retries: int = 2,
) -> str | T:
    """Call LLM with per-agent routing. Returns parsed Pydantic model if response_format given."""
    kwargs = settings.litellm_kwargs(agent)
    kwargs["messages"] = messages
    kwargs["temperature"] = temperature

    if response_format is not None:
        schema = response_format.model_json_schema()
        system_json = (
            f"\nRespond ONLY with valid JSON matching this schema (no markdown fences):\n"
            f"{json.dumps(schema, indent=2)}"
        )
        # Prepend schema instruction to system message
        if messages and messages[0]["role"] == "system":
            messages[0]["content"] += system_json
        else:
            messages.insert(0, {"role": "system", "content": system_json.strip()})

    litellm = _get_litellm()
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            response = await litellm.acompletion(**kwargs)
            text: str = response.choices[0].message.content or ""
            if response_format is not None:
                return _parse_json_response(text, response_format)
            return text
        except Exception as exc:
            last_exc = exc
            logger.warning("LLM call attempt %d/%d failed: %s", attempt + 1, max_retries + 1, exc)
            if attempt < max_retries:
                # Try Ollama fallback on subsequent attempts
                kwargs["model"] = "ollama/phiii3:latest"
                kwargs["api_base"] = settings.ollama_base_url
                kwargs.pop("api_key", None)

    raise RuntimeError(f"LLM call failed after {max_retries + 1} attempts: {last_exc}") from last_exc


def _parse_json_response(text: str, model_cls: Type[T]) -> T:
    # Strip markdown fences if present
    clean = text.strip()
    if clean.startswith("```"):
        lines = clean.split("\n")
        clean = "\n".join(lines[1:-1]) if len(lines) > 2 else clean
    return model_cls.model_validate_json(clean)


class FakeLLM:
    """Deterministic fake for tests — never hits the network."""

    def __init__(self, responses: dict[str, Any]):
        self._responses = responses

    async def __call__(self, agent: str, messages: list[dict], **kwargs: Any) -> Any:
        response_format = kwargs.get("response_format")
        raw = self._responses.get(agent, "{}")
        if response_format is not None:
            if isinstance(raw, BaseModel):
                return raw
            return response_format.model_validate(raw if isinstance(raw, dict) else json.loads(raw))
        return raw if isinstance(raw, str) else json.dumps(raw)
