"""End-to-end graph tests using a deterministic fake LLM (no network calls)."""
from __future__ import annotations
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch, MagicMock

from synapse.state import (
    AgentState,
    Message,
    Ticket,
    Finding,
    Hypothesis,
    Action,
)


# ── Fake LLM responses for deterministic testing ─────────────────────────────

FAKE_INTAKE_RESPONSE = {
    "request_type": "incident",
    "category": "incident",
    "affected_ci_hint": "WEB-02",
    "summary": "Sales dashboard unreachable — WEB-02 worker pool exhausted",
    "confidence": 0.92,
}

FAKE_RCA_RESPONSE = {
    "statement": "WEB-02 worker pool exhausted due to memory leak",
    "confidence": 0.88,
    "remediation_id": "restart_web_service",
    "evidence_from_cmdb": "WEB-02 depends on DB-01 and REDIS-01",
    "evidence_from_kb": "Past incident: WEB-02 worker pool exhausted → restart_web_service",
}

FAKE_REMEDIATION_RESPONSE = {
    "runbook_id": "restart_web_service",
    "parameters": {"host": "WEB-02", "service": "gunicorn"},
    "reasoning": "Restart web service to clear worker pool exhaustion",
}


@pytest.mark.asyncio
async def test_state_roundtrip():
    """AgentState can be created and updated correctly."""
    state = AgentState(user_id="u1", session_id="s1")
    state.conversation.append(Message(role="user", content="Dashboard is down!"))
    assert len(state.conversation) == 1


@pytest.mark.asyncio
async def test_cmdb_query_guard():
    """SELECT-only guard rejects DML statements."""
    from synapse.tools.cmdb_query import _assert_select_only
    # Valid SELECT should not raise
    _assert_select_only("SELECT id, name FROM configuration_items WHERE id = 'WEB-02'")

    # DML should raise
    with pytest.raises(ValueError, match="Only SELECT"):
        _assert_select_only("DELETE FROM tickets WHERE id = 'TKT-001'")

    with pytest.raises(ValueError, match="Only SELECT"):
        _assert_select_only("DROP TABLE configuration_items")

    with pytest.raises(ValueError, match="Only SELECT"):
        _assert_select_only("INSERT INTO tickets VALUES (1,2,3)")


@pytest.mark.asyncio
async def test_graph_compiles():
    """The graph must compile without errors."""
    from synapse.graph import build_graph
    graph = build_graph()
    assert graph is not None


@pytest.mark.asyncio
async def test_fast_path_below_threshold():
    """Fast-path with score below threshold routes to intake."""
    from synapse.graph import route_fast_path
    from synapse.config import settings
    state = AgentState(user_id="u1", session_id="s1", fastpath_score=0.1)
    assert route_fast_path(state) == "intake"


@pytest.mark.asyncio
async def test_fast_path_above_threshold():
    """Fast-path with score above threshold routes to deflect."""
    from synapse.graph import route_fast_path
    state = AgentState(user_id="u1", session_id="s1", fastpath_score=0.95)
    assert route_fast_path(state) == "deflect"


@pytest.mark.asyncio
async def test_route_entry_new_message():
    """New message (no prior closed ticket) → 'new'."""
    from synapse.graph import route_entry
    state = AgentState(
        user_id="u1",
        session_id="s1",
        conversation=[Message(role="user", content="Dashboard is down!")],
    )
    assert route_entry(state) == "new"


@pytest.mark.asyncio
async def test_route_entry_deflect_followup():
    """User says 'didn't help' after a closed deflected ticket → 'deflect_followup'."""
    from synapse.graph import route_entry
    ticket = Ticket(id="TKT-001", category="deflected", priority="P4", status="closed", summary="x")
    state = AgentState(
        user_id="u1",
        session_id="s1",
        conversation=[Message(role="user", content="That didn't help, still broken")],
        tickets={"TKT-001": ticket},
        active_ticket_id="TKT-001",
    )
    assert route_entry(state) == "deflect_followup"


@pytest.mark.asyncio
async def test_route_request_type_incident():
    """Incident request_type routes to RCA."""
    from synapse.graph import route_request_type
    state = AgentState(user_id="u1", session_id="s1", request_type="incident")
    assert route_request_type(state) == "incident"


@pytest.mark.asyncio
async def test_route_request_type_resolved():
    """Service request routes to END."""
    from synapse.graph import route_request_type
    state = AgentState(user_id="u1", session_id="s1", request_type="request")
    assert route_request_type(state) == "resolved"


@pytest.mark.asyncio
async def test_route_hitl_approved():
    """Approved pending_action routes to runbook."""
    from synapse.graph import route_hitl
    action = Action(runbook_id="restart_web_service", parameters={}, status="approved")
    state = AgentState(user_id="u1", session_id="s1", pending_action=action)
    assert route_hitl(state) == "approved"


@pytest.mark.asyncio
async def test_route_verify_succeeded():
    """Recovered=True routes to close_ticket."""
    from synapse.graph import route_verify
    state = AgentState(user_id="u1", session_id="s1", recovered=True)
    assert route_verify(state) == "succeeded"


@pytest.mark.asyncio
async def test_route_verify_failed():
    """Recovered=False routes to report."""
    from synapse.graph import route_verify
    state = AgentState(user_id="u1", session_id="s1", recovered=False)
    assert route_verify(state) == "failed"


@pytest.mark.asyncio
async def test_hypotheses_without_evidence_dropped():
    """The reducer must drop hypotheses with empty evidence."""
    from synapse.state import _hypotheses_reducer
    valid_h = Hypothesis(
        statement="WEB-02 exhausted",
        evidence=[Finding(source="cmdb", snippet="WEB-02 metrics", weight=0.8)],
        confidence=0.9,
    )
    invalid_h = Hypothesis(statement="Unknown", evidence=[], confidence=0.2)
    result = _hypotheses_reducer([], [valid_h, invalid_h])
    assert len(result) == 1
    assert result[0].statement == "WEB-02 exhausted"
