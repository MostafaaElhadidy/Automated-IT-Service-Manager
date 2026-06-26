"""Send email alerts to the IT team using the Resend API (free tier).

Setup:
  1. Sign up at https://resend.com — no credit card needed.
  2. Go to API Keys → Create API Key → copy it.
  3. Add to .env:
       RESEND_API_KEY=re_xxxxxxxxxxxx
       ALERT_EMAIL_TO=itteam@yourcompany.com
       ALERT_EMAIL_FROM=SynapseITSM <onboarding@resend.dev>   # free-tier sender

Free tier limits: 3 000 emails/month, 100/day.
On the free tier the "from" address must be onboarding@resend.dev unless you
verify your own domain in the Resend dashboard.
"""
from __future__ import annotations
import logging

import httpx

from synapse.config import settings

logger = logging.getLogger(__name__)

RESEND_URL = "https://api.resend.com/emails"


async def send_monitoring_alert(
    *,
    ticket_id: str,
    ci_id: str,
    metric: str,
    value: float,
    priority: str,
    summary: str,
) -> None:
    """Send one email per new monitoring ticket to the IT on-call address."""
    if not settings.resend_api_key or not settings.alert_email_to:
        logger.debug("[email] Resend not configured — skipping alert for ticket %s", ticket_id)
        return

    subject = f"[SynapseITSM] {priority} Alert — {ci_id} needs IT attention"
    body = (
        f"SynapseITSM Monitoring Alert\n"
        f"{'=' * 42}\n\n"
        f"Ticket  : {ticket_id}\n"
        f"Priority: {priority}\n"
        f"CI      : {ci_id}\n"
        f"Metric  : {metric} = {value:.3f}\n"
        f"Summary : {summary}\n\n"
        f"The AI has analysed this anomaly and proposed a remediation action.\n"
        f"Please open the Operations Dashboard, review the Root Cause and\n"
        f"Action Plan under 'Pending Approvals', then Approve or Reject.\n\n"
        f"Dashboard: {settings.dashboard_url}\n"
    )

    payload = {
        "from": settings.alert_email_from,
        "to": [settings.alert_email_to],
        "subject": subject,
        "text": body,
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                RESEND_URL,
                headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                json=payload,
            )
            resp.raise_for_status()
        logger.info("[email] Alert sent to %s for ticket %s", settings.alert_email_to, ticket_id)
    except Exception as exc:
        logger.warning("[email] Failed to send alert for ticket %s: %s", ticket_id, exc)
