"""Device management + remote-agent result callback endpoints.

Device management (IT/admin only):
  GET  /devices/users          — list all users with device attributes
  GET  /devices/users/search   — search by email / name / id
  GET  /devices/users/{id}     — single user device info
  PUT  /devices/users/{id}     — update device attributes for a user
  DELETE /devices/users/{id}/device — unlink device from user
  POST /devices/sync           — pull latest device state from MeshCentral

Agent result callback (authenticated by per-job HMAC token):
  POST /agent/result           — remote script posts its execution result here
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from synapse.api.deps import get_db, require_role
from synapse.api.schemas import (
    AgentResultPayload,
    DeviceUpdate,
    DeviceSyncResult,
    UserDeviceInfo,
)
from synapse.api import job_result_store
from synapse.db import repositories as repo
from synapse.db.models import User

logger = logging.getLogger(__name__)

router = APIRouter(tags=["devices"])


# ── Conversion helper ─────────────────────────────────────────────────────────

def _to_device_info(u: User) -> UserDeviceInfo:
    return UserDeviceInfo(
        id=u.id,
        email=u.email,
        full_name=u.full_name,
        role=u.role,
        meshcentral_nodeid=u.meshcentral_nodeid,
        device_hostname=u.device_hostname,
        last_known_ip=u.last_known_ip,
        os_platform=u.os_platform,
        agent_online=u.agent_online,
        device_last_seen=u.device_last_seen,
    )


# ── Device listing / search ───────────────────────────────────────────────────

@router.get("/devices/users", response_model=list[UserDeviceInfo])
async def list_user_devices(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_role("it_team", "admin")),
) -> list[UserDeviceInfo]:
    """Return all users with their current device connection attributes. IT/admin only."""
    users = await repo.list_users(db)
    return [_to_device_info(u) for u in users]


@router.get("/devices/users/search", response_model=list[UserDeviceInfo])
async def search_user_devices(
    q: str = Query(..., min_length=1, description="Search by email, full name, or user ID"),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_role("it_team", "admin")),
) -> list[UserDeviceInfo]:
    """Search users by email / full_name / id substring. IT/admin only."""
    users = await repo.search_users(db, q)
    return [_to_device_info(u) for u in users]


@router.get("/devices/users/{user_id}", response_model=UserDeviceInfo)
async def get_user_device(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    _actor: User = Depends(require_role("it_team", "admin")),
) -> UserDeviceInfo:
    """Get device info for a specific user by ID. IT/admin only."""
    user = await repo.get_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return _to_device_info(user)


# ── Device attribute update (the main form endpoint) ─────────────────────────

@router.put("/devices/users/{user_id}", response_model=UserDeviceInfo)
async def update_user_device(
    user_id: str,
    body: DeviceUpdate,
    db: AsyncSession = Depends(get_db),
    _actor: User = Depends(require_role("it_team", "admin")),
) -> UserDeviceInfo:
    """Update MeshCentral device attributes for a user. IT/admin only.

    Accepts any combination of fields — only supplied (non-null) fields are written.
    Use this to manually link a nodeid to a user, correct the hostname, IP, etc.
    """
    user = await repo.get_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    updated = await repo.update_user_device(
        db,
        user_id,
        nodeid=body.meshcentral_nodeid,
        hostname=body.device_hostname,
        ip=body.last_known_ip,
        os_platform=body.os_platform,
        online=body.agent_online,
        last_seen=datetime.now(timezone.utc) if body.agent_online is not None else None,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="User not found")

    logger.info(
        "Device attributes updated for user=%s by actor=%s: %s",
        user_id, _actor.email, body.model_dump(exclude_none=True),
    )
    return _to_device_info(updated)


# ── Unlink device ─────────────────────────────────────────────────────────────

@router.delete("/devices/users/{user_id}/device", response_model=UserDeviceInfo)
async def unlink_user_device(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    _actor: User = Depends(require_role("it_team", "admin")),
) -> UserDeviceInfo:
    """Clear all device connection attributes for a user. IT/admin only."""
    updated = await repo.unlink_user_device(db, user_id)
    if updated is None:
        raise HTTPException(status_code=404, detail="User not found")
    logger.info("Device unlinked for user=%s by actor=%s", user_id, _actor.email)
    return _to_device_info(updated)


# ── MeshCentral sync ──────────────────────────────────────────────────────────

@router.post("/devices/sync", response_model=DeviceSyncResult)
async def sync_devices_from_meshcentral(
    _actor: User = Depends(require_role("it_team", "admin")),
) -> DeviceSyncResult:
    """Trigger a sync from MeshCentral: pull node list and update users. IT/admin only."""
    from synapse.mcp_servers import meshcentral_client

    result = await meshcentral_client.sync_devices()
    logger.info("MeshCentral sync by %s: %s", _actor.email, result)
    return DeviceSyncResult(**result)


# ── Agent result callback ─────────────────────────────────────────────────────

@router.post("/agent/result", status_code=204)
async def agent_result(
    body: AgentResultPayload,
    x_job_token: str | None = Header(default=None, alias="X-Job-Token"),
) -> None:
    """Receive execution results posted back by a remote remediation script.

    The script includes an HMAC token (X-Job-Token) so only scripts dispatched
    by this backend can write results. Returns 204 so the script doesn't block.
    """
    if x_job_token is None or not job_result_store.verify_job_token(body.job_id, x_job_token):
        logger.warning("Agent result rejected for job_id=%s — bad or missing token", body.job_id)
        raise HTTPException(status_code=401, detail="Invalid job token")

    known = job_result_store.report_step(
        body.job_id, body.step, body.ok, body.output
    )
    if not known:
        logger.warning("Agent result for unknown job_id=%s (may have expired)", body.job_id)
        # Still return 204 — don't confuse the remote script
