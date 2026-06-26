"""LangGraph wiring — matches GRAPH.md exactly.

Nodes, edges, routing functions, and HITL interrupt are all here.
The Supervisor IS this compiled graph + route_entry + drain_alerts.
"""
from __future__ import annotations
import logging
import os
from typing import Any

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from synapse.state import AgentState, ReqType
from synapse.config import settings

logger = logging.getLogger(__name__)

# ── Import node/agent functions ───────────────────────────────────────────────
from synapse.nodes.fast_path import fast_path_node
from synapse.nodes.deflect import deflect_node
from synapse.agents.intake import intake_node
from synapse.nodes.routing import routing_node
from synapse.agents.rca import rca_node
from synapse.agents.remediation import remediation_node
from synapse.nodes.hitl import hitl_node, escalate_human_node
from synapse.nodes.verify import verify_node
from synapse.nodes.close_ticket import close_ticket_node
from synapse.nodes.report import report_node
from synapse.nodes.notify_it import notify_it_node

# ── Negative feedback keywords for route_entry ────────────────────────────────
NEGATIVE_FEEDBACK = {
    "didn't help", "didn't work", "not resolved", "still broken", "still down",
    "لم تُحل", "لم ينجح", "not working", "doesn't work", "failed", "still not",
    "same issue", "problem persists", "not fixed",
}


# ── Routing functions (deterministic — no LLM) ───────────────────────────────

def route_entry(state: AgentState) -> str:
    """Conditional entry point: new message or deflect-followup."""
    last = state.conversation[-1].content.lower() if state.conversation else ""
    active = state.active_ticket_id
    if active and active in state.tickets:
        ticket = state.tickets[active]
        if ticket.status == "closed" and any(k in last for k in NEGATIVE_FEEDBACK):
            return "deflect_followup"
    return "new"


def route_fast_path(state: AgentState) -> str:
    """Route to deflect if score meets threshold, else intake."""
    return "deflect" if state.fastpath_score >= settings.fastpath_threshold else "intake"


def route_request_type(state: AgentState) -> str:
    """Route incident/problem to RCA; simple requests end here."""
    if state.request_type in ("incident", "problem"):
        return "incident"
    return "resolved"


def route_hitl(state: AgentState) -> str:
    """After interrupt() resume: approved or rejected."""
    if state.pending_action and state.pending_action.status == "approved":
        return "approved"
    return "rejected"


def route_verify(state: AgentState) -> str:
    """Runbook succeeded or failed."""
    return "succeeded" if state.recovered else "failed"


# ── State reducers (merge lists/dicts across nodes) ───────────────────────────

def _findings_reducer(a: list, b: list) -> list:
    return a + b


def _hypotheses_reducer(a: list, b: list) -> list:
    valid = [h for h in b if h.evidence]
    return a + valid


def _tickets_reducer(a: dict, b: dict) -> dict:
    merged = dict(a)
    merged.update(b)
    return merged


def _messages_reducer(a: list, b: list) -> list:
    return a + b


# ── Build graph ───────────────────────────────────────────────────────────────

def build_graph(checkpointer=None):
    """Compile and return the LangGraph StateGraph.

    Uses MemorySaver by default (dev/test). Pass a PostgresSaver for production.
    """
    from langgraph.graph.state import CompiledStateGraph

    # Use annotations for reducers via TypedDict-style approach
    # We use AgentState as-is (Pydantic model) with manual reducer wiring
    g = StateGraph(AgentState)

    # ── Register all nodes ────────────────────────────────────────────────────
    g.add_node("fast_path",       fast_path_node)
    g.add_node("deflect",         deflect_node)
    g.add_node("intake",          intake_node)
    g.add_node("routing",         routing_node)
    g.add_node("rca",             rca_node)
    g.add_node("remediation",     remediation_node)
    g.add_node("hitl",            hitl_node)
    g.add_node("runbook",         verify_node)          # executes + verifies
    g.add_node("close_ticket",    close_ticket_node)
    g.add_node("report",          report_node)
    g.add_node("notify_it",       notify_it_node)
    g.add_node("escalate_human",  escalate_human_node)

    # ── Edges (from GRAPH.md) ─────────────────────────────────────────────────
    g.set_conditional_entry_point(
        route_entry,
        {
            "deflect_followup": "intake",   # user said prior deflection didn't help
            "new":              "fast_path",
        },
    )

    g.add_conditional_edges(
        "fast_path",
        route_fast_path,
        {"deflect": "deflect", "intake": "intake"},
    )
    g.add_edge("deflect", END)

    g.add_edge("intake", "routing")
    g.add_conditional_edges(
        "routing",
        route_request_type,
        {"incident": "rca", "resolved": END},
    )

    g.add_edge("rca", "remediation")
    g.add_edge("remediation", "hitl")
    g.add_conditional_edges(
        "hitl",
        route_hitl,
        {"approved": "runbook", "rejected": "escalate_human"},
    )

    g.add_conditional_edges(
        "runbook",
        route_verify,
        {"succeeded": "close_ticket", "failed": "report"},
    )
    g.add_edge("close_ticket", END)
    g.add_edge("report", "notify_it")
    g.add_edge("notify_it", END)
    g.add_edge("escalate_human", END)

    # ── Compile ───────────────────────────────────────────────────────────────
    if checkpointer is None:
        checkpointer = MemorySaver()

    compiled = g.compile(checkpointer=checkpointer, interrupt_before=["hitl"])
    logger.info("LangGraph compiled successfully")
    return compiled


def build_postgres_graph():
    """Build graph with Postgres checkpointer (production)."""
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        import psycopg

        conn_str = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
        checkpointer = AsyncPostgresSaver.from_conn_string(conn_str)
        return build_graph(checkpointer=checkpointer)
    except Exception as exc:
        logger.warning("Postgres checkpointer unavailable, using MemorySaver: %s", exc)
        return build_graph()
