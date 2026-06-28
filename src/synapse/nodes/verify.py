"""Verify node — execute runbook via Runbook MCP + check recovery."""
from __future__ import annotations
import logging

from synapse.state import AgentState, Message
from synapse.db.base import AsyncSessionLocal
from synapse.db import repositories as repo

logger = logging.getLogger(__name__)


async def verify_node(state: AgentState) -> dict:
    """Execute the approved runbook via Runbook MCP and verify recovery."""
    if state.pending_action is None or state.pending_action.status != "approved":
        logger.error("verify_node reached without an approved action")
        return {"recovered": False}

    action = state.pending_action
    ticket_id = state.active_ticket_id

    try:
        from synapse.mcp_servers.runbook_client import execute_and_verify
        from synapse.exec_target import resolve_target

        # Resolve where this runbook should execute: user's PC or local server
        target = await resolve_target(ticket_id, state.user_id)
        if target.kind == "remote":
            logger.info(
                "Remote execution target resolved: %s → %s",
                ticket_id, target.label,
            )

        result = await execute_and_verify(
            runbook_id=action.runbook_id,
            parameters=action.parameters,
            target=target,
        )
        recovered: bool = result.get("recovered", False)

        # Log action in DB
        if ticket_id:
            async with AsyncSessionLocal() as session:
                status_str = "executed" if recovered else "failed"
                await repo.log_action(
                    session,
                    ticket_id=ticket_id,
                    runbook_id=action.runbook_id,
                    status=status_str,
                )

        updated_action = action.model_copy(
            update={"status": "executed" if recovered else "failed"}
        )

        if recovered:
            msg = "Your issue has been fixed! Everything looks good now. Let me know if anything else comes up."
        else:
            msg = "I tried the fix but couldn't fully resolve the issue. I'll escalate this to the IT team."

        return {
            "recovered": recovered,
            "pending_action": updated_action,
            "execution_summary": msg,
            "conversation": [Message(role="assistant", content=msg)],
        }

    except Exception as exc:
        logger.error("Runbook execution failed: %s", exc)
        if ticket_id:
            async with AsyncSessionLocal() as session:
                await repo.log_action(
                    session,
                    ticket_id=ticket_id,
                    runbook_id=action.runbook_id,
                    status="failed",
                )
        updated_action = action.model_copy(update={"status": "failed"})
        return {
            "recovered": False,
            "pending_action": updated_action,
            "conversation": [
                Message(
                    role="assistant",
                    content="Something went wrong while applying the fix. Putting together a report for the IT team.",
                )
            ],
        }
