import asyncio
import hashlib
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

LOCK_RETRY_SECONDS = 0.05


class RunBusyError(Exception):
    """Another process is advancing this run."""


@asynccontextmanager
async def run_lock(
    factory: async_sessionmaker[AsyncSession], run_id: uuid.UUID, *, wait: bool = True
) -> AsyncIterator[None]:
    """Serialize a run across processes without pooling blocked lock connections."""
    key = int.from_bytes(hashlib.sha256(run_id.bytes).digest()[:8], signed=True)
    while True:
        async with factory() as session:
            try:
                acquired = await session.scalar(
                    text("SELECT pg_try_advisory_lock(:key)"), {"key": key}
                )
            except BaseException:
                await session.invalidate()
                raise
            if acquired:
                try:
                    yield
                finally:
                    try:
                        await session.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
                    except BaseException:
                        await session.invalidate()
                        raise
                return
        if not wait:
            raise RunBusyError("The run is processing another request; refresh its status")
        await asyncio.sleep(LOCK_RETRY_SECONDS)
