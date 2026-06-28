"""HITL gate — interrupt() until approved/rejected."""
from __future__ import annotations
import logging

from langgraph.types import interrupt

from synapse.state import AgentState, Message

logger = logging.getLogger(__name__)


async def hitl_node(state: AgentState) -> dict:
    """Pause the graph via interrupt() until the operator approves or rejects the action."""
    if state.pending_action is None:
        logger.error("hitl_node reached with no pending_action")
        return {"escalated_to_human": True}

    # Surfaces pending_action to the API caller; graph pauses here.
    resume_data: dict = interrupt(
        {
            "type": "hitl_approval",
            "runbook_id": state.pending_action.runbook_id,
            "plan": state.pending_action.plan,
            "parameters": state.pending_action.parameters,
        }
    )

    # Resume path: approval endpoint sends Command(resume={"approved": True/False})
    approved: bool = resume_data.get("approved", False)

    if approved:
        updated_action = state.pending_action.model_copy(update={"status": "approved"})
        return {
            "pending_action": updated_action,
            "conversation": [
                Message(role="assistant", content="Approved — applying the fix now...")
            ],
        }
    else:
        return {
            "escalated_to_human": True,
            "conversation": [
                Message(role="assistant", content="Got it. I'll hand this off to the IT team instead.")
            ],
        }


async def escalate_human_node(state: AgentState) -> dict:
    """Fallback-to-human — mark escalated and end."""
    ticket_updates: dict = {}
    if state.active_ticket_id:
        from synapse.db.base import AsyncSessionLocal
        from synapse.db import repositories as repo

        async with AsyncSessionLocal() as session:
            await repo.update_ticket(session, state.active_ticket_id, status="escalated")

        if state.active_ticket_id in state.tickets:
            old = state.tickets[state.active_ticket_id]
            ticket_updates = {
                state.active_ticket_id: old.model_copy(update={"status": "escalated"})
            }

    return {
        "escalated_to_human": True,
        "tickets": ticket_updates,
        "conversation": [
            Message(
                role="assistant",
                content=(
                    "I've flagged this for the IT team. A specialist will reach out to you shortly."
                ),
            )
        ],
    }
