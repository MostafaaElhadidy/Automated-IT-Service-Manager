"""Close all open [AUTO] monitoring tickets so the monitoring agent can create fresh ones."""
import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

DATABASE_URL = "postgresql+asyncpg://synapse:synapse@localhost:5432/synapse"


async def reset():
    engine = create_async_engine(DATABASE_URL)
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                "UPDATE tickets SET status = 'closed' "
                "WHERE summary LIKE '[AUTO]%' "
                "AND status IN ('new', 'assigned', 'in_progress') "
                "RETURNING id"
            )
        )
        rows = result.fetchall()
        print(f"Closed {len(rows)} monitoring ticket(s):")
        for r in rows:
            print(f"  {r[0]}")
        if not rows:
            print("No open monitoring tickets found.")
    await engine.dispose()


asyncio.run(reset())
