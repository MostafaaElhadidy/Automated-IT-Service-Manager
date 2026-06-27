"""Chroma retriever — similarity search over the incident knowledge base."""
from __future__ import annotations
import asyncio
import logging
from functools import lru_cache
from typing import Any

from synapse.config import settings

logger = logging.getLogger(__name__)

COLLECTION_NAME = "incident_kb"


def _get_chroma():
    try:
        import chromadb
        from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction  # noqa: F401
        return chromadb
    except ImportError:
        return None


@lru_cache(maxsize=1)
def _get_client():
    chroma = _get_chroma()
    if chroma is None:
        return None
    return chroma.PersistentClient(path=settings.chroma_dir)


def _get_collection():
    client = _get_client()
    if client is None:
        return None
    try:
        from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
        ef = SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
    except ImportError:
        ef = None  # fall back to ChromaDB default
    kwargs = {"name": COLLECTION_NAME, "metadata": {"hnsw:space": "cosine"}}
    if ef is not None:
        kwargs["embedding_function"] = ef
    return client.get_or_create_collection(**kwargs)


async def retrieve_similar(
    query: str,
    n_results: int = 3,
    score_threshold: float = 0.0,
) -> list[dict[str, Any]]:
    """Return top-n documents with cosine similarity scores."""
    collection = _get_collection()
    if collection is None:
        return []

    if collection.count() == 0:
        return []

    loop = asyncio.get_event_loop()
    results = await loop.run_in_executor(
        None,
        lambda: collection.query(
            query_texts=[query],
            n_results=min(n_results, collection.count()),
            include=["documents", "metadatas", "distances"],
        ),
    )

    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    output = []
    for doc, meta, dist in zip(docs, metas, distances):
        score = 1.0 - dist
        if score >= score_threshold:
            output.append(
                {
                    "document": doc,
                    "score": round(score, 4),
                    "resolution": meta.get("resolution", ""),
                    "symptom": meta.get("symptom", ""),
                    "root_cause": meta.get("root_cause", ""),
                    "remediation_id": meta.get("remediation_id", ""),
                }
            )

    return output
