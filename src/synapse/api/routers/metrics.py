from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from synapse.api.deps import get_db
from synapse.api.schemas import MetricsOut
from synapse.db import repositories as repo

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("", response_model=MetricsOut)
async def get_metrics(db: AsyncSession = Depends(get_db)) -> MetricsOut:
    snap = await repo.metrics_snapshot(db)
    return MetricsOut(
        open_tickets=snap["open_tickets"],
        deflection_rate=snap["deflection_rate"],
        mttr_minutes=snap["mttr_minutes"],
        escalated=snap["escalated"],
        total_tickets=snap["total_tickets"],
    )
