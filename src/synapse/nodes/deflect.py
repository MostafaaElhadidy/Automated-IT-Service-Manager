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
        f"I found a similar past incident in our knowledge base. Here is the **suggested fix** "
        f"— note that nothing has been executed yet, this is a manual recommendation:\n\n"
        f"{answer}\n\n"
        f"**Please try the steps above yourself.** "
        f"Ticket **{db_ticket.id}** has been logged.\n\n"
        f"If this doesn't resolve your issue, reply with something like "
        f"\"that didn't help\" and I'll run a full diagnostic and execute the fix automatically."
    )

    return {
        "tickets": {db_ticket.id: state_ticket},
        "active_ticket_id": db_ticket.id,
        "conversation": [Message(role="assistant", content=reply)],
    }
