"""Deterministic seed for the CMDB + sample historical tickets.

Run: python -m synapse.db.seed
Uses SIM_SEED from settings so every run is identical.
"""
from __future__ import annotations
import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from synapse.db.base import AsyncSessionLocal, engine
from synapse.db.models import Base, ConfigurationItem, CIRelationship, Ticket, User
from synapse.api.security import hash_password

# ── Demo users (password is the same as the name before @ for easy demo) ──────
# email · full_name · role · password
DEMO_USERS: list[dict] = [
    {"email": "admin@synapse.io",  "full_name": "System Admin",   "role": "admin",    "password": "admin123"},
    {"email": "it@synapse.io",     "full_name": "IT Team Member", "role": "it_team",  "password": "it123456"},
    {"email": "sara@synapse.io",   "full_name": "Sara (End User)","role": "end_user", "password": "sara123"},
    {"email": "omar@synapse.io",   "full_name": "Omar (End User)","role": "end_user", "password": "omar123"},
]

# ── CI catalogue (id, name, ci_type, criticality) ────────────────────────────
CIS: list[dict] = [
    # ── Load balancers ────────────────────────────────────────────────────────
    {"id": "LB-01",    "name": "Load Balancer 01",        "ci_type": "lb",      "criticality": 1},
    {"id": "LB-02",    "name": "Load Balancer 02 (CRM)",  "ci_type": "lb",      "criticality": 2},
    # ── Web servers ───────────────────────────────────────────────────────────
    {"id": "WEB-01",   "name": "Web Server 01",           "ci_type": "server",  "criticality": 2},
    {"id": "WEB-02",   "name": "Web Server 02",           "ci_type": "server",  "criticality": 2},
    {"id": "WEB-03",   "name": "Web Server 03 (CRM)",     "ci_type": "server",  "criticality": 2},
    # ── Application servers ───────────────────────────────────────────────────
    {"id": "APP-01",   "name": "App Server 01 (Billing)", "ci_type": "server",  "criticality": 2},
    {"id": "APP-02",   "name": "App Server 02 (HR)",      "ci_type": "server",  "criticality": 3},
    # ── Databases ─────────────────────────────────────────────────────────────
    {"id": "DB-01",    "name": "PostgreSQL Primary",       "ci_type": "db",      "criticality": 1},
    {"id": "DB-02",    "name": "PostgreSQL Replica",       "ci_type": "db",      "criticality": 2},
    {"id": "DB-03",    "name": "MySQL CRM DB",             "ci_type": "db",      "criticality": 2},
    # ── Cache ─────────────────────────────────────────────────────────────────
    {"id": "REDIS-01", "name": "Redis Cache 01",           "ci_type": "cache",   "criticality": 2},
    {"id": "REDIS-02", "name": "Redis Cache 02 (session)", "ci_type": "cache",   "criticality": 3},
    # ── Network ───────────────────────────────────────────────────────────────
    {"id": "SW-CORE-01","name": "Core Switch 01",          "ci_type": "network", "criticality": 1},
    {"id": "SW-CORE-02","name": "Core Switch 02",          "ci_type": "network", "criticality": 1},
    {"id": "FW-01",    "name": "Firewall 01",              "ci_type": "network", "criticality": 1},
    # ── Applications ──────────────────────────────────────────────────────────
    {"id": "APP-SALES","name": "Sales Dashboard",          "ci_type": "app",     "criticality": 1},
    {"id": "APP-CRM",  "name": "CRM Application",          "ci_type": "app",     "criticality": 2},
    {"id": "APP-BILL", "name": "Billing Application",      "ci_type": "app",     "criticality": 1},
    {"id": "APP-HR",   "name": "HR Portal",                "ci_type": "app",     "criticality": 3},
    {"id": "APP-DASH", "name": "Ops Dashboard",            "ci_type": "app",     "criticality": 3},
    # ── Storage ───────────────────────────────────────────────────────────────
    {"id": "STOR-01",  "name": "NFS Storage 01",           "ci_type": "server",  "criticality": 2},
    # ── Monitoring infra ──────────────────────────────────────────────────────
    {"id": "MON-01",   "name": "Prometheus/Grafana",       "ci_type": "server",  "criticality": 3},
    # ── Message queue ─────────────────────────────────────────────────────────
    {"id": "MQ-01",    "name": "RabbitMQ 01",              "ci_type": "server",  "criticality": 2},
    # ── CDN / proxy ───────────────────────────────────────────────────────────
    {"id": "CDN-01",   "name": "CDN Edge Node",            "ci_type": "network", "criticality": 2},
    # ── Auth service ──────────────────────────────────────────────────────────
    {"id": "AUTH-01",  "name": "Auth Service",             "ci_type": "server",  "criticality": 1},
]

# ── Dependency graph (source depends_on target) ───────────────────────────────
# Meaning: if target fails, source is impacted.
RELATIONSHIPS: list[dict] = [
    # Sales Dashboard → LB-01 → WEB-01, WEB-02 → DB-01, REDIS-01
    {"source_id": "APP-SALES", "target_id": "LB-01",     "rel_type": "depends_on"},
    {"source_id": "LB-01",     "target_id": "WEB-01",    "rel_type": "hosts"},
    {"source_id": "LB-01",     "target_id": "WEB-02",    "rel_type": "hosts"},
    {"source_id": "WEB-01",    "target_id": "DB-01",     "rel_type": "depends_on"},
    {"source_id": "WEB-02",    "target_id": "DB-01",     "rel_type": "depends_on"},
    {"source_id": "WEB-01",    "target_id": "REDIS-01",  "rel_type": "depends_on"},
    {"source_id": "WEB-02",    "target_id": "REDIS-01",  "rel_type": "depends_on"},
    {"source_id": "WEB-01",    "target_id": "AUTH-01",   "rel_type": "depends_on"},
    {"source_id": "WEB-02",    "target_id": "AUTH-01",   "rel_type": "depends_on"},
    # CRM Application
    {"source_id": "APP-CRM",   "target_id": "LB-02",    "rel_type": "depends_on"},
    {"source_id": "LB-02",     "target_id": "WEB-03",   "rel_type": "hosts"},
    {"source_id": "WEB-03",    "target_id": "DB-03",    "rel_type": "depends_on"},
    {"source_id": "WEB-03",    "target_id": "REDIS-02", "rel_type": "depends_on"},
    # Billing
    {"source_id": "APP-BILL",  "target_id": "APP-01",   "rel_type": "depends_on"},
    {"source_id": "APP-01",    "target_id": "DB-01",    "rel_type": "depends_on"},
    {"source_id": "APP-01",    "target_id": "MQ-01",    "rel_type": "depends_on"},
    # HR Portal
    {"source_id": "APP-HR",    "target_id": "APP-02",   "rel_type": "depends_on"},
    {"source_id": "APP-02",    "target_id": "DB-02",    "rel_type": "depends_on"},
    # Ops dashboard
    {"source_id": "APP-DASH",  "target_id": "MON-01",  "rel_type": "depends_on"},
    # Network backbone
    {"source_id": "LB-01",     "target_id": "SW-CORE-01","rel_type": "connects_to"},
    {"source_id": "LB-02",     "target_id": "SW-CORE-01","rel_type": "connects_to"},
    {"source_id": "SW-CORE-01","target_id": "FW-01",   "rel_type": "connects_to"},
    {"source_id": "SW-CORE-02","target_id": "FW-01",   "rel_type": "connects_to"},
    # Storage
    {"source_id": "WEB-01",    "target_id": "STOR-01",  "rel_type": "depends_on"},
    {"source_id": "WEB-02",    "target_id": "STOR-01",  "rel_type": "depends_on"},
    # CDN
    {"source_id": "APP-SALES", "target_id": "CDN-01",  "rel_type": "depends_on"},
    # DB replica
    {"source_id": "DB-02",     "target_id": "DB-01",   "rel_type": "depends_on"},
]

# ── Historical tickets (mixed states) ─────────────────────────────────────────
_now = datetime.now(timezone.utc)

HISTORICAL_TICKETS: list[dict] = [
    {
        "id": "TKT-HIST0001",
        "category": "incident",
        "priority": "P1",
        "status": "closed",
        "summary": "Sales dashboard unreachable — WEB-02 worker pool exhausted",
        "affected_ci": "WEB-02",
        "created_at": _now - timedelta(days=7),
        "resolved_at": _now - timedelta(days=7, hours=-1),
    },
    {
        "id": "TKT-HIST0002",
        "category": "incident",
        "priority": "P2",
        "status": "closed",
        "summary": "DB connection pool exhausted on DB-01, billing app slow",
        "affected_ci": "DB-01",
        "created_at": _now - timedelta(days=5),
        "resolved_at": _now - timedelta(days=5, hours=-2),
    },
    {
        "id": "TKT-HIST0003",
        "category": "incident",
        "priority": "P2",
        "status": "closed",
        "summary": "Redis cache stampede caused high latency on Sales Dashboard",
        "affected_ci": "REDIS-01",
        "created_at": _now - timedelta(days=3),
        "resolved_at": _now - timedelta(days=3, hours=-0.5),
    },
    {
        "id": "TKT-HIST0004",
        "category": "request",
        "priority": "P4",
        "status": "resolved",
        "summary": "Request to increase max connections on DB-01",
        "affected_ci": "DB-01",
        "created_at": _now - timedelta(days=10),
        "resolved_at": _now - timedelta(days=9),
    },
    {
        "id": "TKT-HIST0005",
        "category": "incident",
        "priority": "P1",
        "status": "open",
        "summary": "CRM application login failures — Auth-01 high CPU",
        "affected_ci": "AUTH-01",
        "created_at": _now - timedelta(hours=2),
        "resolved_at": None,
    },
]


async def _seed(session: AsyncSession) -> None:
    # ── Users ───────────────────────────────────────────────────────────────────
    for idx, u in enumerate(DEMO_USERS, 1):
        from sqlalchemy import select
        existing = await session.execute(select(User).where(User.email == u["email"]))
        if existing.scalar_one_or_none() is None:
            session.add(User(
                id=f"USR-DEMO{idx:04d}",
                email=u["email"],
                full_name=u["full_name"],
                hashed_password=hash_password(u["password"]),
                role=u["role"],
            ))
    await session.flush()

    # ── CIs ───────────────────────────────────────────────────────────────────
    for ci_data in CIS:
        existing = await session.get(ConfigurationItem, ci_data["id"])
        if existing is None:
            session.add(ConfigurationItem(**ci_data))
    await session.flush()

    # ── Relationships ─────────────────────────────────────────────────────────
    for rel_data in RELATIONSHIPS:
        result = await session.execute(
            text(
                "SELECT 1 FROM ci_relationships WHERE source_id=:s AND target_id=:t AND rel_type=:r"
            ),
            {"s": rel_data["source_id"], "t": rel_data["target_id"], "r": rel_data["rel_type"]},
        )
        if result.one_or_none() is None:
            session.add(CIRelationship(**rel_data))
    await session.flush()

    # ── Historical tickets ─────────────────────────────────────────────────────
    for t_data in HISTORICAL_TICKETS:
        existing = await session.get(Ticket, t_data["id"])
        if existing is None:
            ticket = Ticket(
                id=t_data["id"],
                category=t_data["category"],
                priority=t_data["priority"],
                status=t_data["status"],
                summary=t_data["summary"],
                affected_ci=t_data.get("affected_ci"),
                created_at=t_data["created_at"],
                resolved_at=t_data.get("resolved_at"),
            )
            session.add(ticket)
    await session.commit()

    print(
        f"[seed] {len(DEMO_USERS)} users, {len(CIS)} CIs, "
        f"{len(RELATIONSHIPS)} relationships, {len(HISTORICAL_TICKETS)} tickets seeded."
    )


async def seed() -> None:
    async with AsyncSessionLocal() as session:
        await _seed(session)


if __name__ == "__main__":
    asyncio.run(seed())
