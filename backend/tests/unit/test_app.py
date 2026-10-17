from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.main import create_app


async def test_lifespan_exposes_sessionmaker_and_graph(app: FastAPI) -> None:
    async with LifespanManager(app):
        assert isinstance(app.state.sessionmaker, async_sessionmaker)
        assert {"design_gate", "code_gate"} <= set(app.state.graph.nodes)


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
