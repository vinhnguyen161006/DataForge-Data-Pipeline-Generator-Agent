import asyncio
from typing import Literal

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import ApiSettings
from app.db.models import Base

target_metadata = Base.metadata

NameKind = Literal[
    "schema", "table", "column", "index", "unique_constraint", "foreign_key_constraint"
]


def include_name(name: str | None, type_: NameKind, parent_names: object) -> bool:
    """Only manage tables declared in app.db.models.

    The LangGraph checkpointer shares this database and owns its own tables
    through AsyncPostgresSaver.setup(); Alembic must never try to drop them.
    """
    if type_ == "table":
        return name in target_metadata.tables
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=ApiSettings().app_database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        include_name=include_name,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        include_name=include_name,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(ApiSettings().app_database_url)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
