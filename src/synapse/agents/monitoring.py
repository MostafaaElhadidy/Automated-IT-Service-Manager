"""Monitoring agent — async loop; anomaly detection → alert queue → drain → incident path.

NOT a graph node. Started as a lifespan background task.
"""
from __future__ import annotations
import asyncio
import logging
import uuid
from typing import Any

from synapse.config import settings
from synapse.sim.generator import AnomalyEvent, stream_anomalies
from synapse.db.base import AsyncSessionLocal
from synapse.db import repositories as repo
from synapse.state import Message

logger = logging.getLogger(__name__)

_METRIC_THRESHOLDS: dict[str, float] = {
    "error_rate": 0.10,
    "db_connections": 80,
    "cache_hit_rate": 0.30,
    "cpu_usage": 0.85,
}


def _is_anomalous(metric: str, value: float) -> bool:
    threshold = _METRIC_THRESHOLDS.get(metric)
    if threshold is None:
        return False
    if metric == "cache_hit_rate":
        return value < threshold
    return value > threshold


async def run_monitoring_loop(alert_queue: asyncio.Queue) -> None:
    """Continuously read simulated metric stream and enqueue anomaly events."""
    logger.info("[monitoring] Starting monitoring loop (SIM_SEED=%d)", settings.sim_seed)
    try:
        async for event in stream_anomalies():
            if _is_anomalous(event.metric, event.value):
                logger.warning(
                    "[monitoring] ANOMALY detected: ci=%s metric=%s value=%.3f",
                    event.ci_id, event.metric, event.value,
                )
                await alert_queue.put(event)
    except asyncio.CancelledError:
        logger.info("[monitoring] Monitoring loop cancelled")
    except Exception as exc:
        logger.error("[monitoring] Monitoring loop crashed: %s", exc, exc_info=True)


async def drain_alerts(alert_queue: asyncio.Queue, graph: Any) -> None:
    """Consume anomaly events from the queue; create tickets and invoke the graph."""
    logger.info("[monitoring] Alert drain task started")
    try:
        while True:
            event: AnomalyEvent = await alert_queue.get()
            try:
                await _handle_alert(event, graph)
            except Exception as exc:
                logger.error("[monitoring] Failed to handle alert for %s: %s", event.ci_id, exc, exc_info=True)
            finally:
                alert_queue.task_done()
            # Brief pause between alerts so the LLM API isn't flooded
            # when several scenarios fire in the same minute
            await asyncio.sleep(15)
    except asyncio.CancelledError:
        logger.info("[monitoring] Alert drain cancelled")


async def _handle_alert(event: AnomalyEvent, graph: Any) -> None:
    """Create a ticket for a monitoring anomaly and run the incident path."""
    async with AsyncSessionLocal() as session:
        # ── Layer 1: Deduplication ────────────────────────────────────────────
        existing = await repo.find_open_monitoring_ticket(session, event.ci_id)
        if existing:
            logger.info(
                "[monitoring] Skipping duplicate alert for ci=%s — open ticket %s already exists",
                event.ci_id, existing.id,
            )
            return

        # Determine priority from CMDB impact
        impact = await repo.ci_impact(session, event.ci_id)
        from synapse.tools.priority import _impact_score, _MATRIX
        impact_score = _impact_score(impact["dependents"], impact["criticality"])
        priority = _MATRIX.get((impact_score, 1), "P2")

        db_ticket = await repo.create_ticket(
            session,
            category="incident",
            priority=priority,
            summary=f"[AUTO] {event.description} — {event.metric}={event.value:.3f}",
            affected_ci=event.ci_id,
        )

    ticket_id = db_ticket.id
    session_id = f"mon_{uuid.uuid4().hex[:8]}"
    logger.info("[monitoring] Auto-created ticket %s for ci=%s", ticket_id, event.ci_id)

    # ── Layer 3: Email alert ──────────────────────────────────────────────────
    from synapse.tools.email_alert import send_monitoring_alert
    await send_monitoring_alert(
        ticket_id=ticket_id,
        ci_id=event.ci_id,
        metric=event.metric,
        value=event.value,
        priority=priority,
        summary=db_ticket.summary,
    )

    from synapse.state import Ticket as StateTicket
    state_ticket = StateTicket(
        id=ticket_id,
        status="new",
        category="incident",
        priority=priority,
        affected_ci=event.ci_id,
        summary=db_ticket.summary,
    )

    input_state = {
        "user_id": "monitoring_system",
        "session_id": session_id,
        "chat_history": [],
        "conversation": [
            Message(
                role="user",
                content=(
                    f"Automated monitoring alert: {event.description}. "
                    f"Metric {event.metric}={event.value:.3f} on {event.ci_id}"
                ),
            )
        ],
        "tickets": {ticket_id: state_ticket},
        "active_ticket_id": ticket_id,
        "request_type": "incident",
        "fastpath_score": 0.0,
        "fastpath_answer": "",
        "pending_action": None,
        "hypotheses": [],
        "findings": [],
        "recovered": False,
        "escalated_to_human": False,
        "execution_summary": "",
    }

    config = {"configurable": {"thread_id": session_id}}

    try:
        result = await graph.ainvoke(input_state, config=config)
        logger.info("[monitoring] Graph completed for ticket %s", ticket_id)

        # ── Layer 2: Register pending action so dashboard can show it ─────────
        _register_pending(result, session_id, ticket_id, db_ticket.summary, priority)
    except Exception as exc:
        logger.error("[monitoring] Graph failed for ticket %s: %s", ticket_id, exc, exc_info=True)


def _register_pending(
    result: Any,
    session_id: str,
    ticket_id: str,
    ticket_summary: str,
    ticket_priority: str,
) -> None:
    """Extract pending_action from the graph result and register in dashboard store."""
    from synapse.api import pending_store

    if isinstance(result, dict):
        pending = result.get("pending_action")
        hyps = result.get("hypotheses", [])
    else:
        pending = getattr(result, "pending_action", None)
        hyps = getattr(result, "hypotheses", [])

    if not pending:
        logger.info("[monitoring] No pending_action for ticket %s — nothing to register", ticket_id)
        return

    root_cause = "Root cause analysis pending"
    if hyps:
        last_hyp = hyps[-1]
        root_cause = (
            last_hyp.get("statement", root_cause)
            if isinstance(last_hyp, dict)
            else last_hyp.statement
        )

    if isinstance(pending, dict):
        runbook_id = pending.get("runbook_id", "")
        plan = pending.get("plan", "")
        parameters = pending.get("parameters", {})
    else:
        runbook_id = pending.runbook_id
        plan = pending.plan
        parameters = pending.parameters

    if not runbook_id:
        return

    pending_store.register(
        session_id=session_id,
        action_id=runbook_id,
        runbook_id=runbook_id,
        plan=plan,
        parameters=parameters,
        root_cause=root_cause,
        ticket_id=ticket_id,
        ticket_summary=ticket_summary,
        ticket_priority=ticket_priority,
    )
    logger.info(
        "[monitoring] Registered pending approval for ticket %s (runbook=%s)",
        ticket_id, runbook_id,
    )
