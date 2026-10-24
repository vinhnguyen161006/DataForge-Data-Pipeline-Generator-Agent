"""Delivery-loop startup recovery retries after a temporary failure."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.graph.builder import build_graph
from app.graph.context import GraphContext
from app.services import runs as service


async def test_startup_recovery_retries_until_success_then_stops_recovering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(expire_on_commit=False)
    context = GraphContext(sessionmaker=factory, propose_design=AsyncMock())
    graph = build_graph(InMemorySaver())
    recovered = AsyncMock(side_effect=[RuntimeError("Database unavailable"), 0])
    intents = AsyncMock(return_value=0)
    drained = asyncio.Event()
    ticks = 0

    async def finish(*args: object) -> int:
        nonlocal ticks
        ticks += 1
        if ticks >= 3:
            drained.set()
        return 0

    monkeypatch.setattr(service, "recover_pending_runs", recovered)
    monkeypatch.setattr(service, "deliver_resume_intents", intents)
    monkeypatch.setattr(service, "deliver_finished_jobs", finish)
    task = asyncio.create_task(
        service.job_delivery_loop(factory, graph, context, interval_seconds=0.001)
    )
    try:
        await asyncio.wait_for(drained.wait(), 2)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert recovered.await_count == 2
    assert intents.await_count >= 3
