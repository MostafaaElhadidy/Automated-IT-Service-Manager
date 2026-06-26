"""Notification utilities — stub for demo; replace with PagerDuty/Slack in prod."""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


def notify_it_team(ticket_id: str, summary: str, report_body: str) -> None:
    """Notify the IT team of an escalated incident."""
    logger.warning(
        "[NOTIFY] IT TEAM ALERT\nTicket: %s\nSummary: %s\nReport preview: %s",
        ticket_id,
        summary,
        report_body[:200],
    )
    # In production: call PagerDuty / Slack / email API here


def notify_user(session_id: str, message: str) -> None:
    """Notify the user of an update (stub)."""
    logger.info("[NOTIFY] User %s: %s", session_id[:8], message[:100])
