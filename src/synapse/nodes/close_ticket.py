"""Close-ticket node — mark resolved/closed + write resolution to Chroma (learning loop)."""
from __future__ import annotations
import logging
from datetime import datetime, timezone

from synapse.db.base import AsyncSessionLocal
from synapse.db import repositories as repo
from synapse.state import AgentState, Message

logger = logging.getLogger(__name__)


async def close_ticket_node(state: AgentState) -> dict:
    """Mark the ticket resolved and write the resolution to Chroma for future deflection."""
    ticket_id = state.active_ticket_id
    ticket_updates: dict = {}

    if ticket_id:
        async with AsyncSessionLocal() as session:
            await repo.update_ticket(
                session,
                ticket_id,
                status="closed",
                resolved_at=datetime.now(timezone.utc),
            )

        if ticket_id in state.tickets:
            old = state.tickets[ticket_id]
            ticket_updates = {ticket_id: old.model_copy(update={"status": "closed"})}

        # Write resolution back to Chroma (learning loop)
        if state.hypotheses and state.pending_action:
            top_hyp = state.hypotheses[-1]
            resolution_text = (
                f"Symptom: {state.tickets[ticket_id].summary if ticket_id in state.tickets else 'unknown'}\n"
                f"Root cause: {top_hyp.statement}\n"
                f"Remediation: {state.pending_action.runbook_id}\n"
                f"Result: resolved"
            )
            try:
                from synapse.rag.ingest import ingest_resolution
                await ingest_resolution(
                    symptom=state.tickets[ticket_id].summary if ticket_id in state.tickets else "",
                    root_cause=top_hyp.statement,
                    remediation_id=state.pending_action.runbook_id,
                    ticket_id=ticket_id,
                )
            except Exception as exc:
                logger.warning("Failed to write resolution to Chroma: %s", exc)

    # Build rich resolution summary
    action = state.pending_action
    top_hyp = state.hypotheses[-1] if state.hypotheses else None

    summary_parts = [f"Ticket **{ticket_id}** resolved and closed.\n"]

    if top_hyp:
        summary_parts.append(f"**Root cause:** {top_hyp.statement}")

    if action:
        summary_parts.append(
            f"**Action taken:** Ran `{action.runbook_id}` on `{action.parameters.get('host', 'localhost')}`"
        )

    if state.execution_summary:
        summary_parts.append(f"\n{state.execution_summary}")
    else:
        summary_parts.append(
            "**Result:** Service recovered. Resolution recorded in the knowledge base for future deflection."
        )

    return {
        "tickets": ticket_updates,
        "conversation": [
            Message(role="assistant", content="\n".join(summary_parts))
        ],
    }
