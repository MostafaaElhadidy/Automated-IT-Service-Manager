"""Remediation agent — match runbook to hypothesis → set pending_action (status=proposed).

The hitl node will interrupt(); after approval, verify_node runs the runbook via Runbook MCP.
"""
from __future__ import annotations
import logging
from pydantic import BaseModel, Field

from synapse.llm import call_llm
from synapse.state import AgentState, Action, Message

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an IT remediation specialist.
Given the original incident report and root-cause hypothesis, select the BEST-MATCHING runbook.

Domain matching rules (follow strictly):
- Internet slow / sluggish / high latency / speed issues / "my internet is slow"    → reset_network_adapter
- No internet / completely offline / can't reach websites / packet loss              → diagnose_internet
- DNS / name resolution / "can't resolve" / nslookup fails                          → flush_dns
- VPN / tunnel / remote access / VPN timeout / VPN dropped                          → reconnect_vpn
- Wi-Fi adapter disconnecting / adapter malfunction / adapter not found              → reset_network_adapter
- Full network failure / winsock corruption / TCP stack corrupt                      → reset_network_stack
- Database connections / connection pool / too many DB connections                   → restart_db_connection_pool
- Web service HTTP errors / 502 / 503 / web down                                    → restart_web_service
- Application crash / memory leak / app down                                         → restart_app_service
- Cache / Redis issues                                                               → clear_cache
- Worker count / scaling                                                             → scale_workers

IMPORTANT: "slow" internet/network always means reset_network_adapter (adapter reset fixes sluggishness).
Only use diagnose_internet when the user is completely offline or can't reach anything.
Match the incident DOMAIN to the runbook DOMAIN. Never pick a database runbook for a network problem.
Return ONLY valid JSON. Do not add commentary.
"""


class RemediationOutput(BaseModel):
    runbook_id: str = Field(description="The id of the runbook to run")
    parameters: dict = Field(default_factory=dict, description="Parameters for the runbook")
    reasoning: str = Field(default="", description="Brief reasoning for this choice")


async def remediation_node(state: AgentState) -> dict:
    """Select a runbook for the top hypothesis and set pending_action."""
    if not state.hypotheses:
        logger.error("Remediation reached with no hypotheses")
        return {"escalated_to_human": True}

    top_hyp = state.hypotheses[-1]
    ticket = state.tickets.get(state.active_ticket_id or "")

    # ── Get available runbooks from MCP ───────────────────────────────────────
    runbook_catalogue: list[dict] = []
    try:
        from synapse.mcp_servers.runbook_client import list_runbooks_from_mcp
        runbook_catalogue = await list_runbooks_from_mcp()
    except Exception as exc:
        logger.warning("Could not fetch runbook catalogue from MCP: %s", exc)
        # Fall back to static list
        runbook_catalogue = [
            {"id": "diagnose_internet",          "title": "Diagnose internet connectivity", "params": {}},
            {"id": "flush_dns",                  "title": "Flush DNS cache", "params": {}},
            {"id": "reconnect_vpn",              "title": "Reconnect VPN", "params": {"host": "str"}},
            {"id": "reset_network_adapter",      "title": "Reset network adapter", "params": {}},
            {"id": "reset_network_stack",        "title": "Reset network stack (Winsock/TCP)", "params": {}},
            {"id": "restart_web_service",        "title": "Restart web service", "params": {"host": "str", "service": "str"}},
            {"id": "restart_db_connection_pool", "title": "Restart DB connection pool", "params": {"host": "str"}},
            {"id": "restart_app_service",        "title": "Restart app service", "params": {"host": "str"}},
            {"id": "clear_cache",                "title": "Clear cache / Redis flush", "params": {"host": "str"}},
            {"id": "scale_workers",              "title": "Scale workers", "params": {"host": "str", "count": "int"}},
        ]

    valid_ids = {r["id"] for r in runbook_catalogue}

    # Use hypothesis remediation_id only if it's a valid catalogue entry
    if top_hyp.remediation_id and top_hyp.remediation_id in valid_ids:
        runbook_id = top_hyp.remediation_id
        affected_ci = ticket.affected_ci if ticket else None
        parameters = {"host": affected_ci or "localhost"}
        logger.info("Using hypothesis runbook: %s", runbook_id)
    elif top_hyp.remediation_id and top_hyp.remediation_id not in valid_ids:
        logger.warning(
            "Hypothesis proposed unknown runbook '%s' — falling through to LLM selection",
            top_hyp.remediation_id,
        )
        top_hyp = top_hyp.model_copy(update={"remediation_id": None})
        runbook_id = ""
        parameters = {}

    if not runbook_id:
        # Ask LLM to choose
        catalogue_text = "\n".join(
            f"- {r['id']}: {r.get('title', r['id'])} (params: {r.get('params', {})})"
            for r in runbook_catalogue
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Original incident: <UNTRUSTED_DOC>"
                    f"{ticket.summary if ticket else ''}"
                    f"</UNTRUSTED_DOC>\n\n"
                    f"Root cause: {top_hyp.statement}\n"
                    f"Confidence: {top_hyp.confidence:.0%}\n"
                    f"Affected CI: {ticket.affected_ci if ticket else 'unknown'}\n\n"
                    f"Available runbooks:\n{catalogue_text}\n\n"
                    f"Select the best runbook and provide parameters."
                ),
            },
        ]
        try:
            parsed: RemediationOutput = await call_llm(
                "remediation", messages, response_format=RemediationOutput
            )
            runbook_id = parsed.runbook_id
            parameters = parsed.parameters
            logger.info("LLM selected runbook=%s reasoning=%s", runbook_id, parsed.reasoning)
        except Exception as exc:
            logger.warning("Remediation LLM failed: %s", exc)
            runbook_id = runbook_catalogue[0]["id"] if runbook_catalogue else "restart_web_service"
            parameters = {"host": ticket.affected_ci if ticket else "localhost"}

    # ── Get the human-readable plan from Runbook MCP ──────────────────────────
    plan_text = ""
    try:
        from synapse.mcp_servers.runbook_client import get_plan_from_mcp
        plan_result = await get_plan_from_mcp(runbook_id=runbook_id, parameters=parameters)
        plan_text = plan_result.get("plan", "")
    except Exception as exc:
        logger.warning("Could not get runbook plan: %s", exc)
        plan_text = f"Execute {runbook_id} with parameters {parameters}"

    action = Action(
        runbook_id=runbook_id,
        parameters=parameters,
        status="proposed",
        plan=plan_text,
    )

    reply = (
        f"**Proposed Remediation**\n\n"
        f"Runbook: `{runbook_id}`\n"
        f"Parameters: {parameters}\n\n"
        f"**Plan:**\n{plan_text}\n\n"
        f"_Awaiting human approval before execution._"
    )

    return {
        "pending_action": action,
        "conversation": [Message(role="assistant", content=reply)],
    }
