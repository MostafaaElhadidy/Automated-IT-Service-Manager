"""Notify-IT node — mark escalated, surface report to IT team."""
from __future__ import annotations
import logging

from synapse.state import AgentState, Message

logger = logging.getLogger(__name__)


async def notify_it_node(state: AgentState) -> dict:
    """Mark ticket escalated and notify the IT team (stub: log + state flag)."""
    ticket_id = state.active_ticket_id

    # In a real system this would page PagerDuty, send email, or post to Slack.
    # For demo, we log and surface the message.
    logger.warning(
        "IT TEAM NOTIFICATION: Ticket %s escalated — automated remediation failed.",
        ticket_id,
    )

    ticket_updates: dict = {}
    if ticket_id and ticket_id in state.tickets:
        old = state.tickets[ticket_id]
        ticket_updates = {ticket_id: old.model_copy(update={"status": "escalated"})}

    return {
        "escalated_to_human": True,
        "tickets": ticket_updates,
        "conversation": [
            Message(
                role="assistant",
                content=(
                    f"I've handed this off to the IT team with a full report (ticket **{ticket_id}**). "
                    "They'll reach out to you soon."
                ),
            )
        ],
    }
