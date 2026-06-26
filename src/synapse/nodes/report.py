"""Report node — create a reports row from hypothesis + action log."""
from __future__ import annotations
import json
import logging

from synapse.db.base import AsyncSessionLocal
from synapse.db import repositories as repo
from synapse.state import AgentState, Message

logger = logging.getLogger(__name__)


async def report_node(state: AgentState) -> dict:
    """Generate a structured failure report and persist it."""
    ticket_id = state.active_ticket_id

    # Build report body
    hyp_section = "No hypothesis generated."
    if state.hypotheses:
        top = state.hypotheses[-1]
        evidence_lines = "\n".join(
            f"  - [{f.source}] {f.snippet} (weight={f.weight:.2f})"
            for f in top.evidence
        )
        hyp_section = (
            f"Root cause hypothesis:\n{top.statement}\n"
            f"Confidence: {top.confidence:.0%}\n"
            f"Evidence:\n{evidence_lines}"
        )

    action_section = "No action attempted."
    if state.pending_action:
        action_section = (
            f"Runbook attempted: {state.pending_action.runbook_id}\n"
            f"Parameters: {json.dumps(state.pending_action.parameters)}\n"
            f"Result: {state.pending_action.status}"
        )

    body = (
        f"INCIDENT REPORT\n"
        f"{'='*60}\n"
        f"Ticket: {ticket_id}\n\n"
        f"{hyp_section}\n\n"
        f"Actions tried:\n{action_section}\n\n"
        f"Status: UNRESOLVED — escalated to IT team."
    )

    if ticket_id:
        async with AsyncSessionLocal() as session:
            await repo.create_report(session, ticket_id=ticket_id, body=body)
            await repo.update_ticket(session, ticket_id, status="escalated")

    ticket_updates: dict = {}
    if ticket_id and ticket_id in state.tickets:
        old = state.tickets[ticket_id]
        ticket_updates = {ticket_id: old.model_copy(update={"status": "escalated"})}

    return {
        "tickets": ticket_updates,
        "conversation": [
            Message(
                role="assistant",
                content=(
                    f"Automated remediation failed. A detailed incident report has been generated "
                    f"for ticket **{ticket_id}**."
                ),
            )
        ],
    }
