"""Fast-path node — embed query, Chroma lookup, set fastpath_score."""
from __future__ import annotations
import logging

from synapse.config import settings
from synapse.state import AgentState
from synapse.rag.retriever import retrieve_similar

logger = logging.getLogger(__name__)


async def fast_path_node(state: AgentState) -> dict:
    """Embed the user query and check Chroma for a high-confidence known fix."""
    query = state.conversation[-1].content if state.conversation else ""
    if not query:
        return {"fastpath_score": 0.0, "fastpath_answer": ""}

    try:
        results = await retrieve_similar(query, n_results=1)
        if results:
            top = results[0]
            score: float = top.get("score", 0.0)
            answer: str = top.get("resolution", top.get("document", ""))
            return {"fastpath_score": score, "fastpath_answer": answer}
    except Exception as exc:
        logger.warning("Fast-path Chroma lookup failed: %s", exc)

    return {"fastpath_score": 0.0, "fastpath_answer": ""}
