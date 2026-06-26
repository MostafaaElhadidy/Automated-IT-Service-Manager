"""Ingest resolved incidents into Chroma for RAG retrieval.

Run: python -m synapse.rag.ingest
"""
from __future__ import annotations
import asyncio
import logging
import uuid
from typing import Any

import chromadb

from synapse.config import settings

logger = logging.getLogger(__name__)
COLLECTION_NAME = "incident_kb"

# ── Seed knowledge base ───────────────────────────────────────────────────────
# Format: {symptom, root_cause, remediation_id, resolution}
SEED_INCIDENTS: list[dict[str, str]] = [
    {
        "symptom": "Sales dashboard unreachable, users cannot access the sales dashboard application",
        "root_cause": "WEB-02 worker pool exhausted — too many concurrent connections caused all workers to hang",
        "remediation_id": "restart_web_service",
        "resolution": "Restart the web service on WEB-02 to clear worker pool exhaustion. Run: restart_web_service on host=WEB-02",
    },
    {
        "symptom": "DB connection pool exhausted on PostgreSQL primary, billing application extremely slow",
        "root_cause": "DB-01 connection pool limit reached — too many idle connections not being recycled",
        "remediation_id": "restart_db_connection_pool",
        "resolution": "Restart the DB connection pool manager to recycle stale connections. Run: restart_db_connection_pool on host=DB-01",
    },
    {
        "symptom": "Redis cache stampede causing high latency and CPU spikes on sales dashboard",
        "root_cause": "REDIS-01 cache keys expired simultaneously causing a thundering herd — cache stampede",
        "remediation_id": "clear_cache",
        "resolution": "Clear and reinitialize the Redis cache to break the stampede. Run: clear_cache on host=REDIS-01",
    },
    {
        "symptom": "Web server high CPU usage causing slow response times across all pages",
        "root_cause": "Worker threads spawned excessively due to a runaway background job consuming all CPU",
        "remediation_id": "restart_web_service",
        "resolution": "Restart the web service to kill runaway threads. Run: restart_web_service",
    },
    {
        "symptom": "Application returns 503 Service Unavailable errors intermittently",
        "root_cause": "Load balancer health checks failing due to backend server overload, routing to failed instances",
        "remediation_id": "restart_web_service",
        "resolution": "Restart overloaded backend web servers to restore health check compliance",
    },
    {
        "symptom": "Database queries timing out, application showing database connection errors",
        "root_cause": "Long-running queries blocking connection slots, connection pool starved",
        "remediation_id": "restart_db_connection_pool",
        "resolution": "Restart DB connection pool to terminate stale connections and allow new ones",
    },
    {
        "symptom": "CRM application login page loads very slowly or times out",
        "root_cause": "Auth service overloaded with too many simultaneous authentication requests",
        "remediation_id": "scale_workers",
        "resolution": "Scale up the authentication service workers to handle increased load",
    },
    {
        "symptom": "Billing application failing to process payments, timeout errors on checkout",
        "root_cause": "Message queue (RabbitMQ) backlog causing payment events to queue indefinitely",
        "remediation_id": "restart_db_connection_pool",
        "resolution": "Clear message queue backlog and restart processing workers",
    },
    {
        "symptom": "HR portal showing blank pages or partial data after recent deployment",
        "root_cause": "Database schema mismatch after migration — app reading stale cached schema",
        "remediation_id": "clear_cache",
        "resolution": "Clear application cache to force schema refresh from database",
    },
    {
        "symptom": "WEB-02 error rate spiking above 5%, multiple 500 errors in logs",
        "root_cause": "WEB-02 worker pool exhausted due to memory leak in request handler",
        "remediation_id": "restart_web_service",
        "resolution": "Restart web service on WEB-02 to free memory and reset worker pool",
    },
    {
        "symptom": "Network latency spiking between web servers and database, queries slow",
        "root_cause": "Core switch high packet loss due to spanning tree reconvergence",
        "remediation_id": "restart_web_service",
        "resolution": "Switch issue requires network team. Restart affected services as a workaround",
    },
    {
        "symptom": "Monitoring alerts not firing, Grafana dashboards showing stale data",
        "root_cause": "Prometheus scrape job failing due to target unreachable — metric endpoint down",
        "remediation_id": "restart_web_service",
        "resolution": "Restart the monitoring target service to restore metric endpoint",
    },
    {
        "symptom": "Sales dashboard slow to load charts, data appears outdated",
        "root_cause": "Redis cache serving expired data due to incorrect TTL configuration",
        "remediation_id": "clear_cache",
        "resolution": "Clear Redis cache and restart web service to force fresh data load",
    },
    {
        "symptom": "Application CPU at 100%, health checks failing",
        "root_cause": "Scale-out needed — current worker count insufficient for current load",
        "remediation_id": "scale_workers",
        "resolution": "Scale workers to distribute load. Run: scale_workers",
    },
    {
        "symptom": "Memory usage growing continuously on web server, out of memory errors",
        "root_cause": "Memory leak in web application worker process — workers never releasing memory",
        "remediation_id": "restart_web_service",
        "resolution": "Restart web service workers to reclaim leaked memory",
    },
]


def _get_collection() -> chromadb.Collection:
    client = chromadb.PersistentClient(path=settings.chroma_dir)
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


async def ingest_all() -> None:
    """Embed and store all seed incidents into Chroma."""
    collection = _get_collection()

    ids = []
    documents = []
    metadatas: list[dict[str, Any]] = []

    for i, inc in enumerate(SEED_INCIDENTS):
        doc_id = f"seed_{i:04d}"
        # Document text: symptom + root_cause (what the user describes + diagnosis)
        doc_text = f"{inc['symptom']} | {inc['root_cause']}"
        ids.append(doc_id)
        documents.append(doc_text)
        metadatas.append(
            {
                "symptom": inc["symptom"],
                "root_cause": inc["root_cause"],
                "remediation_id": inc["remediation_id"],
                "resolution": inc["resolution"],
            }
        )

    # Upsert (idempotent)
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        lambda: collection.upsert(ids=ids, documents=documents, metadatas=metadatas),
    )
    logger.info("[ingest] %d incidents ingested into Chroma collection '%s'", len(ids), COLLECTION_NAME)
    print(f"[ingest] {len(ids)} incidents ingested into Chroma.")


async def ingest_resolution(
    symptom: str,
    root_cause: str,
    remediation_id: str,
    ticket_id: str,
) -> None:
    """Write a newly resolved incident back to Chroma (learning loop)."""
    collection = _get_collection()
    doc_id = f"resolved_{ticket_id}"
    doc_text = f"{symptom} | {root_cause}"
    resolution_text = f"Run the '{remediation_id}' runbook to resolve this issue."

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        lambda: collection.upsert(
            ids=[doc_id],
            documents=[doc_text],
            metadatas=[
                {
                    "symptom": symptom,
                    "root_cause": root_cause,
                    "remediation_id": remediation_id,
                    "resolution": resolution_text,
                    "ticket_id": ticket_id,
                }
            ],
        ),
    )
    logger.info("[ingest] Resolution for ticket %s written to Chroma", ticket_id)


if __name__ == "__main__":
    asyncio.run(ingest_all())
