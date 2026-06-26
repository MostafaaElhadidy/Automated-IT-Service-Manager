from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from synapse.api.deps import get_db
from synapse.api.schemas import HealthOut

router = APIRouter(tags=["health"])


@router.get("/healthz", response_model=HealthOut)
async def healthz(db: AsyncSession = Depends(get_db)) -> HealthOut:
    # Check DB
    db_status = "ok"
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        db_status = "error"

    # Check Chroma
    chroma_status = "ok"
    try:
        import chromadb
        from synapse.config import settings
        client = chromadb.PersistentClient(path=settings.chroma_dir)
        client.list_collections()
    except Exception:
        chroma_status = "error"

    overall = "ok" if db_status == "ok" else "degraded"
    return HealthOut(status=overall, db=db_status, chroma=chroma_status)
