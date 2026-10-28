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


async def test_app_uses_explicit_graph_and_context_builders_without_changing_defaults() -> None:
    from unittest.mock import AsyncMock

    from langgraph.checkpoint.base import BaseCheckpointSaver
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.agents.llm import StructuredLLM
    from app.graph.builder import PipelineGraph
    from scripts.recovery_app import build_graph

    calls: list[str] = []

    def graph_builder(saver: BaseCheckpointSaver[str]) -> PipelineGraph:
        calls.append("graph")
        return build_graph(saver)

    def context_builder(
        factory: async_sessionmaker[AsyncSession], llm: StructuredLLM
    ) -> GraphContext:
        calls.append("context")
        return GraphContext(sessionmaker=factory, propose_design=AsyncMock())

    injected = create_app(
        open_checkpointer=in_memory_checkpointer,
        graph_builder=graph_builder,
        context_builder=context_builder,
    )
    async with LifespanManager(injected):
        assert calls == ["graph", "context"]
        assert "code_gate" not in injected.state.graph.nodes
        assert injected.state.graph_context.sessionmaker is injected.state.sessionmaker
    ordinary = create_app(open_checkpointer=in_memory_checkpointer)
    async with LifespanManager(ordinary):
        assert "code_gate" in ordinary.state.graph.nodes
    assert calls == ["graph", "context"]
