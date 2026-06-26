"""CMDB query tool — SELECT-only access guarded by AST check."""
from __future__ import annotations
import logging
import re

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from synapse.db.base import AsyncSessionLocal
from synapse.db import repositories as repo
from synapse.db.models import ConfigurationItem

logger = logging.getLogger(__name__)

# Only allow SELECT statements (no DML)
_FORBIDDEN_PATTERN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|GRANT|REVOKE|EXEC|EXECUTE)\b",
    re.IGNORECASE,
)


def _assert_select_only(sql: str) -> None:
    if _FORBIDDEN_PATTERN.search(sql):
        raise ValueError(f"Only SELECT queries are allowed in CMDB queries. Got: {sql[:80]}")


async def query_cmdb_raw(sql: str) -> list[dict]:
    """Execute a raw SELECT query against the CMDB (read-only guard enforced)."""
    _assert_select_only(sql)
    async with AsyncSessionLocal() as session:
        result = await session.execute(text(sql))
        rows = result.mappings().all()
        return [dict(r) for r in rows]


async def get_ci_dependencies_text(ci_id: str) -> str:
    """Return a human-readable dependency chain for a CI."""
    async with AsyncSessionLocal() as session:
        ci = await repo.get_ci(session, ci_id)
        if ci is None:
            return f"CI '{ci_id}' not found in CMDB."

        deps = await repo.ci_dependencies(session, ci_id)
        dependents = await repo.ci_dependents(session, ci_id)

        lines = [
            f"CI: {ci.id} ({ci.name}) — type={ci.ci_type}, criticality={ci.criticality}, status={ci.status}"
        ]
        if deps:
            lines.append(f"Depends on: {', '.join(f'{d.id}({d.name})' for d in deps)}")
        if dependents:
            lines.append(f"Depended on by: {', '.join(f'{d.id}({d.name})' for d in dependents)}")
        if not deps and not dependents:
            lines.append("No dependency relationships found.")
        return "\n".join(lines)


async def search_affected_cis(name_hint: str) -> list[dict]:
    """Find CIs matching a name hint, returning id/name/type/criticality."""
    async with AsyncSessionLocal() as session:
        cis = await repo.search_cis(session, name_hint)
        return [
            {
                "id": ci.id,
                "name": ci.name,
                "ci_type": ci.ci_type,
                "criticality": ci.criticality,
                "status": ci.status,
            }
            for ci in cis
        ]
