"""Langfuse tracing — wrap LLM calls and graph nodes with trace spans.

Enabled only if LANGFUSE_PUBLIC_KEY + LANGFUSE_SECRET_KEY are set.
"""
from __future__ import annotations
import logging
from typing import Any

from synapse.config import settings

logger = logging.getLogger(__name__)

_langfuse = None


def get_langfuse():
    """Return the Langfuse client, or None if tracing is disabled."""
    global _langfuse
    if _langfuse is not None:
        return _langfuse
    if not settings.langfuse_enabled:
        return None
    try:
        from langfuse import Langfuse
        _langfuse = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
        logger.info("Langfuse tracing enabled")
        return _langfuse
    except Exception as exc:
        logger.warning("Langfuse unavailable: %s", exc)
        return None


def trace_node(node_name: str, session_id: str, input_data: Any, output_data: Any) -> None:
    """Record a node execution in Langfuse (best-effort)."""
    lf = get_langfuse()
    if lf is None:
        return
    try:
        trace = lf.trace(name=node_name, session_id=session_id)
        trace.span(
            name=node_name,
            input=str(input_data)[:1000],
            output=str(output_data)[:1000],
        )
    except Exception as exc:
        logger.debug("Langfuse trace failed: %s", exc)


def trace_llm_call(agent: str, session_id: str, prompt: str, response: str, model: str) -> None:
    """Record an LLM call in Langfuse."""
    lf = get_langfuse()
    if lf is None:
        return
    try:
        trace = lf.trace(name=f"llm_{agent}", session_id=session_id)
        trace.generation(
            name=agent,
            model=model,
            prompt=prompt[:2000],
            completion=response[:2000],
        )
    except Exception as exc:
        logger.debug("Langfuse LLM trace failed: %s", exc)
