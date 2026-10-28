"""Startup readiness, resource cleanup and unexpected delivery exits through real lifespans."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from psycopg_pool import AsyncConnectionPool
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import main
from app.api.routes import health
from app.core.config import ApiSettings
from app.db.checkpointer import open_postgres_checkpointer
from app.graph.context import GraphContext
from app.services import delivery_lifecycle

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@dataclass
class Runtime:
    settings: ApiSettings
    events: list[str]
    open_checkpointer: main.CheckpointerFactory

    def app(self) -> FastAPI:
        app = FastAPI(lifespan=main.make_lifespan(self.settings, self.open_checkpointer))
        app.include_router(health.router, prefix="/api")
        return app


@pytest.fixture
def runtime(monkeypatch: pytest.MonkeyPatch) -> Runtime:
    events: list[str] = []
    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(expire_on_commit=False)
    engine = AsyncMock()

    async def dispose() -> None:
        events.append("engine_closed")

    @asynccontextmanager
    async def saver(conn_string: str) -> AsyncIterator[InMemorySaver]:
        events.append("saver_opened")
        try:
            yield InMemorySaver()
        finally:
            events.append("saver_closed")

    engine.dispose.side_effect = dispose
    monkeypatch.setattr(main, "make_engine", lambda url: engine)
    monkeypatch.setattr(main, "make_sessionmaker", lambda engine: factory)
    monkeypatch.setattr(main, "make_llm", lambda settings: None)
    monkeypatch.setattr(
        main,
        "make_graph_context",
        lambda factory, llm, budget: GraphContext(sessionmaker=factory, propose_design=AsyncMock()),
    )
    return Runtime(
        ApiSettings(
            _env_file=None,
            job_delivery_enabled=True,
            job_delivery_interval_seconds=0.001,
            job_delivery_startup_timeout_seconds=2,
        ),
        events,
        saver,
    )


async def test_lifespan_waits_for_recovery_before_entering(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    async def loop(*args: Any, **kwargs: Any) -> None:
        started.set()
        try:
            await release.wait()
            kwargs["startup_ready"].set()
            await asyncio.Event().wait()
        finally:
            runtime.events.append("delivery_stopped")

    monkeypatch.setattr(main, "job_delivery_loop", loop)
    app = runtime.app()
    lifespan = app.router.lifespan_context(app)
    startup = asyncio.create_task(lifespan.__aenter__())
    try:
        await asyncio.wait_for(started.wait(), 2)
        assert not startup.done()
        assert not app.state.job_delivery_status.healthy
        release.set()
        await asyncio.wait_for(startup, 2)
        assert app.state.job_delivery_status.healthy
    finally:
        release.set()
        await startup
        await lifespan.__aexit__(None, None, None)
    assert runtime.events == ["saver_opened", "delivery_stopped", "saver_closed", "engine_closed"]


async def test_shutdown_joins_delivery_before_closing_database_resources(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    cleaning = asyncio.Event()
    finish_cleanup = asyncio.Event()

    async def loop(*args: Any, **kwargs: Any) -> None:
        kwargs["startup_ready"].set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await finish_cleanup.wait()
            runtime.events.append("delivery_stopped")

    monkeypatch.setattr(main, "job_delivery_loop", loop)
    app = runtime.app()
    lifespan = app.router.lifespan_context(app)
    await lifespan.__aenter__()
    shutdown = asyncio.create_task(lifespan.__aexit__(None, None, None))
    try:
        await asyncio.wait_for(cleaning.wait(), 2)
        assert not shutdown.done()
        assert runtime.events == ["saver_opened"]
    finally:
        finish_cleanup.set()
        await asyncio.wait_for(shutdown, 2)
    assert runtime.events == ["saver_opened", "delivery_stopped", "saver_closed", "engine_closed"]


async def test_startup_timeout_cancels_delivery_and_closes_resources(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime.settings.job_delivery_startup_timeout_seconds = 0.02

    async def loop(*args: Any, **kwargs: Any) -> None:
        try:
            await asyncio.Event().wait()
        finally:
            runtime.events.append("delivery_stopped")

    monkeypatch.setattr(main, "job_delivery_loop", loop)
    app = runtime.app()
    with pytest.raises(TimeoutError, match="startup"):
        async with app.router.lifespan_context(app):
            pytest.fail("Startup must wait for recovery")
    assert runtime.events == ["saver_opened", "delivery_stopped", "saver_closed", "engine_closed"]


@pytest.mark.parametrize("exit_kind", ["exception", "return", "cancel"])
async def test_loop_exit_before_readiness_fails_startup_and_closes_resources(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch, exit_kind: str
) -> None:
    async def loop(*args: Any, **kwargs: Any) -> None:
        if exit_kind == "exception":
            raise ValueError("Injected delivery failure")
        if exit_kind == "cancel":
            raise asyncio.CancelledError

    monkeypatch.setattr(main, "job_delivery_loop", loop)
    app = runtime.app()
    expected = ValueError if exit_kind == "exception" else RuntimeError
    with pytest.raises(expected):
        async with app.router.lifespan_context(app):
            pytest.fail("Unexpected loop exit must fail startup")
    assert runtime.events == ["saver_opened", "saver_closed", "engine_closed"]


async def test_cancelling_startup_joins_loop_and_closes_resources(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = asyncio.Event()

    async def loop(*args: Any, **kwargs: Any) -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            runtime.events.append("delivery_stopped")

    monkeypatch.setattr(main, "job_delivery_loop", loop)
    app = runtime.app()
    startup = asyncio.create_task(app.router.lifespan_context(app).__aenter__())
    await asyncio.wait_for(started.wait(), 2)
    startup.cancel()
    with pytest.raises(asyncio.CancelledError):
        await startup
    assert runtime.events == ["saver_opened", "delivery_stopped", "saver_closed", "engine_closed"]


@pytest.mark.parametrize("exit_kind", ["exception", "return", "cancel"])
async def test_unexpected_runtime_exit_is_logged_and_health_becomes_unavailable(
    runtime: Runtime,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    exit_kind: str,
) -> None:
    crash = asyncio.Event()
    observed = asyncio.Event()
    original = delivery_lifecycle._delivery_exited

    def report(task: asyncio.Task[None], **kwargs: Any) -> None:
        original(task, **kwargs)
        observed.set()

    async def loop(*args: Any, **kwargs: Any) -> None:
        kwargs["startup_ready"].set()
        await crash.wait()
        if exit_kind == "exception":
            raise RuntimeError("private credentials")
        if exit_kind == "cancel":
            raise asyncio.CancelledError

    monkeypatch.setattr(delivery_lifecycle, "_delivery_exited", report)
    monkeypatch.setattr(main, "job_delivery_loop", loop)
    app = runtime.app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://lifespan.test") as client,
    ):
        assert (await client.get("/api/health")).status_code == 200
        crash.set()
        await asyncio.wait_for(observed.wait(), 2)
        response = await client.get("/api/health")
        assert response.status_code == 503
        assert response.json() == {"status": "unavailable"}
    assert "Job delivery stopped unexpectedly" in caplog.text
    assert "private credentials" not in caplog.text


async def test_disabled_delivery_does_not_start_loop_or_block_readiness(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime.settings.job_delivery_enabled = False
    loop = AsyncMock(side_effect=AssertionError("Delivery is disabled"))
    monkeypatch.setattr(main, "job_delivery_loop", loop)
    app = runtime.app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://lifespan.test") as client,
    ):
        assert (await client.get("/api/health")).status_code == 200
    loop.assert_not_awaited()
    assert runtime.events == ["saver_opened", "saver_closed", "engine_closed"]


@pytest.mark.parametrize(
    "field", ["job_delivery_interval_seconds", "job_delivery_startup_timeout_seconds"]
)
@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf"), -float("inf")])
def test_delivery_timing_rejects_nonpositive_or_nonfinite_values(field: str, value: float) -> None:
    values: dict[str, Any] = {field: value}
    with pytest.raises(ValidationError):
        ApiSettings(_env_file=None, **values)


async def test_checkpoint_pool_is_closed_when_initial_connection_open_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened = AsyncMock(side_effect=RuntimeError("Checkpoint database unavailable"))
    closed = AsyncMock()
    monkeypatch.setattr(AsyncConnectionPool, "open", opened)
    monkeypatch.setattr(AsyncConnectionPool, "close", closed)
    with pytest.raises(RuntimeError, match="unavailable"):
        async with open_postgres_checkpointer("postgresql://localhost/unused_test_database"):
            pytest.fail("Unavailable checkpoint storage must fail startup")
    opened.assert_awaited_once_with(wait=True)
    closed.assert_awaited_once()


async def test_shutdown_cleanup_error_is_logged_and_resources_still_close(
    runtime: Runtime, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    async def loop(*args: Any, **kwargs: Any) -> None:
        kwargs["startup_ready"].set()
        try:
            await asyncio.Event().wait()
        finally:
            raise ValueError("Private shutdown details")

    monkeypatch.setattr(main, "job_delivery_loop", loop)
    app = runtime.app()
    async with app.router.lifespan_context(app):
        assert app.state.job_delivery_status.healthy
    assert app.state.job_delivery_status.failed
    assert runtime.events == ["saver_opened", "saver_closed", "engine_closed"]
    assert "Job delivery failed during shutdown" in caplog.text
    assert "Private shutdown details" not in caplog.text
