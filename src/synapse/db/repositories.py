from __future__ import annotations
import uuid
from datetime import datetime
from typing import Any
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from synapse.db.models import Ticket, ConfigurationItem, CIRelationship, ActionLog, Report, User


# ── Users ──────────────────────────────────────────────────────────────────

async def create_user(
    session: AsyncSession,
    *,
    email: str,
    full_name: str,
    hashed_password: str,
    role: str = "end_user",
) -> User:
    user = User(
        id=f"USR-{uuid.uuid4().hex[:8].upper()}",
        email=email.lower().strip(),
        full_name=full_name,
        hashed_password=hashed_password,
        role=role,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    result = await session.execute(select(User).where(User.email == email.lower().strip()))
    return result.scalar_one_or_none()


async def get_user(session: AsyncSession, user_id: str) -> User | None:
    result = await session.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def list_users(session: AsyncSession) -> list[User]:
    result = await session.execute(select(User).order_by(User.full_name))
    return list(result.scalars().all())


async def get_user_by_nodeid(session: AsyncSession, nodeid: str) -> User | None:
    result = await session.execute(select(User).where(User.meshcentral_nodeid == nodeid))
    return result.scalar_one_or_none()


async def search_users(session: AsyncSession, query: str) -> list[User]:
    """Search users by email, full_name, or id (case-insensitive substring match)."""
    q = f"%{query.strip()}%"
    result = await session.execute(
        select(User).where(
            (User.email.ilike(q))
            | (User.full_name.ilike(q))
            | (User.id.ilike(q))
        ).order_by(User.full_name)
    )
    return list(result.scalars().all())


async def update_user_device(
    session: AsyncSession,
    user_id: str,
    *,
    nodeid: str | None = None,
    hostname: str | None = None,
    ip: str | None = None,
    os_platform: str | None = None,
    online: bool | None = None,
    last_seen: datetime | None = None,
) -> User | None:
    """Update MeshCentral device connection attributes on a user row."""
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        return None
    if nodeid is not None:
        user.meshcentral_nodeid = nodeid
    if hostname is not None:
        user.device_hostname = hostname
    if ip is not None:
        user.last_known_ip = ip
    if os_platform is not None:
        user.os_platform = os_platform
    if online is not None:
        user.agent_online = online
    if last_seen is not None:
        user.device_last_seen = last_seen
    await session.commit()
    await session.refresh(user)
    return user


async def unlink_user_device(session: AsyncSession, user_id: str) -> User | None:
    """Clear all device connection attributes for a user (unlink from MeshCentral)."""
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        return None
    user.meshcentral_nodeid = None
    user.device_hostname = None
    user.last_known_ip = None
    user.os_platform = None
    user.agent_online = False
    user.device_last_seen = None
    await session.commit()
    await session.refresh(user)
    return user


async def create_ticket(
    session: AsyncSession,
    *,
    category: str,
    priority: str,
    summary: str,
    affected_ci: str | None = None,
    owner_id: str | None = None,
) -> Ticket:
    ticket = Ticket(
        id=f"TKT-{uuid.uuid4().hex[:8].upper()}",
        category=category,
        priority=priority,
        status="new",
        summary=summary,
        affected_ci=affected_ci,
        owner_id=owner_id,
    )
    session.add(ticket)
    await session.commit()
    await session.refresh(ticket)
    return ticket


async def update_ticket(session: AsyncSession, ticket_id: str, **fields: Any) -> Ticket:
    result = await session.execute(select(Ticket).where(Ticket.id == ticket_id))
    ticket = result.scalar_one()
    for key, value in fields.items():
        setattr(ticket, key, value)
    await session.commit()
    await session.refresh(ticket)
    return ticket


async def get_ticket(session: AsyncSession, ticket_id: str) -> Ticket | None:
    result = await session.execute(select(Ticket).where(Ticket.id == ticket_id))
    return result.scalar_one_or_none()


async def search_tickets(
    session: AsyncSession,
    *,
    status: str | None = None,
    priority: str | None = None,
    since: datetime | None = None,
    owner_id: str | None = None,
) -> list[Ticket]:
    """Search tickets. Pass owner_id to restrict to one user's tickets (RBAC for end users)."""
    stmt = select(Ticket)
    filters = []
    if status:
        filters.append(Ticket.status == status)
    if priority:
        filters.append(Ticket.priority == priority)
    if since:
        filters.append(Ticket.created_at >= since)
    if owner_id is not None:
        filters.append(Ticket.owner_id == owner_id)
    if filters:
        stmt = stmt.where(and_(*filters))
    stmt = stmt.order_by(Ticket.created_at.desc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def find_open_monitoring_ticket(session: AsyncSession, ci_id: str) -> "Ticket | None":
    """Return the most recent open [AUTO] ticket for this CI, or None."""
    result = await session.execute(
        select(Ticket)
        .where(
            and_(
                Ticket.affected_ci == ci_id,
                Ticket.summary.like("[AUTO]%"),
                Ticket.status.in_(["new", "assigned", "in_progress"]),
            )
        )
        .order_by(Ticket.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def ci_impact(session: AsyncSession, ci_id: str) -> dict:
    """Return the number of CIs that depend on this CI and the CI's criticality."""
    ci_result = await session.execute(
        select(ConfigurationItem).where(ConfigurationItem.id == ci_id)
    )
    ci = ci_result.scalar_one_or_none()
    if ci is None:
        return {"dependents": 0, "criticality": 3}

    # Count all CIs that transitively depend on this one
    dep_result = await session.execute(
        select(func.count()).where(CIRelationship.target_id == ci_id)
    )
    direct_dependents = dep_result.scalar_one() or 0

    return {"dependents": direct_dependents, "criticality": ci.criticality}


async def ci_dependencies(session: AsyncSession, ci_id: str) -> list[ConfigurationItem]:
    """Return CIs that the given CI depends on (targets of its upstream relationships)."""
    result = await session.execute(
        select(ConfigurationItem)
        .join(CIRelationship, CIRelationship.target_id == ConfigurationItem.id)
        .where(CIRelationship.source_id == ci_id)
    )
    return list(result.scalars().all())


async def ci_dependents(session: AsyncSession, ci_id: str) -> list[ConfigurationItem]:
    """Return CIs that depend on the given CI (sources whose target is this CI)."""
    result = await session.execute(
        select(ConfigurationItem)
        .join(CIRelationship, CIRelationship.source_id == ConfigurationItem.id)
        .where(CIRelationship.target_id == ci_id)
    )
    return list(result.scalars().all())


async def get_ci(session: AsyncSession, ci_id: str) -> ConfigurationItem | None:
    result = await session.execute(
        select(ConfigurationItem).where(ConfigurationItem.id == ci_id)
    )
    return result.scalar_one_or_none()


async def search_cis(session: AsyncSession, name_like: str) -> list[ConfigurationItem]:
    result = await session.execute(
        select(ConfigurationItem).where(
            ConfigurationItem.name.ilike(f"%{name_like}%")
        )
    )
    return list(result.scalars().all())


async def log_action(
    session: AsyncSession,
    *,
    ticket_id: str,
    runbook_id: str,
    status: str,
) -> ActionLog:
    entry = ActionLog(ticket_id=ticket_id, runbook_id=runbook_id, status=status)
    session.add(entry)
    await session.commit()
    await session.refresh(entry)
    return entry


async def create_report(
    session: AsyncSession,
    *,
    ticket_id: str,
    body: str,
) -> Report:
    report = Report(ticket_id=ticket_id, body=body)
    session.add(report)
    await session.commit()
    await session.refresh(report)
    return report


async def metrics_snapshot(session: AsyncSession) -> dict:
    total_result = await session.execute(select(func.count()).select_from(Ticket))
    total = total_result.scalar_one() or 0

    open_result = await session.execute(
        select(func.count()).where(Ticket.status.in_(["new", "assigned", "in_progress"]))
    )
    open_count = open_result.scalar_one() or 0

    deflected_result = await session.execute(
        select(func.count()).where(Ticket.category == "deflected")
    )
    deflected = deflected_result.scalar_one() or 0

    escalated_result = await session.execute(
        select(func.count()).where(Ticket.status == "escalated")
    )
    escalated = escalated_result.scalar_one() or 0

    # MTTR: average minutes from created_at to resolved_at for resolved/closed tickets
    mttr_result = await session.execute(
        select(
            func.avg(
                func.extract("epoch", Ticket.resolved_at - Ticket.created_at) / 60.0
            )
        ).where(Ticket.resolved_at.isnot(None))
    )
    mttr = float(mttr_result.scalar_one() or 0.0)

    deflection_rate = round(deflected / total, 4) if total > 0 else 0.0

    return {
        "total_tickets": total,
        "open_tickets": open_count,
        "deflection_rate": deflection_rate,
        "mttr_minutes": round(mttr, 2),
        "escalated": escalated,
    }
