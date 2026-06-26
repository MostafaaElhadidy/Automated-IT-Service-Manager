"""Pytest configuration — async setup + deterministic fake LLM."""
from __future__ import annotations
import asyncio
import os
import sys
import pytest
import pytest_asyncio

# Make src/ importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# Use in-memory SQLite for tests (no Postgres required)
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("DATABASE_URL_RO", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("CHROMA_DIR", "/tmp/synapse_test_chroma")
os.environ.setdefault("FASTPATH_THRESHOLD", "0.82")
os.environ.setdefault("SIM_SEED", "42")


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def db_engine():
    """Create in-memory SQLite tables for testing."""
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from synapse.db.base import Base
    import synapse.db.models  # register models

    # SQLite doesn't support asyncpg — patch the engine
    test_url = "sqlite+aiosqlite:///:memory:"
    engine = create_async_engine(test_url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    """Yield an async session scoped to each test (rolled back after)."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
    factory = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
        await session.rollback()
