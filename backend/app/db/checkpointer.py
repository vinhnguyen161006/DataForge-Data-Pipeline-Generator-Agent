from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import AsyncConnectionPool

from app.core import eventloop
from app.core.config import ApiSettings


@asynccontextmanager
async def open_postgres_checkpointer(conn_string: str) -> AsyncIterator[AsyncPostgresSaver]:
    """Yield a checkpointer backed by a connection pool, closed on exit.

    A pool rather than one connection lets concurrent requests share the saver and recovers
    after Postgres restarts. Opening waits for the first connections so a bad URL fails at
    startup. Tables are not created here; setup_checkpointer runs once per deploy.
    """
    pool = AsyncConnectionPool[AsyncConnection[DictRow]](
        conn_string,
        connection_class=AsyncConnection[DictRow],
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        open=False,
    )
    await pool.open(wait=True)
    try:
        yield AsyncPostgresSaver(pool)
    finally:
        await pool.close()


async def setup_checkpointer(conn_string: str) -> None:
    """Create or migrate the LangGraph checkpoint tables; run once per deploy, not per request."""
    async with AsyncPostgresSaver.from_conn_string(conn_string) as saver:
        await saver.setup()


def main() -> None:
    eventloop.run(setup_checkpointer(ApiSettings().checkpoint_database_url))


if __name__ == "__main__":
    main()
