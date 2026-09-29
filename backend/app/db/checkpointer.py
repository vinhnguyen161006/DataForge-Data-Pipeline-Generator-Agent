import asyncio

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.core.config import ApiSettings


async def setup_checkpointer(conn_string: str) -> None:
    """Create or migrate the LangGraph checkpoint tables; run once per deploy, not per request."""
    async with AsyncPostgresSaver.from_conn_string(conn_string) as saver:
        await saver.setup()


def main() -> None:
    asyncio.run(setup_checkpointer(ApiSettings().checkpoint_database_url))


if __name__ == "__main__":
    main()
