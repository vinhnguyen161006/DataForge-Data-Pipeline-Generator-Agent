import asyncio
import logging
import uuid
from collections.abc import Awaitable
from typing import TYPE_CHECKING, Any

from langgraph.types import Command, StateSnapshot
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Job, JobStatus, PipelineRun, RunResumeIntent, RunStatus
from app.graph.builder import PipelineGraph
from app.graph.context import GraphContext
from app.graph.interrupts import (
    WAITING_STATUS,
    ClarificationReply,
    ClarificationRequest,
    DesignGateReply,
    DesignGateRequest,
    JobOutcome,
    JobWait,
    pending_adapter,
)
from app.graph.state import PipelineState
from app.profiler.schemas import DataProfile
from app.services.run_lock import run_lock

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


class RunDecisionConflictError(Exception):
    """The submitted interrupt or design is no longer current."""


class RunReplyValidationError(ValueError):
    """The reply does not answer the current questions or contains an invalid design."""


def _human_pending(
    snapshot: StateSnapshot,
) -> tuple[str, ClarificationRequest | DesignGateRequest]:
    interrupts = [item for task in snapshot.tasks for item in task.interrupts]
    if len(interrupts) != 1:
        raise RunDecisionConflictError("The run is not waiting for this decision")
    item = interrupts[0]
    pending = pending_adapter.validate_python(item.value)
    if not isinstance(pending, ClarificationRequest | DesignGateRequest):
        raise RunDecisionConflictError("The run is waiting for a worker job")
    return item.id, pending


def _validate_reply(
    pending: ClarificationRequest | DesignGateRequest,
    reply: ClarificationReply | DesignGateReply,
    design_version_id: uuid.UUID | None,
    context: GraphContext,
) -> None:
    if isinstance(pending, ClarificationRequest) and isinstance(reply, ClarificationReply):
        questions = [question.question for question in pending.questions]
        supplied = [answer.question for answer in reply.answers]
        if (
            len(questions) != len(set(questions))
            or len(supplied) != len(set(supplied))
            or set(supplied) != set(questions)
        ):
            raise RunReplyValidationError("Answer each current question exactly once")
        if any(not answer.answer.strip() for answer in reply.answers):
            raise RunReplyValidationError("Answers cannot be blank")
        return
    if isinstance(pending, DesignGateRequest) and isinstance(reply, DesignGateReply):
        if design_version_id != pending.design_version_id:
            raise RunDecisionConflictError("The design version has changed; refresh the run")
        if reply.decision == "approve":
            problems = context.check_design(reply.edited_design or pending.design)
            if problems:
                raise RunReplyValidationError("; ".join(problems))
        return
    raise RunDecisionConflictError("This reply does not match the current gate")


async def resume_run(
    factory: async_sessionmaker[AsyncSession],
    graph: PipelineGraph,
    context: GraphContext,
    run_id: uuid.UUID,
    *,
    project_id: uuid.UUID,
    interrupt_id: str,
    reply: ClarificationReply | DesignGateReply,
    design_version_id: uuid.UUID | None = None,
) -> PipelineRun:
    """Atomically accept one human reply; delivery remains recoverable after HTTP returns."""
    expected = (
        RunStatus.WAITING_CLARIFICATION
        if isinstance(reply, ClarificationReply)
        else RunStatus.WAITING_DESIGN_APPROVAL
    )
    async with run_lock(factory, run_id, wait=False), factory() as session:
        run = await session.scalar(
            select(PipelineRun)
            .where(PipelineRun.id == run_id, PipelineRun.project_id == project_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if run is None:
            raise RunNotFoundError("Run not found in this project")
        if run.status is not expected:
            raise RunStateConflictError(run_id, expected, run.status)
        if run.interrupt_id != interrupt_id:
            raise RunDecisionConflictError("The interrupt has changed; refresh the run")
        existing = await session.scalar(
            select(RunResumeIntent.id).where(
                RunResumeIntent.run_id == run_id,
                RunResumeIntent.interrupt_id == interrupt_id,
            )
        )
        if existing is not None:
            raise RunDecisionConflictError("A decision was already accepted for this interrupt")
        snapshot = await graph.aget_state(thread_config(run_id))
        current_id, pending = _human_pending(snapshot)
        if current_id != interrupt_id:
            raise RunDecisionConflictError("The interrupt has changed; refresh the run")
        _validate_reply(pending, reply, design_version_id, context)
        session.add(
            RunResumeIntent(
                run_id=run_id,
                interrupt_id=interrupt_id,
                actor_id=reply.user_id,
                kind=pending.kind,
                payload=reply.model_dump(mode="json"),
            )
        )
        run.status = RunStatus.RUNNING
        run.pending = None
        run.interrupt_id = None
        run.error = None
        await session.flush()
        await session.refresh(run)
        await session.commit()
        return run


async def _deliver_resume_intent_locked(
    factory: async_sessionmaker[AsyncSession],
    graph: PipelineGraph,
    context: GraphContext,
    intent_id: uuid.UUID,
) -> bool:
    async with factory() as session:
        intent = await session.get(RunResumeIntent, intent_id)
    if intent is None or intent.delivered:
        return False
    reply = (
        ClarificationReply.model_validate(intent.payload)
        if intent.kind == "clarification"
        else DesignGateReply.model_validate(intent.payload)
    )
    if reply.user_id != intent.actor_id:
        raise RunReplyValidationError("Stored reply actor does not match its receipt")
    snapshot = await graph.aget_state(thread_config(intent.run_id))
    if not snapshot.values:
        raise RuntimeError("The checkpoint for an accepted reply is unavailable")
    interrupt_ids = {item.id for task in snapshot.tasks for item in task.interrupts}
    if intent.interrupt_id in interrupt_ids:
        command: Command[Any] = Command(resume={intent.interrupt_id: reply.model_dump(mode="json")})
        await _drive_run(factory, graph, context, intent.run_id, command)
    elif snapshot.next and not interrupt_ids:
        await _drive_run(factory, graph, context, intent.run_id)
    else:
        await sync_run(factory, graph, intent.run_id)
    await _mark_resume_delivered(factory, intent_id)
    return True


async def _mark_resume_delivered(
    factory: async_sessionmaker[AsyncSession], intent_id: uuid.UUID
) -> None:
    async with factory.begin() as session:
        stored = await session.get(RunResumeIntent, intent_id, with_for_update=True)
        if stored is not None:
            stored.delivered = True


async def deliver_resume_intents(
    factory: async_sessionmaker[AsyncSession],
    graph: PipelineGraph,
    context: GraphContext,
    run_id: uuid.UUID | None = None,
) -> int:
    """Drain committed human replies without sending an old reply into a later interrupt."""
    query = select(RunResumeIntent.id, RunResumeIntent.run_id).where(
        RunResumeIntent.delivered.is_(False)
    )
    if run_id is not None:
        query = query.where(RunResumeIntent.run_id == run_id)
    async with factory() as session:
        intents = (
            await session.execute(
                query.order_by(RunResumeIntent.created_at, RunResumeIntent.id).limit(
                    DELIVERY_BATCH_SIZE
                )
            )
        ).all()
    delivered = 0
    for intent_id, run_id in intents:
        async with run_lock(factory, run_id):
            delivered += await _deliver_resume_intent_locked(factory, graph, context, intent_id)
    return delivered


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
            run.interrupt_id = None
            run.error = error


async def drive_run(
    factory: async_sessionmaker[AsyncSession],
    graph: PipelineGraph,
    context: GraphContext,
    run_id: uuid.UUID,
    command: Command[Any] | None = None,
) -> None:
    """Serialize graph execution with human replies, recovery and job delivery."""
    async with run_lock(factory, run_id):
        await _drive_run(factory, graph, context, run_id, command)


async def _drive_run(
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
        run.interrupt_id = next(
            (item.id for task in snapshot.tasks for item in task.interrupts), None
        )
        run.error = snapshot.values.get("error")
    return status


async def _finished_undelivered_jobs(
    factory: async_sessionmaker[AsyncSession], *, after_id: uuid.UUID | None = None
) -> list[Job]:
    query = select(Job).where(
        Job.run_id.is_not(None),
        Job.delivered.is_(False),
        Job.status.in_(TERMINAL_JOB_STATUSES),
    )
    if after_id is not None:
        query = query.where(Job.id > after_id)
    async with factory() as session:
        jobs = await session.scalars(query.order_by(Job.id).limit(DELIVERY_BATCH_SIZE))
        return list(jobs.all())


async def _mark_job_resuming(factory: async_sessionmaker[AsyncSession], run_id: uuid.UUID) -> None:
    """Project a checkpoint-authorized resume while holding the shared run lock."""
    async with factory.begin() as session:
        run = await session.get(PipelineRun, run_id, with_for_update=True)
        if run is None:
            raise RunNotFoundError(f"Run {run_id} does not exist")
        run.status = RunStatus.RUNNING
        run.pending = None
        run.interrupt_id = None


async def _mark_delivered(factory: async_sessionmaker[AsyncSession], job_id: uuid.UUID) -> None:
    async with factory.begin() as session:
        job = await session.get(Job, job_id, with_for_update=True)
        if job is not None:
            job.delivered = True


def _job_consumed(snapshot: StateSnapshot, job: Job) -> bool:
    if str(job.id) in snapshot.values.get("consumed_job_ids", []):
        return True
    return (
        "consumed_job_ids" not in snapshot.values
        and job.kind == "profile"
        and job.idempotency_key == f"profile:{job.run_id}"
        and bool(snapshot.values.get("profile"))
    )


async def _deliver_job_locked(
    factory: async_sessionmaker[AsyncSession],
    graph: PipelineGraph,
    context: GraphContext,
    job_id: uuid.UUID,
) -> bool:
    async with factory() as session:
        job = await session.get(Job, job_id)
    if (
        job is None
        or job.delivered
        or job.run_id is None
        or job.status not in TERMINAL_JOB_STATUSES
    ):
        return False
    snapshot = await graph.aget_state(thread_config(job.run_id))
    if not snapshot.values or snapshot.values.get("run_id") != str(job.run_id):
        return False
    interrupts = [item for task in snapshot.tasks for item in task.interrupts]
    advanced = False
    if snapshot.next and not interrupts:
        await _drive_run(factory, graph, context, job.run_id)
        advanced = True
        snapshot = await graph.aget_state(thread_config(job.run_id))
        interrupts = [item for task in snapshot.tasks for item in task.interrupts]
    if _job_consumed(snapshot, job):
        if not advanced:
            await sync_run(factory, graph, job.run_id)
        await _mark_delivered(factory, job.id)
        return False
    if len(interrupts) != 1:
        return False
    pending = pending_adapter.validate_python(interrupts[0].value)
    if not isinstance(pending, JobWait) or pending.job_id != job.id or pending.job_kind != job.kind:
        return False
    outcome = JobOutcome(job_id=job.id, status=job.status, result=job.result, error=job.last_error)
    if job.kind == "profile" and job.status is JobStatus.SUCCEEDED:
        outcome.result = DataProfile.model_validate(job.result).model_dump(mode="json")
    await _mark_job_resuming(factory, job.run_id)
    await _drive_run(
        factory,
        graph,
        context,
        job.run_id,
        Command(resume={interrupts[0].id: outcome.model_dump(mode="json")}),
    )
    snapshot = await graph.aget_state(thread_config(job.run_id))
    if not _job_consumed(snapshot, job):
        return False
    await _mark_delivered(factory, job.id)
    return True


async def deliver_finished_jobs(
    factory: async_sessionmaker[AsyncSession], graph: PipelineGraph, context: GraphContext
) -> int:
    """Deliver only to the matching checkpoint interrupt and acknowledge durable consumption."""
    resumed = 0
    after_id = None
    while jobs := await _finished_undelivered_jobs(factory, after_id=after_id):
        for job in jobs:
            if job.run_id is None:
                continue
            async with run_lock(factory, job.run_id):
                try:
                    resumed += await _deliver_job_locked(factory, graph, context, job.id)
                except ValidationError:
                    logger.error(
                        "Job delivery rejected an invalid payload",
                        extra={"job_id": str(job.id), "run_id": str(job.run_id)},
                    )
        after_id = jobs[-1].id
        if len(jobs) < DELIVERY_BATCH_SIZE:
            break
    return resumed


async def recover_pending_runs(
    factory: async_sessionmaker[AsyncSession], graph: PipelineGraph, context: GraphContext
) -> int:
    """Deliver accepted replies, then restore unfinished projections from checkpoints."""
    await deliver_resume_intents(factory, graph, context)
    async with factory() as session:
        run_ids = (
            await session.scalars(
                select(PipelineRun.id).where(PipelineRun.status.not_in(TERMINAL_RUN_STATUSES))
            )
        ).all()
    for run_id in run_ids:
        async with run_lock(factory, run_id):
            async with factory() as session:
                pending_intents = list(
                    await session.scalars(
                        select(RunResumeIntent.id).where(
                            RunResumeIntent.run_id == run_id,
                            RunResumeIntent.delivered.is_(False),
                        )
                    )
                )
            for intent_id in pending_intents:
                await _deliver_resume_intent_locked(factory, graph, context, intent_id)
            snapshot = await graph.aget_state(thread_config(run_id))
            unstarted = not snapshot.values
            if unstarted or await sync_run(factory, graph, run_id) is RunStatus.RUNNING:
                await _drive_run(factory, graph, context, run_id)
    return len(run_ids)


async def _logged(step: str, work: Awaitable[int]) -> bool:
    try:
        count = await work
    except Exception:
        logger.exception("%s failed; retrying on the next tick", step)
        return False
    if count:
        logger.info("%s handled %d runs", step, count)
    return True


async def job_delivery_loop(
    factory: async_sessionmaker[AsyncSession],
    graph: PipelineGraph,
    context: GraphContext,
    *,
    interval_seconds: float,
) -> None:
    """Retry startup recovery until successful, then deliver results until cancelled."""
    recovered = False
    while True:
        if not recovered:
            recovered = await _logged(
                "recover_pending_runs", recover_pending_runs(factory, graph, context)
            )
        await _logged("deliver_resume_intents", deliver_resume_intents(factory, graph, context))
        await _logged("deliver_finished_jobs", deliver_finished_jobs(factory, graph, context))
        await asyncio.sleep(interval_seconds)
