"""Priority computation: impact (from CMDB) × urgency → P1-P5."""
from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession
from synapse.db import repositories as repo
from synapse.state import Priority


# Impact × Urgency matrix → Priority
# Impact: 1=many dependents/high criticality, 5=isolated/low criticality
# Urgency: 1=immediate/user-blocking, 5=cosmetic
_MATRIX: dict[tuple[int, int], Priority] = {
    (1, 1): "P1", (1, 2): "P1", (1, 3): "P2", (1, 4): "P2", (1, 5): "P3",
    (2, 1): "P1", (2, 2): "P2", (2, 3): "P2", (2, 4): "P3", (2, 5): "P3",
    (3, 1): "P2", (3, 2): "P2", (3, 3): "P3", (3, 4): "P3", (3, 5): "P4",
    (4, 1): "P2", (4, 2): "P3", (4, 3): "P3", (4, 4): "P4", (4, 5): "P4",
    (5, 1): "P3", (5, 2): "P3", (5, 3): "P4", (5, 4): "P4", (5, 5): "P5",
}


def _impact_score(dependents: int, criticality: int) -> int:
    """Convert raw CMDB impact data into an impact bucket 1-5."""
    # Criticality 1 is highest; many dependents raise impact
    base = criticality  # 1–5 already
    if dependents >= 5:
        base = max(1, base - 2)
    elif dependents >= 2:
        base = max(1, base - 1)
    return max(1, min(5, base))


async def compute_priority(
    session: AsyncSession,
    ci_id: str | None,
    urgency: int,
) -> Priority:
    """Compute ticket priority from CMDB impact and caller-supplied urgency (1-5)."""
    if ci_id:
        impact_data = await repo.ci_impact(session, ci_id)
        impact = _impact_score(impact_data["dependents"], impact_data["criticality"])
    else:
        impact = 3  # unknown CI → medium impact

    urgency = max(1, min(5, urgency))
    return _MATRIX.get((impact, urgency), "P3")


def urgency_from_text(text: str) -> int:
    """Heuristic: extract urgency level from natural-language description."""
    text_lower = text.lower()
    if any(w in text_lower for w in ("urgent", "critical", "down", "outage", "can't", "cannot", "emergency")):
        return 1
    if any(w in text_lower for w in ("slow", "degraded", "intermittent", "failing")):
        return 2
    if any(w in text_lower for w in ("issue", "problem", "error")):
        return 3
    if any(w in text_lower for w in ("request", "please", "need", "want")):
        return 4
    return 3
