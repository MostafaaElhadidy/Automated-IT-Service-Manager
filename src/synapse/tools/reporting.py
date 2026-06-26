"""Report generation utilities."""
from __future__ import annotations
from synapse.state import Hypothesis, Action


def build_report_body(
    ticket_id: str,
    ticket_summary: str,
    hypotheses: list[Hypothesis],
    pending_action: Action | None,
) -> str:
    hyp_section = "No hypothesis generated."
    if hypotheses:
        top = hypotheses[-1]
        ev_lines = "\n".join(
            f"  - [{f.source}] {f.snippet[:150]} (weight={f.weight:.2f})"
            for f in top.evidence
        )
        hyp_section = (
            f"Root cause: {top.statement}\n"
            f"Confidence: {top.confidence:.0%}\n"
            f"Evidence:\n{ev_lines}"
        )

    action_section = "No action attempted."
    if pending_action:
        action_section = (
            f"Runbook: {pending_action.runbook_id}\n"
            f"Parameters: {pending_action.parameters}\n"
            f"Status: {pending_action.status}"
        )

    return (
        f"INCIDENT REPORT\n"
        f"{'='*60}\n"
        f"Ticket: {ticket_id}\n"
        f"Summary: {ticket_summary}\n\n"
        f"ROOT CAUSE ANALYSIS\n{hyp_section}\n\n"
        f"ACTIONS TRIED\n{action_section}\n\n"
        f"Resolution: UNRESOLVED — escalated to IT team."
    )
