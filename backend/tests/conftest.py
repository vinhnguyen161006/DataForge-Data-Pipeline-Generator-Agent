import asyncio
import os
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager

import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver

from app.core.config import get_api_settings
from app.main import create_app

TEST_DATABASE_URL_ENV = "DATAFORGE_TEST_DATABASE_URL"


def pytest_asyncio_loop_factories(
    config: pytest.Config, item: pytest.Item
) -> dict[str, Callable[[], asyncio.AbstractEventLoop]]:
    """Run every async test on a selector loop, the one psycopg async needs on Windows."""
    return {"selector": asyncio.SelectorEventLoop}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    if os.environ.get(TEST_DATABASE_URL_ENV):
        return
    skip = pytest.mark.skip(reason=f"{TEST_DATABASE_URL_ENV} is not set")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


@asynccontextmanager
async def open_in_memory_checkpointer(conn_string: str) -> AsyncIterator[InMemorySaver]:
    yield InMemorySaver()


@pytest.fixture
def app() -> Iterator[FastAPI]:
    get_api_settings.cache_clear()
    yield create_app(open_checkpointer=open_in_memory_checkpointer)
    get_api_settings.cache_clear()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with (
        LifespanManager(app) as manager,
        AsyncClient(transport=ASGITransport(app=manager.app), base_url="http://test") as client,
    ):
        yield client


@pytest.fixture
def checkpointer() -> InMemorySaver:
    return InMemorySaver()


@pytest.fixture
def database_url() -> str:
    return os.environ[TEST_DATABASE_URL_ENV]
