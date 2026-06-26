"""API schemas — HTTP layer. Distinct from ORM models and AgentState."""
from __future__ import annotations
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, EmailStr, Field


class ChatRequest(BaseModel):
    message: str


# ── Auth ──────────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=6, max_length=128)
    role: Literal["end_user", "it_team", "admin"] = "end_user"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    is_active: bool


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class TicketOut(BaseModel):
    id: str
    category: str
    priority: str
    status: str
    summary: str
    affected_ci: str | None = None
    created_at: datetime | None = None
    resolved_at: datetime | None = None


class PendingActionOut(BaseModel):
    action_id: str       # runbook_id used as action id for approval endpoint
    runbook_id: str
    plan: str
    parameters: dict


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    tickets: list[TicketOut] = []
    pending_action: PendingActionOut | None = None
    escalated: bool = False


class SessionOut(BaseModel):
    session_id: str


class MetricsOut(BaseModel):
    open_tickets: int
    deflection_rate: float
    mttr_minutes: float
    escalated: int
    total_tickets: int


class CMDBQueryRequest(BaseModel):
    question: str


class CMDBQueryResponse(BaseModel):
    answer: str
    rows: list[dict[str, Any]] = []


class PendingApprovalOut(BaseModel):
    session_id: str
    action_id: str
    runbook_id: str
    plan: str
    parameters: dict
    root_cause: str
    ticket_id: str
    ticket_summary: str
    ticket_priority: str
    created_at: str


class ApprovalRequest(BaseModel):
    session_id: str


class HealthOut(BaseModel):
    status: str
    db: str = "unknown"
    chroma: str = "unknown"
