import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import async_sessionmaker

from app import main
from app.core.config import get_api_settings
from app.graph.context import GraphContext
from app.main import create_app


async def test_lifespan_exposes_sessionmaker_and_graph(app: FastAPI) -> None:
    async with LifespanManager(app):
        assert isinstance(app.state.sessionmaker, async_sessionmaker)
        assert {"design_gate", "code_gate"} <= set(app.state.graph.nodes)
        assert isinstance(app.state.graph_context, GraphContext)
        assert app.state.graph_context.sessionmaker is app.state.sessionmaker


async def test_lifespan_closes_checkpointer_on_shutdown() -> None:
    events: list[str] = []

    @asynccontextmanager
    async def tracking_checkpointer(conn_string: str) -> AsyncIterator[InMemorySaver]:
        events.append("opened")
        yield InMemorySaver()
        events.append("closed")

    async with LifespanManager(create_app(open_checkpointer=tracking_checkpointer)):
        assert events == ["opened"]
    assert events == ["opened", "closed"]


async def test_lifespan_runs_job_delivery_until_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
    started = asyncio.Event()
    cancelled: list[bool] = []

    async def fake_loop(*args: Any, **kwargs: Any) -> None:
        started.set()
        kwargs["startup_ready"].set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(True)
            raise

    monkeypatch.setenv("DATAFORGE_JOB_DELIVERY_ENABLED", "true")
    monkeypatch.setattr(main, "job_delivery_loop", fake_loop)
    get_api_settings.cache_clear()

    async with LifespanManager(create_app(open_checkpointer=in_memory_checkpointer)):
        await asyncio.wait_for(started.wait(), timeout=1)
    assert cancelled == [True]


@asynccontextmanager
async def in_memory_checkpointer(conn_string: str) -> AsyncIterator[InMemorySaver]:
    yield InMemorySaver()
