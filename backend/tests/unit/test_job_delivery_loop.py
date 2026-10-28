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


@pytest.mark.parametrize("failed_step", ["recovery", "intents", "jobs"])
async def test_readiness_waits_for_successful_recovery_and_first_delivery(
    monkeypatch: pytest.MonkeyPatch, failed_step: str
) -> None:
    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(expire_on_commit=False)
    context = GraphContext(sessionmaker=factory, propose_design=AsyncMock())
    graph = build_graph(InMemorySaver())
    ready = asyncio.Event()
    second_tick = asyncio.Event()
    release_second_tick = asyncio.Event()
    calls = {"recovery": 0, "intents": 0, "jobs": 0}

    async def recover(*args: object) -> int:
        calls["recovery"] += 1
        if failed_step == "recovery" and calls["recovery"] == 1:
            raise RuntimeError("Temporary recovery failure")
        return 0

    async def intents(*args: object) -> int:
        calls["intents"] += 1
        if calls["intents"] == 2:
            second_tick.set()
            await release_second_tick.wait()
        if failed_step == "intents" and calls["intents"] == 1:
            raise RuntimeError("Temporary intent delivery failure")
        return 0

    async def jobs(*args: object) -> int:
        calls["jobs"] += 1
        if failed_step == "jobs" and calls["jobs"] == 1:
            raise RuntimeError("Temporary result delivery failure")
        return 0

    monkeypatch.setattr(service, "recover_pending_runs", recover)
    monkeypatch.setattr(service, "deliver_resume_intents", intents)
    monkeypatch.setattr(service, "deliver_finished_jobs", jobs)
    task = asyncio.create_task(
        service.job_delivery_loop(
            factory, graph, context, interval_seconds=0.001, startup_ready=ready
        )
    )
    try:
        await asyncio.wait_for(second_tick.wait(), 2)
        assert not ready.is_set()
        release_second_tick.set()
        await asyncio.wait_for(ready.wait(), 2)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert calls["recovery"] == (2 if failed_step == "recovery" else 1)
    assert calls["jobs"] >= 2


@pytest.mark.parametrize("interval", [0, -1, float("nan"), float("inf")])
async def test_loop_rejects_invalid_interval_before_recovery(
    monkeypatch: pytest.MonkeyPatch, interval: float
) -> None:
    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(expire_on_commit=False)
    context = GraphContext(sessionmaker=factory, propose_design=AsyncMock())
    recovery = AsyncMock()
    monkeypatch.setattr(service, "recover_pending_runs", recovery)
    with pytest.raises(ValueError, match="interval"):
        await service.job_delivery_loop(
            factory, build_graph(InMemorySaver()), context, interval_seconds=interval
        )
    recovery.assert_not_awaited()
