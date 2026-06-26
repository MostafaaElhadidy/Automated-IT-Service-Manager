"""Chat router — POST /sessions + POST /sessions/{id}/messages + GET /sessions/{id}/stream."""
from __future__ import annotations
import json
import logging
import uuid
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from synapse.api.deps import get_db, get_graph, get_current_user
from synapse.api.schemas import (
    ChatRequest,
    ChatResponse,
    PendingActionOut,
    SessionOut,
    TicketOut,
)
from synapse.api import pending_store, notification_store
from synapse.db.models import User
from synapse.state import AgentState, Message

router = APIRouter(prefix="/sessions", tags=["chat"])
logger = logging.getLogger(__name__)

# Per-session conversation history (role + content pairs).
# LangGraph state replaces conversation on each turn, so we accumulate it here
# in the API layer and pass the full history into the graph on every invoke.
_history: dict[str, list[Message]] = {}


def _extract_reply(result: AgentState | dict) -> str:
    """Pull the last assistant message from state."""
    if isinstance(result, dict):
        msgs = result.get("conversation", [])
    else:
        msgs = result.conversation if hasattr(result, "conversation") else []

    for msg in reversed(msgs):
        if isinstance(msg, dict):
            if msg.get("role") == "assistant":
                return msg.get("content", "")
        elif hasattr(msg, "role") and msg.role == "assistant":
            return msg.content
    return "Processing complete."


def _build_response(result: AgentState | dict, session_id: str) -> ChatResponse:
    """Map AgentState to ChatResponse — the API → state boundary."""
    if isinstance(result, dict):
        # LangGraph returns a dict of updates
        tickets_raw = result.get("tickets", {})
        pending = result.get("pending_action")
        escalated = result.get("escalated_to_human", False)
    else:
        tickets_raw = result.tickets
        pending = result.pending_action
        escalated = result.escalated_to_human

    reply = _extract_reply(result)

    tickets_out: list[TicketOut] = []
    for tid, t in (tickets_raw.items() if isinstance(tickets_raw, dict) else {}.items()):
        if isinstance(t, dict):
            tickets_out.append(TicketOut(**t))
        else:
            tickets_out.append(TicketOut(
                id=t.id,
                category=t.category,
                priority=t.priority,
                status=t.status,
                summary=t.summary,
                affected_ci=t.affected_ci,
            ))

    pending_out: PendingActionOut | None = None
    if pending:
        if isinstance(pending, dict):
            pending_out = PendingActionOut(
                action_id=pending.get("runbook_id", ""),
                runbook_id=pending.get("runbook_id", ""),
                plan=pending.get("plan", ""),
                parameters=pending.get("parameters", {}),
            )
        else:
            pending_out = PendingActionOut(
                action_id=pending.runbook_id,
                runbook_id=pending.runbook_id,
                plan=pending.plan,
                parameters=pending.parameters,
            )

    return ChatResponse(
        reply=reply,
        session_id=session_id,
        tickets=tickets_out,
        pending_action=pending_out,
        escalated=bool(escalated),
    )


@router.post("", response_model=SessionOut)
async def create_session(_user: User = Depends(get_current_user)) -> SessionOut:
    """Create a new chat session for the authenticated user."""
    sid = uuid.uuid4().hex
    return SessionOut(session_id=sid)


@router.post("/{sid}/messages", response_model=ChatResponse)
async def post_message(
    sid: str,
    body: ChatRequest,
    graph=Depends(get_graph),
    user: User = Depends(get_current_user),
    _db: AsyncSession = Depends(get_db),
) -> ChatResponse:
    """Send a user message; runs the graph and returns the response."""
    user_id = user.id  # authenticated user — becomes the ticket owner_id at intake
    config = {"configurable": {"thread_id": sid}}

    # Build full conversation: accumulated history + this new user message.
    # Per-turn incident fields are reset so stale state (e.g. old pending_action)
    # from a prior incident never bleeds into a new message.
    history = _history.get(sid, [])
    new_user_msg = Message(role="user", content=body.message)
    full_conversation = history + [new_user_msg]

    input_update = {
        "user_id": user_id,
        "session_id": sid,
        # chat_history = full context; agents never overwrite this field so it
        # survives intra-run state replacements and is available to routing_node.
        "chat_history": full_conversation,
        # conversation = current message only; agents append their replies here.
        "conversation": [new_user_msg],
        "pending_action": None,
        "hypotheses": [],
        "findings": [],
        "recovered": False,
        "escalated_to_human": False,
        "fastpath_score": 0.0,
        "fastpath_answer": "",
        "execution_summary": "",
    }

    try:
        result = await graph.ainvoke(input_update, config=config)
    except Exception as exc:
        logger.error("Graph invocation failed for session %s: %s", sid, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Graph error: {exc}")

    # Persist conversation: save user msg + agent reply so next turn sees history.
    reply_text = _extract_reply(result)
    _history[sid] = full_conversation + [Message(role="assistant", content=reply_text)]

    response = _build_response(result, sid)

    # Register in pending store so the dashboard can show the approval request
    # with root cause and ticket context that the Chainlit client doesn't expose.
    if response.pending_action:
        if isinstance(result, dict):
            hyps = result.get("hypotheses", [])
            active_tid = result.get("active_ticket_id")
            tickets_raw = result.get("tickets", {})
        else:
            hyps = getattr(result, "hypotheses", [])
            active_tid = getattr(result, "active_ticket_id", None)
            tickets_raw = getattr(result, "tickets", {})

        if hyps:
            last_hyp = hyps[-1]
            root_cause = last_hyp.get("statement", "") if isinstance(last_hyp, dict) else last_hyp.statement
        else:
            root_cause = "Root cause analysis pending"

        ticket_id = active_tid or ""
        ticket_summary = ""
        ticket_priority = "P3"
        if ticket_id and ticket_id in tickets_raw:
            t = tickets_raw[ticket_id]
            if isinstance(t, dict):
                ticket_summary = t.get("summary", "")
                ticket_priority = t.get("priority", "P3")
            else:
                ticket_summary = t.summary
                ticket_priority = t.priority
        elif response.tickets:
            t0 = response.tickets[0]
            ticket_id = ticket_id or t0.id
            ticket_summary = t0.summary
            ticket_priority = t0.priority

        pa = response.pending_action
        pending_store.register(
            session_id=sid,
            action_id=pa.action_id,
            runbook_id=pa.runbook_id,
            plan=pa.plan,
            parameters=pa.parameters,
            root_cause=root_cause,
            ticket_id=ticket_id,
            ticket_summary=ticket_summary,
            ticket_priority=ticket_priority,
        )

    return response


@router.get("/{sid}/notification")
async def get_notification(sid: str) -> dict:
    """Poll endpoint for Chainlit — returns and clears any pending notification."""
    return {"message": notification_store.pop_notification(sid)}


@router.get("/{sid}/stream")
async def stream_session(sid: str, graph=Depends(get_graph)) -> StreamingResponse:
    """SSE stream of agent steps."""
    async def event_stream() -> AsyncGenerator[str, None]:
        config = {"configurable": {"thread_id": sid}}
        try:
            async for event in graph.astream_events({}, config=config, version="v2"):
                data = json.dumps({"type": event.get("event"), "data": str(event.get("data", ""))[:200]})
                yield f"data: {data}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'data': str(exc)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
