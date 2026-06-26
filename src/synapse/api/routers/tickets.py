from __future__ import annotations
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from synapse.api.deps import get_db, get_graph, get_current_user, require_role
from synapse.api.schemas import TicketOut
from synapse.db import repositories as repo
from synapse.db.models import User
from synapse.state import Message, Ticket as StateTicket

router = APIRouter(prefix="/tickets", tags=["tickets"])


def _ticket_to_out(t) -> TicketOut:
    return TicketOut(
        id=t.id,
        category=t.category,
        priority=t.priority,
        status=t.status,
        summary=t.summary,
        affected_ci=t.affected_ci,
        created_at=t.created_at,
        resolved_at=t.resolved_at,
    )


@router.get("", response_model=list[TicketOut])
async def list_tickets(
    status: str | None = Query(None),
    priority: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[TicketOut]:
    """List tickets. End users see only their own; IT/admin see all."""
    owner_filter = user.id if user.role == "end_user" else None
    tickets = await repo.search_tickets(db, status=status, priority=priority, owner_id=owner_filter)
    return [_ticket_to_out(t) for t in tickets]


@router.get("/{ticket_id}", response_model=TicketOut)
async def get_ticket(
    ticket_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TicketOut:
    ticket = await repo.get_ticket(db, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} not found")
    # End users may only view their own tickets
    if user.role == "end_user" and ticket.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized to view this ticket")
    return _ticket_to_out(ticket)


@router.post("/{ticket_id}/investigate")
async def investigate_ticket(
    ticket_id: str,
    graph=Depends(get_graph),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_role("it_team", "admin")),
) -> dict:
    """Trigger RCA + remediation for a monitoring ticket from the dashboard.

    IT-only. Runs the full agent pipeline, then registers the proposed action in
    the pending-approvals store so it appears immediately in the dashboard.
    """
    ticket = await repo.get_ticket(db, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} not found")

    session_id = f"inv_{uuid.uuid4().hex[:8]}"

    state_ticket = StateTicket(
        id=ticket.id,
        status=ticket.status,
        category=ticket.category,
        priority=ticket.priority,
        affected_ci=ticket.affected_ci,
        summary=ticket.summary,
    )

    input_state = {
        "user_id": "monitoring_system",
        "session_id": session_id,
        "chat_history": [],
        "conversation": [
            Message(role="user", content=f"Investigate: {ticket.summary}")
        ],
        "tickets": {ticket_id: state_ticket},
        "active_ticket_id": ticket_id,
        "request_type": "incident",
        "fastpath_score": 0.0,
        "fastpath_answer": "",
        "pending_action": None,
        "hypotheses": [],
        "findings": [],
        "recovered": False,
        "escalated_to_human": False,
        "execution_summary": "",
    }

    config = {"configurable": {"thread_id": session_id}}

    try:
        result = await graph.ainvoke(input_state, config=config)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Investigation failed: {exc}")

    # Register proposed action in the dashboard pending-approvals store
    from synapse.api import pending_store

    if isinstance(result, dict):
        pending = result.get("pending_action")
        hyps = result.get("hypotheses", [])
    else:
        pending = getattr(result, "pending_action", None)
        hyps = getattr(result, "hypotheses", [])

    if not pending:
        return {"status": "no_action_proposed", "session_id": session_id}

    root_cause = "Root cause analysis pending"
    if hyps:
        last_hyp = hyps[-1]
        root_cause = (
            last_hyp.get("statement", root_cause)
            if isinstance(last_hyp, dict)
            else last_hyp.statement
        )

    runbook_id = pending.get("runbook_id", "") if isinstance(pending, dict) else pending.runbook_id
    plan       = pending.get("plan", "")        if isinstance(pending, dict) else pending.plan
    parameters = pending.get("parameters", {})  if isinstance(pending, dict) else pending.parameters

    pending_store.register(
        session_id=session_id,
        action_id=runbook_id,
        runbook_id=runbook_id,
        plan=plan,
        parameters=parameters,
        root_cause=root_cause,
        ticket_id=ticket_id,
        ticket_summary=ticket.summary,
        ticket_priority=ticket.priority,
    )

    return {"status": "pending_approval", "session_id": session_id, "runbook_id": runbook_id}
