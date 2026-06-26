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

        result = await execute_and_verify(
            runbook_id=action.runbook_id,
            parameters=action.parameters,
        )
        recovered: bool = result.get("recovered", False)
        before = result.get("before", {})
        after = result.get("after", {})

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

        steps = result.get("steps", [])
        step_log = "\n".join(
            f"  - [{'OK' if s.get('ok') else 'FAIL'}] **{s['step']}**: {s['output']}"
            for s in steps
        ) if steps else "  (no step details)"

        if recovered:
            msg = (
                f"**Runbook `{action.runbook_id}` executed successfully.**\n\n"
                f"**Execution steps:**\n{step_log}\n\n"
                f"**Before:** {before}\n"
                f"**After:** {after}\n\n"
                f"Service has recovered."
            )
        else:
            msg = (
                f"**Runbook `{action.runbook_id}` executed — recovery not yet confirmed.**\n\n"
                f"**Execution steps:**\n{step_log}\n\n"
                f"**Before:** {before}\n"
                f"**After:** {after}\n\n"
                f"Generating failure report..."
            )

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
                    content=f"Runbook execution error: {exc}. Generating failure report.",
                )
            ],
        }
