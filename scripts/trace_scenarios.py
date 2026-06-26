"""
SynapseITSM -- Full Scenario Trace
==================================
Patches every internal function with logging decorators and runs 5 scenarios:

  1. Deflection       -- known FAQ -> fast-path Chroma hit -> deflect (no LLM)
  2. Full incident    -- WEB-02 502 -> intake LLM -> RCA LLM+CMDB+RAG -> remediation LLM -> HITL approve -> verify -> close
  3. HITL rejection   -- incident -> remediation proposed -> operator rejects -> escalate
  4. Monitoring alert -- direct call to _handle_alert() -> auto-ticket -> graph runs RCA
  5. CMDB query       -- /cmdb/query endpoint for dependency graph lookup

Usage (from synapseitsm/ dir):
    uv run python scripts/trace_scenarios.py
"""
from __future__ import annotations
import asyncio
import functools
import json
import logging
import os
import sys
import textwrap
import time
from typing import Any

# -- path bootstrap ------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# Force SQLite for speed (avoids needing PG for the direct-graph tests)
# Comment this out if you want to test against the real Postgres DB.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://synapse:synapse@localhost:5432/synapse")

# -- colour output -------------------------------------------------------------
RESET  = "\033[0m";  BOLD = "\033[1m"
CYAN   = "\033[96m"; GREEN = "\033[92m"; YELLOW = "\033[93m"
RED    = "\033[91m"; MAGENTA = "\033[95m"; BLUE = "\033[94m"
DIM    = "\033[2m"

def hdr(title: str, colour: str = CYAN) -> None:
    bar = "=" * 70
    print(f"\n{colour}{BOLD}{bar}")
    print(f"  {title}")
    print(f"{bar}{RESET}\n")

def step(label: str, colour: str = GREEN) -> None:
    print(f"{colour}{BOLD}>> {label}{RESET}")

def info(msg: str) -> None:
    print(f"  {DIM}{msg}{RESET}")

def ok(msg: str) -> None:
    print(f"  {GREEN}[OK] {msg}{RESET}")

def warn(msg: str) -> None:
    print(f"  {YELLOW}[!] {msg}{RESET}")

def show_json(label: str, data: Any) -> None:
    print(f"  {MAGENTA}{label}:{RESET}")
    dumped = json.dumps(data, indent=4, default=str)
    for line in dumped.splitlines():
        print(f"    {DIM}{line}{RESET}")

# -- call-trace decorator ------------------------------------------------------
_CALL_LOG: list[dict] = []

def traced(label: str, show_args: bool = True, show_result: bool = True, truncate: int = 400):
    """Wrap an async function to print entry/exit and log to _CALL_LOG."""
    def decorator(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            t0 = time.perf_counter()
            entry = {"fn": label, "args_repr": "", "result_repr": "", "elapsed_ms": 0, "error": None}
            if show_args:
                try:
                    # Skip large binary args
                    safe = {k: v for k, v in kwargs.items() if not isinstance(v, bytes)}
                    pos = [repr(a)[:200] for a in args]
                    entry["args_repr"] = f"args={pos} kwargs={safe}"
                except Exception:
                    pass
            print(f"\n  {BLUE}[CALL]  {BOLD}{label}{RESET}")
            if show_args and entry["args_repr"]:
                short = entry["args_repr"][:truncate]
                for ln in short.splitlines():
                    print(f"  {BLUE}|  {DIM}{ln}{RESET}")
            try:
                result = await fn(*args, **kwargs)
                elapsed = (time.perf_counter() - t0) * 1000
                entry["elapsed_ms"] = round(elapsed, 1)
                if show_result and result is not None:
                    r_repr = repr(result)[:truncate]
                    entry["result_repr"] = r_repr
                    print(f"  {BLUE}|  {GREEN}-> {r_repr}{RESET}")
                print(f"  {BLUE}[DONE]  {BOLD}{label}{RESET} {DIM}({elapsed:.0f}ms){RESET}")
                _CALL_LOG.append(entry)
                return result
            except Exception as exc:
                elapsed = (time.perf_counter() - t0) * 1000
                entry["elapsed_ms"] = round(elapsed, 1)
                entry["error"] = str(exc)
                print(f"  {BLUE}[ERR]   {BOLD}{label}{RESET} {RED}{exc}{RESET}")
                _CALL_LOG.append(entry)
                raise
        return wrapper
    return decorator

# -- patch internal functions before importing the modules ---------------------
import synapse.llm as _llm_mod
import synapse.rag.retriever as _rag_mod
import synapse.tools.cmdb_query as _cmdb_mod

_orig_call_llm = _llm_mod.call_llm
_orig_retrieve  = _rag_mod.retrieve_similar
_orig_cmdb      = _cmdb_mod.get_ci_dependencies_text

async def _traced_call_llm(agent: str, messages: list, **kwargs):
    """Show exactly what model + prompt is sent to Groq/Ollama."""
    from synapse.config import settings
    kw = settings.litellm_kwargs(agent)
    model = kw.get("model", "?")
    last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    print(f"\n  {YELLOW}[LLM]  agent={BOLD}{agent}{RESET}{YELLOW}  model={BOLD}{model}{RESET}")
    print(f"  {YELLOW}|  prompt (last user turn, first 300 chars):{RESET}")
    for ln in textwrap.wrap(last_user[:300], 90):
        print(f"  {YELLOW}|    {DIM}{ln}{RESET}")
    t0 = time.perf_counter()
    result = await _orig_call_llm(agent, messages, **kwargs)
    elapsed = (time.perf_counter() - t0) * 1000
    r_repr = repr(result)[:500]
    print(f"  {YELLOW}|  response -> {GREEN}{r_repr}{RESET}")
    print(f"  {YELLOW}[LLM DONE]  {DIM}({elapsed:.0f}ms){RESET}")
    _CALL_LOG.append({"fn": f"call_llm({agent})", "model": model, "elapsed_ms": round(elapsed, 1)})
    return result

async def _traced_retrieve(query: str, n_results: int = 3):
    print(f"\n  {MAGENTA}[RAG]  retrieve_similar  n={n_results}")
    print(f"  {MAGENTA}|  query: {DIM}{query[:200]}{RESET}")
    t0 = time.perf_counter()
    result = await _orig_retrieve(query, n_results=n_results)
    elapsed = (time.perf_counter() - t0) * 1000
    print(f"  {MAGENTA}|  hits: {len(result)}  scores: {[round(r.get('score',0),3) for r in result]}{RESET}")
    print(f"  {MAGENTA}[RAG DONE] {DIM}({elapsed:.0f}ms){RESET}")
    _CALL_LOG.append({"fn": "retrieve_similar", "hits": len(result), "elapsed_ms": round(elapsed, 1)})
    return result

async def _traced_cmdb(ci_id: str):
    print(f"\n  {CYAN}[CMDB]  get_ci_dependencies_text  ci={BOLD}{ci_id}{RESET}")
    t0 = time.perf_counter()
    result = await _orig_cmdb(ci_id)
    elapsed = (time.perf_counter() - t0) * 1000
    print(f"  {CYAN}|  result: {DIM}{str(result)[:300]}{RESET}")
    print(f"  {CYAN}[CMDB DONE] {DIM}({elapsed:.0f}ms){RESET}")
    _CALL_LOG.append({"fn": f"get_ci_dependencies_text({ci_id})", "elapsed_ms": round(elapsed, 1)})
    return result

_llm_mod.call_llm  = _traced_call_llm
_rag_mod.retrieve_similar = _traced_retrieve
_cmdb_mod.get_ci_dependencies_text = _traced_cmdb

# Patch in submodules that already imported at module load
import synapse.agents.intake as _intake_mod
import synapse.agents.rca as _rca_mod
import synapse.agents.remediation as _rem_mod
import synapse.nodes.fast_path as _fp_mod
_intake_mod.call_llm = _traced_call_llm
_rca_mod.call_llm    = _traced_call_llm
_rca_mod.retrieve_similar = _traced_retrieve
_rca_mod.get_ci_dependencies_text = _traced_cmdb
_rem_mod.call_llm    = _traced_call_llm
_fp_mod.retrieve_similar = _traced_retrieve

# -- patch runbook client ------------------------------------------------------
try:
    import synapse.mcp_servers.runbook_client as _rb_mod
    _orig_list_rb   = _rb_mod.list_runbooks_from_mcp
    _orig_get_plan  = _rb_mod.get_plan_from_mcp
    _orig_exec_ver  = _rb_mod.execute_and_verify

    @traced("runbook_client.list_runbooks_from_mcp", show_args=False)
    async def _t_list_rb(): return await _orig_list_rb()

    @traced("runbook_client.get_plan_from_mcp")
    async def _t_get_plan(**kw): return await _orig_get_plan(**kw)

    @traced("runbook_client.execute_and_verify")
    async def _t_exec_ver(**kw): return await _orig_exec_ver(**kw)

    _rb_mod.list_runbooks_from_mcp = _t_list_rb
    _rb_mod.get_plan_from_mcp      = _t_get_plan
    _rb_mod.execute_and_verify     = _t_exec_ver
    _rem_mod.list_runbooks_from_mcp = _t_list_rb
    _rem_mod.get_plan_from_mcp      = _t_get_plan
except ImportError:
    warn("runbook_client not importable -- MCP calls won't be traced")

# -- node entry/exit wrapper for LangGraph ------------------------------------
# Import the modules (this also imports graph.py which captures fn references)
import synapse.graph as _graph_mod
import synapse.agents.intake    as _ia
import synapse.agents.rca       as _ra
import synapse.agents.remediation as _rema
import synapse.nodes.fast_path  as _fpn
import synapse.nodes.deflect    as _defn
import synapse.nodes.hitl       as _hitn
import synapse.nodes.verify     as _vern
import synapse.nodes.close_ticket as _cln
import synapse.nodes.routing    as _routn
import synapse.nodes.report     as _repn
import synapse.nodes.notify_it  as _notin

# Map: graph-node-name -> (owning_module, fn_name, graph_module_attr_name)
_NODE_FUNS = {
    "fast_path":      (_fpn,   "fast_path_node",       "fast_path_node"),
    "deflect":        (_defn,  "deflect_node",          "deflect_node"),
    "intake":         (_ia,    "intake_node",           "intake_node"),
    "routing":        (_routn, "routing_node",          "routing_node"),
    "rca":            (_ra,    "rca_node",              "rca_node"),
    "remediation":    (_rema,  "remediation_node",      "remediation_node"),
    "hitl":           (_hitn,  "hitl_node",             "hitl_node"),
    "escalate_human": (_hitn,  "escalate_human_node",   "escalate_human_node"),
    "verify":         (_vern,  "verify_node",           "verify_node"),
    "close_ticket":   (_cln,   "close_ticket_node",     "close_ticket_node"),
    "report":         (_repn,  "report_node",           "report_node"),
    "notify_it":      (_notin, "notify_it_node",        "notify_it_node"),
}

def _wrap_node(mod, fn_name: str, graph_attr: str, label: str):
    orig = getattr(mod, fn_name)
    @functools.wraps(orig)
    async def _wrapper(state):
        print(f"\n{GREEN}{BOLD}  [NODE ENTER] {label}{RESET}")
        t0 = time.perf_counter()
        result = await orig(state)
        elapsed = (time.perf_counter() - t0) * 1000
        print(f"{GREEN}  [NODE EXIT]  {label}  ({elapsed:.0f}ms){RESET}")
        if result:
            keys = list(result.keys())
            print(f"  {DIM}  state updates: {keys}{RESET}")
        return result
    # Patch in the owning module AND in graph.py's namespace
    setattr(mod, fn_name, _wrapper)
    setattr(_graph_mod, graph_attr, _wrapper)
    return _wrapper

for label, (mod, fn, graph_attr) in _NODE_FUNS.items():
    _wrap_node(mod, fn, graph_attr, label)

# -- build the graph AFTER all patches so build_graph() picks up wrappers -----
from synapse.graph import build_graph
from langgraph.types import Command
from synapse.state import AgentState, Message

# Suppress noisy library loggers
logging.basicConfig(level=logging.WARNING)
for noisy in ("httpx", "httpcore", "openai", "litellm", "chromadb"):
    logging.getLogger(noisy).setLevel(logging.ERROR)
# Keep synapse loggers
for synapse_log in ("synapse.agents", "synapse.nodes", "synapse.mcp_servers"):
    logging.getLogger(synapse_log).setLevel(logging.INFO)

graph = build_graph()

# -- helpers -------------------------------------------------------------------
def _last_reply(result: dict | AgentState) -> str:
    convs = result.get("conversation", []) if isinstance(result, dict) else result.conversation
    for m in reversed(convs):
        role = m.get("role") if isinstance(m, dict) else m.role
        if role == "assistant":
            return (m.get("content") if isinstance(m, dict) else m.content) or ""
    return "(no reply)"

def _show_call_summary():
    if not _CALL_LOG:
        return
    print(f"\n  {DIM}{'-'*60}")
    print(f"  {DIM}CALL SUMMARY ({len(_CALL_LOG)} traced calls):{RESET}")
    for entry in _CALL_LOG:
        err = f" {RED}ERROR: {entry['error']}{RESET}" if entry.get("error") else ""
        print(f"  {DIM}  - {entry['fn']:<45} {entry['elapsed_ms']:>7.1f}ms{err}{RESET}")
    _CALL_LOG.clear()

# -----------------------------------------------------------------------------
# SCENARIO 1 -- Deflection (fast-path Chroma hit -> no LLM, no ticket escalation)
# -----------------------------------------------------------------------------
async def scenario_deflect():
    hdr("SCENARIO 1 -- DEFLECTION (fast-path -> known KB answer)", BLUE)
    info("Message: 'How do I reset my password?'")
    info("Expected: fast_path_node -> RAG lookup -> if score >= 0.82 -> deflect_node")
    info("No intake LLM call should happen.\n")

    sid = "trace_deflect_01"
    config = {"configurable": {"thread_id": sid}}

    step("Invoking graph...")
    result = await graph.ainvoke(
        {
            "user_id": "tester",
            "session_id": sid,
            "conversation": [Message(role="user", content="How do I reset my VPN password?")],
        },
        config=config,
    )

    reply = _last_reply(result)
    tix   = result.get("tickets", {}) if isinstance(result, dict) else result.tickets

    print(f"\n  {BOLD}Final reply:{RESET}")
    for ln in reply.splitlines():
        print(f"    {ln}")

    ticket_statuses = {tid: t.status if hasattr(t, "status") else t.get("status") for tid, t in tix.items()}
    ok(f"Tickets created: {ticket_statuses or 'none'}")
    score = result.get("fastpath_score", 0) if isinstance(result, dict) else getattr(result, "fastpath_score", 0)
    info(f"Fastpath score: {score:.3f}  (threshold: 0.82)")

    _show_call_summary()


# -----------------------------------------------------------------------------
# SCENARIO 2 -- Full incident: intake -> RCA -> remediation -> HITL approve -> verify -> close
# -----------------------------------------------------------------------------
async def scenario_full_incident():
    hdr("SCENARIO 2 -- FULL INCIDENT WORKFLOW (WEB-02 502 error)", GREEN)
    info("Message: WEB-02 returning 502 errors")
    info("Expected path: route_entry->fast_path->intake(LLM)->routing->rca(LLM+CMDB+RAG)->remediation(LLM)->hitl(PAUSE)")
    info("Then: POST /actions/approve -> hitl resumes -> verify(MCP exec) -> close_ticket\n")

    sid = "trace_incident_02"
    config = {"configurable": {"thread_id": sid}}

    step("Phase 1 -- send incident message (graph will pause at hitl)...")
    result = await graph.ainvoke(
        {
            "user_id": "tester",
            "session_id": sid,
            "conversation": [
                Message(
                    role="user",
                    content=(
                        "CRITICAL: WEB-02 is returning HTTP 502 Bad Gateway errors. "
                        "Users cannot access the customer portal. Started 10 minutes ago."
                    ),
                )
            ],
        },
        config=config,
    )

    reply = _last_reply(result)
    tix   = result.get("tickets", {}) if isinstance(result, dict) else result.tickets
    pa    = result.get("pending_action") if isinstance(result, dict) else getattr(result, "pending_action", None)

    print(f"\n  {BOLD}Agent reply after Phase 1:{RESET}")
    for ln in reply.splitlines():
        print(f"    {ln}")

    if tix:
        for tid, t in tix.items():
            prio = t.priority if hasattr(t, "priority") else t.get("priority")
            stat = t.status if hasattr(t, "status") else t.get("status")
            ci   = (t.affected_ci if hasattr(t, "affected_ci") else t.get("affected_ci")) or "n/a"
            ok(f"Ticket {tid}  priority={prio}  status={stat}  ci={ci}")

    if pa:
        rb_id = pa.runbook_id if hasattr(pa, "runbook_id") else pa.get("runbook_id")
        ok(f"Pending action: runbook={rb_id}  (graph paused at HITL)")
    else:
        warn("No pending_action -- check if HITL was reached")

    _show_call_summary()

    # -- Phase 2: approve ------------------------------------------------------
    if pa:
        step("\nPhase 2 -- operator APPROVES the runbook...")
        result2 = await graph.ainvoke(
            Command(resume={"approved": True}),
            config=config,
        )

        reply2 = _last_reply(result2)
        tix2   = result2.get("tickets", {}) if isinstance(result2, dict) else result2.tickets
        rec    = result2.get("recovered") if isinstance(result2, dict) else getattr(result2, "recovered", None)

        print(f"\n  {BOLD}Agent reply after approval:{RESET}")
        for ln in reply2.splitlines():
            print(f"    {ln}")

        for tid, t in tix2.items():
            stat = t.status if hasattr(t, "status") else t.get("status")
            ok(f"Ticket {tid} -> status={stat}")

        ok(f"Recovered={rec}")
        _show_call_summary()
    else:
        warn("Skipping Phase 2 (no pending action to approve)")


# -----------------------------------------------------------------------------
# SCENARIO 3 -- HITL rejection -> escalate_human
# -----------------------------------------------------------------------------
async def scenario_hitl_reject():
    hdr("SCENARIO 3 -- HITL REJECTION -> ESCALATE TO HUMAN", RED)
    info("Message: DB-01 connections exhausted")
    info("Expected: full pipeline -> HITL pause -> operator REJECTS -> escalate_human_node\n")

    sid = "trace_reject_03"
    config = {"configurable": {"thread_id": sid}}

    step("Phase 1 -- incident message...")
    result = await graph.ainvoke(
        {
            "user_id": "tester",
            "session_id": sid,
            "conversation": [
                Message(
                    role="user",
                    content=(
                        "DB-01 is reporting too many connections -- "
                        "error: FATAL: remaining connection slots are reserved. "
                        "All applications are throwing database errors."
                    ),
                )
            ],
        },
        config=config,
    )

    pa = result.get("pending_action") if isinstance(result, dict) else getattr(result, "pending_action", None)
    reply = _last_reply(result)
    print(f"\n  {BOLD}Agent reply:{RESET}")
    for ln in reply.splitlines():
        print(f"    {ln}")

    _show_call_summary()

    step("\nPhase 2 -- operator REJECTS the runbook...")
    result2 = await graph.ainvoke(
        Command(resume={"approved": False}),
        config=config,
    )

    reply2 = _last_reply(result2)
    esc    = result2.get("escalated_to_human") if isinstance(result2, dict) else getattr(result2, "escalated_to_human", False)
    tix2   = result2.get("tickets", {}) if isinstance(result2, dict) else result2.tickets

    print(f"\n  {BOLD}Agent reply after rejection:{RESET}")
    for ln in reply2.splitlines():
        print(f"    {ln}")

    ok(f"escalated_to_human={esc}")
    for tid, t in tix2.items():
        stat = t.status if hasattr(t, "status") else t.get("status")
        ok(f"Ticket {tid} -> status={stat}")

    _show_call_summary()


# -----------------------------------------------------------------------------
# SCENARIO 4 -- Monitoring auto-alert (direct call to _handle_alert)
# -----------------------------------------------------------------------------
async def scenario_monitoring():
    hdr("SCENARIO 4 -- MONITORING AUTO-ALERT (anomaly detection -> auto-ticket -> graph)", MAGENTA)
    info("Simulates anomaly detector firing an alert for WEB-02 error_rate=0.72")
    info("Expected: _handle_alert -> create ticket -> graph.ainvoke (intake skipped, goes straight to rca)\n")

    from synapse.sim.generator import AnomalyEvent
    from synapse.agents.monitoring import _handle_alert

    event = AnomalyEvent(
        ci_id="WEB-02",
        metric="error_rate",
        value=0.72,
        description="HTTP error rate spike detected on WEB-02",
        timestamp=time.time(),
    )

    step(f"Firing alert: ci={event.ci_id}  metric={event.metric}  value={event.value}")
    await _handle_alert(event, graph)

    ok("Monitoring alert handled -- auto-ticket created and graph invoked")
    _show_call_summary()


# -----------------------------------------------------------------------------
# SCENARIO 5 -- CMDB dependency query via API
# -----------------------------------------------------------------------------
async def scenario_cmdb_query():
    hdr("SCENARIO 5 -- CMDB DEPENDENCY QUERY (/cmdb/query)", CYAN)
    info("Calls the CMDB natural-language query endpoint to show dependency traversal\n")

    import httpx
    questions = [
        "What does WEB-02 depend on?",
        "Which CIs depend on DB-01?",
        "List all P1 critical infrastructure components",
    ]

    try:
        async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=20) as c:
            for q in questions:
                step(f"Question: {q}")
                r = await c.post("/cmdb/query", json={"question": q})
                if r.status_code == 200:
                    data = r.json()
                    ok(f"Answer: {data.get('answer', '')[:300]}")
                    if data.get("rows"):
                        info(f"Rows returned: {len(data['rows'])}")
                        for row in data["rows"][:3]:
                            info(f"  {row}")
                else:
                    warn(f"HTTP {r.status_code}: {r.text[:200]}")
                print()
    except Exception as exc:
        warn(f"Backend not reachable: {exc}")
        info("Start the backend first with: uv run uvicorn synapse.api.main:app --port 8000")

        # Fall back to direct function call
        step("Direct CMDB lookup for WEB-02 (bypassing HTTP):")
        result = await _orig_cmdb("WEB-02")
        ok(f"WEB-02 dependencies:\n{result}")


# -----------------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------------
async def main():
    hdr("SynapseITSM -- Full Scenario Trace Runner", CYAN)
    print(f"  {DIM}All internal functions are patched with call-trace wrappers.")
    print(f"  Every LLM call shows the actual model + truncated prompt + response.")
    print(f"  Every node entry/exit is printed with elapsed time.{RESET}\n")

    try:
        await scenario_deflect()
    except Exception as exc:
        warn(f"Scenario 1 failed: {exc}")
        import traceback; traceback.print_exc()

    try:
        await scenario_full_incident()
    except Exception as exc:
        warn(f"Scenario 2 failed: {exc}")
        import traceback; traceback.print_exc()

    try:
        await scenario_hitl_reject()
    except Exception as exc:
        warn(f"Scenario 3 failed: {exc}")
        import traceback; traceback.print_exc()

    try:
        await scenario_monitoring()
    except Exception as exc:
        warn(f"Scenario 4 failed: {exc}")
        import traceback; traceback.print_exc()

    try:
        await scenario_cmdb_query()
    except Exception as exc:
        warn(f"Scenario 5 failed: {exc}")
        import traceback; traceback.print_exc()

    hdr("ALL SCENARIOS COMPLETE", GREEN)


if __name__ == "__main__":
    asyncio.run(main())
