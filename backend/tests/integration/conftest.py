from __future__ import annotations
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import make_engine, make_sessionmaker

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker


@pytest.fixture
async def database_engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = make_engine(database_url)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def session_factory(
    database_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return make_sessionmaker(database_engine)


@pytest.fixture
async def db_session(
    database_engine: AsyncEngine,
) -> AsyncIterator[AsyncSession]:
    async with database_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            async with AsyncSession(
                bind=connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            ) as session:
                yield session
        finally:
            await transaction.rollback()