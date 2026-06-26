"""Phase 0 acceptance test — DB round-trip."""
from __future__ import annotations
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from synapse.db import repositories as repo


@pytest.mark.asyncio
async def test_create_and_get_ticket(db_session: AsyncSession):
    ticket = await repo.create_ticket(
        db_session,
        category="incident",
        priority="P1",
        summary="Test incident: sales dashboard down",
        affected_ci=None,
    )
    assert ticket.id.startswith("TKT-")
    assert ticket.priority == "P1"
    assert ticket.status == "new"

    # Round-trip
    fetched = await repo.get_ticket(db_session, ticket.id)
    assert fetched is not None
    assert fetched.id == ticket.id
    assert fetched.summary == "Test incident: sales dashboard down"


@pytest.mark.asyncio
async def test_update_ticket(db_session: AsyncSession):
    ticket = await repo.create_ticket(
        db_session,
        category="request",
        priority="P3",
        summary="Need VPN access",
    )
    updated = await repo.update_ticket(db_session, ticket.id, status="resolved")
    assert updated.status == "resolved"


@pytest.mark.asyncio
async def test_search_tickets(db_session: AsyncSession):
    for i in range(3):
        await repo.create_ticket(
            db_session,
            category="incident",
            priority="P2",
            summary=f"Incident #{i}",
        )
    tickets = await repo.search_tickets(db_session)
    assert len(tickets) >= 3


@pytest.mark.asyncio
async def test_log_action(db_session: AsyncSession):
    ticket = await repo.create_ticket(
        db_session,
        category="incident",
        priority="P1",
        summary="DB down",
    )
    log = await repo.log_action(
        db_session,
        ticket_id=ticket.id,
        runbook_id="restart_db_connection_pool",
        status="executed",
    )
    assert log.ticket_id == ticket.id
    assert log.runbook_id == "restart_db_connection_pool"


@pytest.mark.asyncio
async def test_create_report(db_session: AsyncSession):
    ticket = await repo.create_ticket(
        db_session,
        category="incident",
        priority="P1",
        summary="Cache failure",
    )
    report = await repo.create_report(
        db_session,
        ticket_id=ticket.id,
        body="Root cause: cache stampede. Actions tried: clear_cache (failed).",
    )
    assert report.ticket_id == ticket.id


@pytest.mark.asyncio
async def test_metrics_snapshot(db_session: AsyncSession):
    snap = await repo.metrics_snapshot(db_session)
    assert "open_tickets" in snap
    assert "deflection_rate" in snap
    assert "mttr_minutes" in snap
