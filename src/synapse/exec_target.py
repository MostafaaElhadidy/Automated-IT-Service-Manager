"""Execution target resolution for runbook dispatch.

Determines whether a runbook should run on the backend server (LocalTarget)
or on a specific user's PC/laptop via MeshCentral (RemoteTarget).

Usage in verify.py:
    target = await resolve_target(ticket_id, user_id)
    result = await execute_and_verify(runbook_id, parameters, target=target)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)


# ── Target types ──────────────────────────────────────────────────────────────

@dataclass
class LocalTarget:
    """Run the runbook on the backend server (current behavior)."""
    kind: Literal["local"] = "local"

    @property
    def label(self) -> str:
        return "local server"


@dataclass
class RemoteTarget:
    """Run the runbook on a specific user device via MeshCentral."""
    nodeid: str
    os_platform: str = "windows"
    hostname: str = ""
    user_id: str = ""
    kind: Literal["remote"] = "remote"

    @property
    def label(self) -> str:
        name = self.hostname or self.nodeid
        return f"{name} ({self.os_platform})"


ExecTarget = LocalTarget | RemoteTarget


# ── Runbooks that make sense to run on the user's PC ─────────────────────────
# All others (db pool, cache, service restart, scale_workers) run server-side.

REMOTE_CAPABLE = frozenset({
    "diagnose_internet",
    "flush_dns",
    "reset_network_adapter",
    "reconnect_vpn",
    "reset_network_stack",
})


def is_remote_capable(runbook_id: str) -> bool:
    return runbook_id in REMOTE_CAPABLE


# ── Target resolver ───────────────────────────────────────────────────────────

async def resolve_target(ticket_id: str | None, user_id: str | None) -> ExecTarget:
    """Resolve the correct ExecTarget for a runbook execution.

    Chain: ticket_id → ticket.owner_id → users.meshcentral_nodeid
    Falls back to LocalTarget when:
      - ticket is unowned (monitoring/[AUTO] tickets)
      - user has no enrolled device
      - MeshCentral is disabled
      - agent is offline
    """
    from synapse.config import settings

    # Monitoring system tickets always run locally
    if user_id == "monitoring_system" or not ticket_id:
        return LocalTarget()

    if not settings.meshcentral_enabled:
        logger.debug("MeshCentral disabled — using LocalTarget for ticket=%s", ticket_id)
        return LocalTarget()

    try:
        from synapse.db.base import AsyncSessionLocal
        from synapse.db import repositories as repo

        async with AsyncSessionLocal() as session:
            # Look up the ticket to get owner_id
            ticket = await repo.get_ticket(session, ticket_id)
            owner_id = ticket.owner_id if ticket else None

            if not owner_id:
                logger.debug("Ticket %s has no owner — using LocalTarget", ticket_id)
                return LocalTarget()

            user = await repo.get_user(session, owner_id)
            if user is None or not user.meshcentral_nodeid:
                logger.debug(
                    "User %s has no enrolled device — using LocalTarget", owner_id
                )
                return LocalTarget()

            if not user.agent_online:
                logger.warning(
                    "Device for user %s (nodeid=%s) is offline — falling back to LocalTarget",
                    user.email, user.meshcentral_nodeid,
                )
                return LocalTarget()

            return RemoteTarget(
                nodeid=user.meshcentral_nodeid,
                os_platform=user.os_platform or "windows",
                hostname=user.device_hostname or "",
                user_id=user.id,
            )

    except Exception as exc:
        logger.error("Target resolution failed for ticket=%s: %s — using LocalTarget", ticket_id, exc)
        return LocalTarget()
