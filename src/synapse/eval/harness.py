"""Evaluation harness — runs the labeled dataset through the system and prints metrics.

Run: python -m synapse.eval.harness
"""
from __future__ import annotations
import asyncio
import json
import logging
import pathlib
import time
from dataclasses import dataclass, field
from typing import Any

from synapse.config import settings

logger = logging.getLogger(__name__)
DATASET = pathlib.Path(__file__).parent / "dataset.jsonl"


@dataclass
class EvalResult:
    case_id: str
    input_text: str
    priority_match: bool = False
    category_match: bool = False
    root_cause_match: bool = False
    remediation_match: bool = False
    latency_s: float = 0.0
    error: str | None = None
    details: dict = field(default_factory=dict)


def _load_dataset() -> list[dict]:
    cases = []
    with open(DATASET) as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


async def _run_case(case: dict, graph: Any) -> EvalResult:
    result = EvalResult(case_id=case["id"], input_text=case["input"])
    t0 = time.time()

    try:
        import uuid
        session_id = f"eval_{uuid.uuid4().hex[:8]}"
        from synapse.state import Message

        input_state = {
            "user_id": "eval_harness",
            "session_id": session_id,
            "conversation": [Message(role="user", content=case["input"])],
        }
        config = {"configurable": {"thread_id": session_id}}

        output = await graph.ainvoke(input_state, config=config)
        result.latency_s = time.time() - t0

        # Extract ticket from output
        tickets = output.get("tickets", {}) if isinstance(output, dict) else output.tickets
        active_id = output.get("active_ticket_id") if isinstance(output, dict) else output.active_ticket_id

        ticket = tickets.get(active_id) if tickets and active_id else None

        if ticket:
            actual_priority = ticket.priority if hasattr(ticket, "priority") else ticket.get("priority")
            actual_category = ticket.category if hasattr(ticket, "category") else ticket.get("category")

            result.priority_match = actual_priority == case["expected_priority"]
            result.category_match = actual_category == case["expected_category"]

            result.details["ticket_id"] = active_id
            result.details["actual_priority"] = actual_priority
            result.details["actual_category"] = actual_category

        # Check hypotheses for root cause
        hyps = output.get("hypotheses", []) if isinstance(output, dict) else getattr(output, "hypotheses", [])
        expected_terms = case.get("expected_root_cause_contains", [])
        if expected_terms and hyps:
            top_hyp = hyps[-1]
            stmt = top_hyp.statement if hasattr(top_hyp, "statement") else top_hyp.get("statement", "")
            result.root_cause_match = any(t.lower() in stmt.lower() for t in expected_terms)
            result.details["rca_statement"] = stmt

        # Check remediation
        expected_rem = case.get("expected_remediation")
        pending = output.get("pending_action") if isinstance(output, dict) else getattr(output, "pending_action", None)
        if expected_rem and pending:
            actual_rb = pending.runbook_id if hasattr(pending, "runbook_id") else pending.get("runbook_id", "")
            result.remediation_match = actual_rb == expected_rem
            result.details["actual_runbook"] = actual_rb
        elif expected_rem is None:
            result.remediation_match = True  # no runbook expected

    except Exception as exc:
        result.latency_s = time.time() - t0
        result.error = str(exc)
        logger.error("Eval case %s failed: %s", case["id"], exc, exc_info=True)

    return result


async def run_eval() -> None:
    from synapse.graph import build_graph

    graph = build_graph()
    cases = _load_dataset()

    print(f"\n{'='*70}")
    print(f"SynapseITSM Evaluation Harness — {len(cases)} cases")
    print(f"{'='*70}\n")

    results: list[EvalResult] = []
    for case in cases:
        print(f"Running {case['id']}: {case['input'][:60]}...")
        r = await _run_case(case, graph)
        results.append(r)
        status = "✓" if (r.priority_match and r.category_match) else "✗"
        print(f"  {status} priority={r.priority_match} category={r.category_match} "
              f"rca={r.root_cause_match} rem={r.remediation_match} "
              f"latency={r.latency_s:.1f}s"
              + (f" ERROR: {r.error}" if r.error else ""))

    # ── Aggregate metrics ────────────────────────────────────────────────────
    n = len(results)
    priority_acc = sum(r.priority_match for r in results) / n
    category_acc = sum(r.category_match for r in results) / n
    rca_acc_cases = [r for r in results if r.details.get("rca_statement")]
    rca_acc = sum(r.root_cause_match for r in rca_acc_cases) / len(rca_acc_cases) if rca_acc_cases else 0.0
    rem_cases = [r for r in results if not r.error]
    rem_acc = sum(r.remediation_match for r in rem_cases) / len(rem_cases) if rem_cases else 0.0
    avg_latency = sum(r.latency_s for r in results) / n
    errors = sum(1 for r in results if r.error)

    print(f"\n{'='*70}")
    print(f"RESULTS ({n} cases)")
    print(f"{'='*70}")
    print(f"  Priority accuracy : {priority_acc:.1%}")
    print(f"  Category accuracy : {category_acc:.1%}")
    print(f"  RCA top-1 accuracy: {rca_acc:.1%}  (over {len(rca_acc_cases)} cases with hypotheses)")
    print(f"  Remediation match : {rem_acc:.1%}")
    print(f"  Avg latency       : {avg_latency:.1f}s")
    print(f"  Errors            : {errors}/{n}")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    asyncio.run(run_eval())
