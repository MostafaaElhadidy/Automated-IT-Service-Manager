"""Thin async client for the Runbook MCP server.

Calls the server's tools via HTTP (when running as HTTP server) or imports directly
(when running in-process for tests).
"""
from __future__ import annotations
import logging
from typing import Any

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


async def execute_and_verify(runbook_id: str, parameters: dict) -> dict:
    """Execute runbook + verify recovery. Returns {recovered, before, after}."""
    from synapse.mcp_servers.runbook_server import (
        execute_runbook,
        verify_recovery,
        _CATALOGUE,
    )

    # Execute
    exec_result = execute_runbook(runbook_id=runbook_id, parameters=parameters)

    # Verify
    target_metric: str = _CATALOGUE.get(runbook_id, {}).get("target_metric", "error_rate")
    ci_id: str = str(parameters.get("host", "unknown"))
    verify_result = verify_recovery(target_metric=target_metric, ci_id=ci_id)

    return {
        "recovered": verify_result["recovered"],
        "before": exec_result.get("before", {}),
        "after": exec_result.get("after", {}),
        "steps": exec_result.get("steps", []),
        "verify": verify_result,
    }
