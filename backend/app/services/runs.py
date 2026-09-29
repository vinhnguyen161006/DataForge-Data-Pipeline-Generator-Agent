import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.graph.builder import PipelineGraph


async def start_run(
    session: AsyncSession,
    graph: PipelineGraph,
    *,
    project_id: uuid.UUID,
    batch_id: uuid.UUID,
    request_text: str,
) -> uuid.UUID:
    """TODO: create a PipelineRun and start the graph with thread_id = run id."""
    raise NotImplementedError


async def resume_run(graph: PipelineGraph, run_id: uuid.UUID, value: dict[str, Any]) -> None:
    """TODO: resume the interrupted thread with Command(resume=value) and refresh run status."""
    raise NotImplementedError


async def deliver_finished_jobs(
    factory: async_sessionmaker[AsyncSession], graph: PipelineGraph
) -> int:
    """TODO: resume every run whose awaited job finished and is not yet delivered; mark delivered.

    Called periodically from the API lifespan; restart-safe because state lives in Postgres (FR-21).
    """
    raise NotImplementedError


async def recover_pending_runs(
    factory: async_sessionmaker[AsyncSession], graph: PipelineGraph
) -> int:
    """TODO: on startup, re-sync PipelineRun.status/pending from the latest checkpoint of each
    thread.
    """
    raise NotImplementedError
