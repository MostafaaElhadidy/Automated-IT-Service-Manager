"""Per-session notification queue for pushing approval results to the Chainlit chat.

Written by the approvals router after approve/reject; consumed (and cleared)
by the GET /{sid}/notification polling endpoint called from the Chainlit UI.
"""
from __future__ import annotations

# session_id → pending notification message (one at a time is enough)
_notifications: dict[str, str] = {}


def set_notification(session_id: str, message: str) -> None:
    _notifications[session_id] = message


def pop_notification(session_id: str) -> str | None:
    """Return and remove the notification, or None if none is pending."""
    return _notifications.pop(session_id, None)
