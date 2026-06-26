"""Runbook MCP server unit tests — whitelist enforcement + verify."""
from __future__ import annotations
import pytest
from synapse.mcp_servers.runbook_server import (
    list_runbooks,
    get_plan,
    execute_runbook,
    verify_recovery,
    set_metric,
    _CATALOGUE,
)


def test_list_runbooks():
    runbooks = list_runbooks()
    ids = {r["id"] for r in runbooks}
    assert "restart_web_service" in ids
    assert "restart_db_connection_pool" in ids
    assert "clear_cache" in ids
    assert "scale_workers" in ids


def test_get_plan():
    plan_result = get_plan("restart_web_service", {"host": "WEB-02", "service": "gunicorn"})
    assert "plan" in plan_result
    assert "restart_web_service" in plan_result["plan"].lower() or "web service" in plan_result["plan"].lower()


def test_whitelist_enforcement():
    with pytest.raises((ValueError, KeyError)):
        execute_runbook("rm_rf_everything", {"host": "WEB-02"})


def test_execute_runbook():
    # Set a high error rate first
    set_metric("error_rate", "WEB-02", 0.80)
    result = execute_runbook("restart_web_service", {"host": "WEB-02", "service": "gunicorn"})
    assert result["status"] == "executed"
    assert result["after"]["error_rate"] < 0.05  # sim_effect brings it down


def test_verify_recovery_after_execution():
    set_metric("error_rate", "WEB-01", 0.001)
    result = verify_recovery("error_rate", "WEB-01")
    assert result["recovered"] is True


def test_verify_recovery_failure():
    set_metric("error_rate", "WEB-99", 0.95)
    result = verify_recovery("error_rate", "WEB-99")
    assert result["recovered"] is False


def test_get_plan_unknown_runbook():
    result = get_plan("nonexistent_runbook", {})
    assert "error" in result
