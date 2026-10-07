import pytest
from sqlalchemy.engine import make_url

from app.db.checkpointer import open_postgres_checkpointer

pytestmark = pytest.mark.integration


async def test_postgres_checkpointer_reads_through_the_pool(database_url: str) -> None:
    conn_string = make_url(database_url).set(drivername="postgresql").render_as_string(False)
    async with open_postgres_checkpointer(conn_string) as checkpointer:
        missing = await checkpointer.aget_tuple({"configurable": {"thread_id": "no-such-run"}})
    assert missing is None
