import asyncio
import logging
import uuid
from collections.abc import Awaitable
from typing import TYPE_CHECKING, Any

from langgraph.types import Command, StateSnapshot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Job, JobStatus, PipelineRun, RunStatus
from app.graph.builder import PipelineGraph
from app.graph.context import GraphContext
from app.graph.interrupts import WAITING_STATUS, JobOutcome, pending_adapter
from app.graph.state import PipelineState

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig

logger = logging.getLogger(__name__)

TERMINAL_RUN_STATUSES = frozenset({RunStatus.PUBLISHED, RunStatus.FAILED})
TERMINAL_JOB_STATUSES = (JobStatus.SUCCEEDED, JobStatus.FAILED)
DELIVERY_BATCH_SIZE = 50


class RunNotFoundError(LookupError):
    """No pipeline run has the requested id."""


class RunStateConflictError(Exception):
    """The run is not in the status the request expects, e.g. a decision sent twice."""

    def __init__(self, run_id: uuid.UUID, expected: RunStatus, actual: RunStatus):
        self.run_id = run_id
        self.expected = expected
        self.actual = actual
        super().__init__(f"Run {run_id} is {actual.value}, expected {expected.value}")


def thread_config(run_id: uuid.UUID) -> "RunnableConfig":
    return {"configurable": {"thread_id": str(run_id)}}


async def start_run(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    batch_id: uuid.UUID,
    request_text: str,
) -> uuid.UUID:
    """Create a RUNNING PipelineRun and commit; the caller then schedules drive_run.

    The run id is also the LangGraph thread id.
    """
    run = PipelineRun(
        project_id=project_id,
        batch_id=batch_id,
        request_text=request_text,
        status=RunStatus.RUNNING,
    )
    session.add(run)
    await session.commit()
    return run.id


async def resume_run(session: AsyncSession, run_id: uuid.UUID, *, expected: RunStatus) -> None:
    """Claim a waiting run for resumption; the caller then schedules drive_run with
    Command(resume=...).

    Separating the check from execution keeps the HTTP request short while the Modeler
    calls Gemini, and makes a duplicated decision fail instead of resuming twice.
    """
    run = await session.get(PipelineRun, run_id, with_for_update=True)
    if run is None:
        raise RunNotFoundError(f"Run {run_id} does not exist")
    if run.status is not expected:
        raise RunStateConflictError(run_id, expected, run.status)
    run.status = RunStatus.RUNNING
    run.pending = None
    await session.commit()


async def _initial_input(
    factory: async_sessionmaker[AsyncSession], run_id: uuid.UUID
) -> PipelineState:
    async with factory() as session:
        run = await session.get(PipelineRun, run_id)
    if run is None:
        raise RunNotFoundError(f"Run {run_id} does not exist")
    return {
        "run_id": str(run.id),
        "project_id": str(run.project_id),
        "batch_id": str(run.batch_id),
        "request_text": run.request_text,
    }


async def _graph_input(
    factory: async_sessionmaker[AsyncSession],
    graph: PipelineGraph,
    run_id: uuid.UUID,
    command: Command[Any] | None,
) -> PipelineState | Command[Any] | None:
    if command is not None:
        return command
    snapshot = await graph.aget_state(thread_config(run_id))
    if snapshot.values:
        return None
    return await _initial_input(factory, run_id)


async def _mark_failed(
    factory: async_sessionmaker[AsyncSession], run_id: uuid.UUID, error: str
) -> None:
    async with factory.begin() as session:
        run = await session.get(PipelineRun, run_id, with_for_update=True)
        if run is not None:
            run.status = RunStatus.FAILED
            run.pending = None
            run.error = error


async def drive_run(
    factory: async_sessionmaker[AsyncSession],
    graph: PipelineGraph,
    context: GraphContext,
    run_id: uuid.UUID,
    command: Command[Any] | None = None,
) -> None:
    """Advance the graph until its next interrupt or the end, then sync the run row.

    Without a command it starts a new thread or continues an existing one. Any
    exception marks the run FAILED with its message instead of propagating.
    """
    try:
        graph_input = await _graph_input(factory, graph, run_id, command)
        await graph.ainvoke(graph_input, thread_config(run_id), context=context)
    except Exception as exc:
        logger.exception("run %s failed", run_id)
        await _mark_failed(factory, run_id, f"{type(exc).__name__}: {exc}")
        return
    await sync_run(factory, graph, run_id)


def run_view(snapshot: StateSnapshot) -> tuple[RunStatus, str | None, dict[str, Any] | None]:
    for task in snapshot.tasks:
        if task.interrupts:
            pending = pending_adapter.validate_python(task.interrupts[0].value)
            return WAITING_STATUS[pending.kind], task.name, pending.model_dump(mode="json")
    if snapshot.next:
        return RunStatus.RUNNING, snapshot.next[0], None
    if snapshot.values.get("error"):
        return RunStatus.FAILED, None, None
    return RunStatus.PUBLISHED, None, None


async def sync_run(
    factory: async_sessionmaker[AsyncSession], graph: PipelineGraph, run_id: uuid.UUID
) -> RunStatus:
    """Copy the latest checkpoint into PipelineRun: status, current step and pending payload."""
    snapshot = await graph.aget_state(thread_config(run_id))
    status, step, pending = run_view(snapshot)
    async with factory.begin() as session:
        run = await session.get(PipelineRun, run_id, with_for_update=True)
        if run is None:
            raise RunNotFoundError(f"Run {run_id} does not exist")
        run.status = status
        run.current_step = step
        run.pending = pending
        run.error = snapshot.values.get("error")
    return status


async def _finished_undelivered_jobs(factory: async_sessionmaker[AsyncSession]) -> list[Job]:
    async with factory() as session:
        jobs = await session.scalars(
            select(Job)
            .where(
                Job.run_id.is_not(None),
                Job.delivered.is_(False),
                Job.status.in_(TERMINAL_JOB_STATUSES),
            )
            .order_by(Job.finished_at, Job.id)
            .limit(DELIVERY_BATCH_SIZE)
        )
        return list(jobs.all())


async def _claim_waiting_run(factory: async_sessionmaker[AsyncSession], job: Job) -> bool:
    """Move the run from WAITING_JOB to RUNNING when it is waiting for exactly this job."""
    async with factory.begin() as session:
        run = await session.get(PipelineRun, job.run_id, with_for_update=True)
        waiting = (
            run is not None
            and run.status is RunStatus.WAITING_JOB
            and run.pending is not None
            and run.pending.get("job_id") == str(job.id)
        )
        if run is not None and waiting:
            run.status = RunStatus.RUNNING
            run.pending = None
        return waiting


async def _mark_delivered(factory: async_sessionmaker[AsyncSession], job_id: uuid.UUID) -> None:
    async with factory.begin() as session:
        job = await session.get(Job, job_id, with_for_update=True)
        if job is not None:
            job.delivered = True


async def deliver_finished_jobs(
    factory: async_sessionmaker[AsyncSession], graph: PipelineGraph, context: GraphContext
) -> int:
    """Resume every run whose awaited job finished; return how many runs were resumed.

    Claiming the run row first makes concurrent deliverers resume a run once. The job
    is marked delivered only after the run moved on, so a crash in between redelivers;
    a run no longer waiting for that job then simply marks it delivered (FR-21).
    """
    resumed = 0
    for job in await _finished_undelivered_jobs(factory):
        if job.run_id is not None and await _claim_waiting_run(factory, job):
            outcome = JobOutcome(
                job_id=job.id,
                status=job.status,
                result=job.result,
                error=job.last_error,
            )
            await drive_run(
                factory, graph, context, job.run_id, Command(resume=outcome.model_dump(mode="json"))
            )
            resumed += 1
        await _mark_delivered(factory, job.id)
    return resumed


async def recover_pending_runs(
    factory: async_sessionmaker[AsyncSession], graph: PipelineGraph, context: GraphContext
) -> int:
    """On startup, re-sync every unfinished run from its checkpoint and continue the ones that
    stopped between nodes; return how many runs were recovered.

    A run claimed for resumption but never driven goes back to its waiting status, so the
    Engineer's decision or the job delivery can be sent again.
    """
    async with factory() as session:
        run_ids = (
            await session.scalars(
                select(PipelineRun.id).where(PipelineRun.status.not_in(TERMINAL_RUN_STATUSES))
            )
        ).all()
    for run_id in run_ids:
        snapshot = await graph.aget_state(thread_config(run_id))
        unstarted = not snapshot.values
        if unstarted or await sync_run(factory, graph, run_id) is RunStatus.RUNNING:
            await drive_run(factory, graph, context, run_id)
    return len(run_ids)


async def _logged(step: str, work: Awaitable[int]) -> None:
    try:
        count = await work
    except Exception:
        logger.exception("%s failed; retrying on the next tick", step)
        return
    if count:
        logger.info("%s handled %d runs", step, count)


async def job_delivery_loop(
    factory: async_sessionmaker[AsyncSession],
    graph: PipelineGraph,
    context: GraphContext,
    *,
    interval_seconds: float,
) -> None:
    """Recover unfinished runs once, then keep delivering finished jobs until cancelled."""
    await _logged("recover_pending_runs", recover_pending_runs(factory, graph, context))
    while True:
        await _logged("deliver_finished_jobs", deliver_finished_jobs(factory, graph, context))
        await asyncio.sleep(interval_seconds)
