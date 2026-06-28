"""Thin async client for the Runbook MCP server.

Calls the server's tools via HTTP (when running as HTTP server) or imports directly
(when running in-process for tests).
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


async def list_runbooks_from_mcp() -> list[dict]:
    """Get runbook catalogue. Falls back to direct import if MCP server not running."""
    try:
        from synapse.mcp_servers.runbook_server import list_runbooks
        return list_runbooks()
    except Exception as exc:
        logger.warning("Runbook MCP list failed: %s", exc)
        return []


async def get_plan_from_mcp(runbook_id: str, parameters: dict) -> dict:
    """Get human-readable plan for a runbook."""
    try:
        from synapse.mcp_servers.runbook_server import get_plan
        return get_plan(runbook_id=runbook_id, parameters=parameters)
    except Exception as exc:
        logger.warning("Runbook MCP get_plan failed: %s", exc)
        return {"plan": f"Execute {runbook_id} with {parameters}"}


async def execute_and_verify(
    runbook_id: str,
    parameters: dict,
    target=None,  # ExecTarget — LocalTarget | RemoteTarget (imported lazily)
) -> dict:
    """Execute runbook + verify recovery. Returns {recovered, before, after, steps}.

    When target is a RemoteTarget and the runbook is remote-capable, dispatches
    the command to the user's PC via MeshCentral and awaits the self-report
    callback. Otherwise falls through to local execution (existing behaviour).
    """
    from synapse.mcp_servers.runbook_server import (
        execute_runbook,
        execute_runbook_remote,
        verify_recovery,
        _CATALOGUE,
    )
    from synapse.exec_target import RemoteTarget, is_remote_capable

    target_metric: str = _CATALOGUE.get(runbook_id, {}).get("target_metric", "error_rate")
    ci_id: str = str(parameters.get("host", "unknown"))

    # ── Remote execution path ─────────────────────────────────────────────────
    if (
        target is not None
        and isinstance(target, RemoteTarget)
        and is_remote_capable(runbook_id)
    ):
        exec_result = await execute_runbook_remote(
            runbook_id=runbook_id,
            parameters=parameters,
            nodeid=target.nodeid,
            os_platform=target.os_platform,
        )
        # Remote verify: check the last step's ok flag as the recovery signal.
        # The remote script itself ran the verification probe and reported it.
        steps = exec_result.get("steps", [])
        final = next((s for s in reversed(steps) if s.get("step") == "complete"), None)
        recovered = final["ok"] if final else exec_result.get("status") == "executed"
        return {
            "recovered": recovered,
            "before": exec_result.get("before", {}),
            "after": exec_result.get("after", {}),
            "steps": steps,
            "verify": {"recovered": recovered, "metric": target_metric, "remote": True},
        }

    # ── Local execution path (existing behaviour) ─────────────────────────────
    exec_result = execute_runbook(runbook_id=runbook_id, parameters=parameters)
    verify_result = verify_recovery(target_metric=target_metric, ci_id=ci_id)

    return {
        "recovered": verify_result["recovered"],
        "before": exec_result.get("before", {}),
        "after": exec_result.get("after", {}),
        "steps": exec_result.get("steps", []),
        "verify": verify_result,
    }
