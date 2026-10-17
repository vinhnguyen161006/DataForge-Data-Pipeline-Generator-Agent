import uuid
from typing import Any

from langgraph.types import Command
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import RunStatus
from app.graph.builder import PipelineGraph
from app.graph.context import GraphContext


class RunStateConflictError(Exception):
    """The run is not in the status the request expects, e.g. a decision sent twice."""

    def __init__(self, run_id: uuid.UUID, expected: RunStatus, actual: RunStatus):
        self.run_id = run_id
        self.expected = expected
        self.actual = actual
        super().__init__(f"Run {run_id} is {actual.value}, expected {expected.value}")


async def start_run(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    batch_id: uuid.UUID,
    request_text: str,
) -> uuid.UUID:
    """TODO: create a RUNNING PipelineRun and commit; the caller then schedules drive_run.

    The run id is also the LangGraph thread id.
    """
    raise NotImplementedError


async def resume_run(session: AsyncSession, run_id: uuid.UUID, *, expected: RunStatus) -> None:
    """TODO: lock the run row, raise RunStateConflictError unless its status is `expected`,
    set it RUNNING and commit; the caller then schedules drive_run with Command(resume=...).

    Separating the check from execution keeps the HTTP request short while the Modeler
    calls Gemini, and makes a duplicated decision fail instead of resuming twice.
    """
    raise NotImplementedError


async def drive_run(
    factory: async_sessionmaker[AsyncSession],
    graph: PipelineGraph,
    context: GraphContext,
    run_id: uuid.UUID,
    command: Command[Any] | None = None,
) -> None:
    """TODO: invoke the graph on thread run_id (initial input when command is None), then
    sync_run; any exception marks the run FAILED with its message.
    """
    raise NotImplementedError


async def sync_run(
    factory: async_sessionmaker[AsyncSession], graph: PipelineGraph, run_id: uuid.UUID
) -> RunStatus:
    """TODO: copy the latest checkpoint into PipelineRun: the pending interrupt payload, its
    WAITING_STATUS and the node name as current_step.
    """
    raise NotImplementedError


async def deliver_finished_jobs(
    factory: async_sessionmaker[AsyncSession], graph: PipelineGraph, context: GraphContext
) -> int:
    """TODO: resume every run whose awaited job finished and is not yet delivered; mark delivered.

    Claim jobs with FOR UPDATE SKIP LOCKED, resume only when the run's pending JobWait has
    the same job_id, using a JobOutcome as resume value. Called periodically from the API
    lifespan; restart-safe because state lives in Postgres (FR-21).
    """
    raise NotImplementedError


async def recover_pending_runs(
    factory: async_sessionmaker[AsyncSession], graph: PipelineGraph, context: GraphContext
) -> int:
    """TODO: on startup, sync_run every non-terminal run and drive RUNNING runs whose
    checkpoint still has nodes to execute and no pending interrupt.
    """
    raise NotImplementedError
