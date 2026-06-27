"""FastAPI application — compiles the graph once and runs the monitoring loop as a lifespan task."""
from __future__ import annotations
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from synapse.graph import build_graph
from synapse.agents.monitoring import run_monitoring_loop, drain_alerts
from synapse.api.routers import chat, tickets, cmdb, metrics, approvals, health, alerts, auth, devices

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("SynapseITSM starting up...")

    # Compile the graph once (uses MemorySaver by default; swap for PostgresSaver in prod)
    app.state.graph = build_graph()
    logger.info("LangGraph compiled")

    # Monitoring alert queue
    app.state.alerts = asyncio.Queue()

    # Background tasks: monitoring loop + drain + MeshCentral status refresh
    async def _mesh_refresh_loop():
        from synapse.mcp_servers import meshcentral_client
        from synapse.config import settings
        while True:
            await asyncio.sleep(60)
            if settings.meshcentral_enabled:
                try:
                    await meshcentral_client.refresh_online_status()
                except Exception as exc:
                    logger.debug("MeshCentral status refresh failed: %s", exc)

    app.state.tasks = [
        asyncio.create_task(run_monitoring_loop(app.state.alerts), name="monitoring_loop"),
        asyncio.create_task(drain_alerts(app.state.alerts, app.state.graph), name="drain_alerts"),
        asyncio.create_task(_mesh_refresh_loop(), name="mesh_refresh"),
    ]
    logger.info("Monitoring tasks started")

    yield

    logger.info("SynapseITSM shutting down...")
    for task in app.state.tasks:
        task.cancel()
    await asyncio.gather(*app.state.tasks, return_exceptions=True)


app = FastAPI(
    title="SynapseITSM",
    description="Multi-agent ITSM system with LangGraph orchestration",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register all routers
for r in (auth, chat, tickets, cmdb, metrics, approvals, health, alerts, devices):
    app.include_router(r.router)
