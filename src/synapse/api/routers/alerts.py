"""Alert streaming endpoint — SSE stream of proactive monitoring alerts."""
from __future__ import annotations
import asyncio
import json
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from synapse.api.deps import get_alert_queue

router = APIRouter(prefix="/alerts", tags=["alerts"])
logger = logging.getLogger(__name__)


@router.get("/stream")
async def alert_stream(alert_queue: asyncio.Queue = Depends(get_alert_queue)) -> StreamingResponse:
    """SSE stream delivering monitoring anomaly events to the dashboard."""
    async def event_gen():
        while True:
            try:
                event = alert_queue.get_nowait()
                data = json.dumps({
                    "ci_id": event.ci_id,
                    "metric": event.metric,
                    "value": event.value,
                    "description": event.description,
                    "timestamp": event.timestamp,
                })
                yield f"data: {data}\n\n"
            except asyncio.QueueEmpty:
                yield "data: {\"type\": \"heartbeat\"}\n\n"
                await asyncio.sleep(5)

    return StreamingResponse(event_gen(), media_type="text/event-stream")
