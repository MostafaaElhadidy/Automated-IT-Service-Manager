"""Phase 1 acceptance test — AgentState round-trip."""
from __future__ import annotations
import pytest
from synapse.state import AgentState, Message, Ticket, Finding, Hypothesis, Action


def test_agent_state_defaults():
    state = AgentState(user_id="u1", session_id="s1")
    assert state.schema_version == "1.0"
    assert state.conversation == []
    assert state.tickets == {}
    assert state.fastpath_score == 0.0
    assert state.recovered is None


def test_ticket_in_state():
    ticket = Ticket(id="TKT-001", category="incident", priority="P1", summary="DB down")
    state = AgentState(user_id="u1", session_id="s1")
    state.tickets["TKT-001"] = ticket
    assert state.tickets["TKT-001"].priority == "P1"


def test_hypothesis_requires_evidence():
    """Hypotheses without evidence must be dropped by the reducer."""
    from synapse.state import _hypotheses_reducer
    valid = Hypothesis(
        statement="WEB-02 exhausted",
        evidence=[Finding(source="cmdb", snippet="WEB-02 has 0 free workers", weight=0.9)],
        confidence=0.85,
        remediation_id="restart_web_service",
    )
    invalid = Hypothesis(statement="Unknown", evidence=[], confidence=0.1)
    result = _hypotheses_reducer([], [valid, invalid])
    assert len(result) == 1
    assert result[0].remediation_id == "restart_web_service"


def test_state_serialization():
    """AgentState must serialize/deserialize cleanly."""
    state = AgentState(
        user_id="u1",
        session_id="s1",
        conversation=[Message(role="user", content="Dashboard is down!")],
    )
    serialized = state.model_dump()
    restored = AgentState.model_validate(serialized)
    assert restored.conversation[0].content == "Dashboard is down!"


def test_action_status_transition():
    action = Action(runbook_id="restart_web_service", parameters={"host": "WEB-02"})
    assert action.status == "proposed"
    approved = action.model_copy(update={"status": "approved"})
    assert approved.status == "approved"
    assert action.status == "proposed"  # original unchanged
