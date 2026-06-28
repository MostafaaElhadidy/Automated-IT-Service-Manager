"""In-process store for HITL pending approvals.

Keyed by session_id. Written by the chat router when a pending_action is
detected; cleared by the approvals router after approve/reject.
"""
from __future__ import annotations
from datetime import datetime, timezone

# session_id → approval snapshot dict
_pending: dict[str, dict] = {}


def register(
    session_id: str,
    action_id: str,
    runbook_id: str,
    plan: str,
    parameters: dict,
    root_cause: str,
    ticket_id: str,
    ticket_summary: str,
    ticket_priority: str,
    *,
    target_label: str = "local",
    target_nodeid: str | None = None,
    target_online: bool = False,
) -> None:
    _pending[session_id] = {
        "session_id": session_id,
        "action_id": action_id,
        "runbook_id": runbook_id,
        "plan": plan,
        "parameters": parameters,
        "root_cause": root_cause,
        "ticket_id": ticket_id,
        "ticket_summary": ticket_summary,
        "ticket_priority": ticket_priority,
        "created_at": datetime.now(timezone.utc).isoformat(),
        # Remote execution target (shown in dashboard approval card)
        "target_label": target_label,
        "target_nodeid": target_nodeid,
        "target_online": target_online,
    }


def clear(session_id: str) -> None:
    _pending.pop(session_id, None)


def all_pending() -> list[dict]:
    return list(_pending.values())
