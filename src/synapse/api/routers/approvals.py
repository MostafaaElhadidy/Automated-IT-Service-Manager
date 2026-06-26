"""HITL approval/rejection endpoints — resume the graph after interrupt()."""
from __future__ import annotations
import logging

from fastapi import APIRouter, Depends, HTTPException
from langgraph.types import Command

from synapse.api.deps import get_graph, require_role
from synapse.api.routers.chat import _build_response
from synapse.api.schemas import ApprovalRequest, ChatResponse, PendingApprovalOut
from synapse.api import pending_store, notification_store
from synapse.db.models import User

router = APIRouter(prefix="/actions", tags=["approvals"])
logger = logging.getLogger(__name__)


@router.get("/pending", response_model=list[PendingApprovalOut])
async def list_pending_approvals(
    _user: User = Depends(require_role("it_team", "admin")),
) -> list[PendingApprovalOut]:
    """Return all sessions currently waiting for HITL approval. IT-only."""
    return [PendingApprovalOut(**item) for item in pending_store.all_pending()]


@router.post("/{action_id}/approve", response_model=ChatResponse)
async def approve_action(
    action_id: str,  # noqa: ARG001
    body: ApprovalRequest,
    graph=Depends(get_graph),
    _user: User = Depends(require_role("it_team", "admin")),
) -> ChatResponse:
    """Approve a pending HITL action and resume the graph. IT-only."""
    sid = body.session_id
    config = {"configurable": {"thread_id": sid}}
    try:
        result = await graph.ainvoke(
            Command(resume={"approved": True}),
            config=config,
        )
    except Exception as exc:
        logger.error("Approval resume failed for session %s: %s", sid, exc)
        raise HTTPException(status_code=500, detail=f"Resume error: {exc}")

    pending_store.clear(sid)
    response = _build_response(result, sid)
    notification_store.set_notification(
        sid,
        f"**The IT team approved the action.**\n\n{response.reply}",
    )
    return response


@router.post("/{action_id}/reject", response_model=ChatResponse)
async def reject_action(
    action_id: str,  # noqa: ARG001
    body: ApprovalRequest,
    graph=Depends(get_graph),
    _user: User = Depends(require_role("it_team", "admin")),
) -> ChatResponse:
    """Reject a pending HITL action → escalate_human path. IT-only."""
    sid = body.session_id
    config = {"configurable": {"thread_id": sid}}
    try:
        result = await graph.ainvoke(
            Command(resume={"approved": False}),
            config=config,
        )
    except Exception as exc:
        logger.error("Rejection resume failed for session %s: %s", sid, exc)
        raise HTTPException(status_code=500, detail=f"Resume error: {exc}")

    pending_store.clear(sid)
    response = _build_response(result, sid)
    notification_store.set_notification(
        sid,
        "**The IT team rejected the proposed action.** Your ticket has been escalated to a human specialist who will contact you shortly.",
    )
    return response
