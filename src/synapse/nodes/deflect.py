"""Deflect node — return known fix + create a CLOSED deflected ticket."""
from __future__ import annotations
import logging

from synapse.db.base import AsyncSessionLocal
from synapse.db import repositories as repo
from synapse.state import AgentState, Message, Ticket

logger = logging.getLogger(__name__)


async def deflect_node(state: AgentState) -> dict:
    """Create a closed/deflected ticket and return the KB answer."""
    query = state.conversation[-1].content if state.conversation else "Unknown issue"
    answer = state.fastpath_answer or "Please check the known issue database."

    async with AsyncSessionLocal() as session:
        db_ticket = await repo.create_ticket(
            session,
            category="deflected",
            priority="P4",
            summary=f"[DEFLECTED] {query[:100]}",
            affected_ci=None,
        )
        await repo.update_ticket(session, db_ticket.id, status="closed")

    state_ticket = Ticket(
        id=db_ticket.id,
        status="closed",
        category="deflected",
        priority="P4",
        summary=f"[DEFLECTED] {query[:100]}",
    )

    reply = (
        f"I've seen something similar before — here's what fixed it:\n\n"
        f"{answer}\n\n"
        f"Give those steps a try. I've logged this as ticket **{db_ticket.id}** in case we need to follow up.\n\n"
        f"If it doesn't help, just say so (like \"that didn't work\") and I'll dig deeper and apply the fix automatically."
    )

    return {
        "tickets": {db_ticket.id: state_ticket},
        "active_ticket_id": db_ticket.id,
        "conversation": [Message(role="assistant", content=reply)],
    }
