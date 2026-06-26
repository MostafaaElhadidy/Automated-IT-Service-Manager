"""AgentState — the runtime contract passed between all graph nodes.

Three separate layers:
  - This file (Pydantic runtime state)
  - db/models.py (SQLAlchemy ORM)
  - api/schemas.py (HTTP API shapes)
Never store ORM objects here; never return AgentState from the API directly.
"""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field

Source = Literal["rag", "cmdb", "monitoring", "seqthinking", "web", "user"]
TicketCat = Literal["incident", "request", "problem", "change", "deflected"]
Priority = Literal["P1", "P2", "P3", "P4", "P5"]
TicketStat = Literal["new", "assigned", "in_progress", "resolved", "closed", "escalated"]
ActionStat = Literal["proposed", "approved", "executed", "failed", "rejected"]
Role = Literal["user", "assistant", "system"]
ReqType = Literal["incident", "problem", "request"]


class Message(BaseModel):
    role: Role
    content: str


class Finding(BaseModel):
    source: Source
    snippet: str
    weight: float = Field(ge=0.0, le=1.0)


class Hypothesis(BaseModel):
    statement: str
    evidence: list[Finding]  # must be non-empty
    confidence: float = Field(ge=0.0, le=1.0)
    remediation_id: str | None = None


class Action(BaseModel):
    runbook_id: str
    parameters: dict
    status: ActionStat = "proposed"
    plan: str = ""  # human-readable plan from get_plan


class Ticket(BaseModel):
    id: str
    status: TicketStat = "new"
    category: TicketCat
    priority: Priority
    affected_ci: str | None = None
    summary: str


class AgentState(BaseModel):
    schema_version: str = "1.0"
    user_id: str
    session_id: str
    # Full multi-turn history (user + assistant).  Set once per turn by the API
    # layer; NEVER written to by any agent/node so it survives intra-run state
    # replacements.  Used by routing_node for LLM context.
    chat_history: list[Message] = []
    conversation: list[Message] = []
    tickets: dict[str, Ticket] = {}
    active_ticket_id: str | None = None
    findings: list[Finding] = []
    hypotheses: list[Hypothesis] = []
    pending_action: Action | None = None
    escalated_to_human: bool = False
    # ── Scalar flags read/written by decision nodes ──────────────────────────
    fastpath_score: float = 0.0
    fastpath_answer: str = ""       # the KB answer returned by fast_path
    request_type: ReqType | None = None
    recovered: bool | None = None
    execution_summary: str = ""     # step-by-step log from verify_node, shown in close_ticket


# ── LangGraph reducer helpers ─────────────────────────────────────────────────
def _append_findings(existing: list[Finding], new: list[Finding]) -> list[Finding]:
    return existing + new


def _append_hypotheses(existing: list[Hypothesis], new: list[Hypothesis]) -> list[Hypothesis]:
    valid = [h for h in new if h.evidence]
    return existing + valid


# Aliases used by graph.py reducers and tests
_findings_reducer = _append_findings
_hypotheses_reducer = _append_hypotheses


def _merge_tickets(existing: dict[str, Ticket], new: dict[str, Ticket]) -> dict[str, Ticket]:
    merged = dict(existing)
    merged.update(new)
    return merged


# Alias
_tickets_reducer = _merge_tickets


def _append_messages(existing: list[Message], new: list[Message]) -> list[Message]:
    return existing + new
