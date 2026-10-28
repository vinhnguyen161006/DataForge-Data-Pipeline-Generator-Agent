import uuid
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import select

from app.api.deps import SessionDep, require_project_member, require_role
from app.api.run_views import run_out
from app.api.schemas import (
    ClarificationAnswers,
    CodeDecision,
    DesignDecision,
    FileEdit,
    RunBuildsOut,
    RunCreate,
    RunOut,
)
from app.core.config import get_api_settings
from app.db.models import Batch, PipelineRun, ProjectRole, User
from app.graph.interrupts import ClarificationAnswer, ClarificationReply, DesignGateReply
from app.ingest.storage import Storage
from app.services import batches as batch_service
from app.services import builds as build_service
from app.services import runs as run_service
from app.services.run_lock import RunBusyError

router = APIRouter(prefix="/projects/{project_id}/runs", tags=["runs"])

EngineerDep = Annotated[User, Depends(require_role(ProjectRole.ENGINEER))]
ProjectMemberDep = Annotated[User, Depends(require_project_member)]


@router.post("", response_model=RunOut)
async def create_run(
    project_id: uuid.UUID,
    body: RunCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    _engineer: EngineerDep,
    session: SessionDep,
) -> RunOut:
    """Commit a run for a verified snapshot before scheduling graph execution."""
    storage = Storage(get_api_settings().storage_root)
    try:
        await batch_service.assert_batch_ready(
            session, storage, project_id=project_id, batch_id=body.batch_id
        )
        factory = request.app.state.sessionmaker
        graph = request.app.state.graph
        context = request.app.state.graph_context
        run_id = await run_service.start_run(
            session,
            project_id=project_id,
            batch_id=body.batch_id,
            request_text=body.request_text,
        )
        run = await _get_project_run(session, project_id, run_id)
        response = run_out(run)

    except batch_service.BatchError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except Exception:
        await session.rollback()
        raise
    background_tasks.add_task(run_service.drive_run, factory, graph, context, run_id)
    return response


@router.get("/{run_id}", response_model=RunOut)
async def get_run(
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    _member: ProjectMemberDep,
    session: SessionDep,
) -> RunOut:
    """Read persisted run status without advancing the workflow."""
    run = await _get_project_run(session, project_id, run_id)
    return run_out(run)


@router.get("/{run_id}/builds", response_model=RunBuildsOut)
async def get_builds(
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    _member: ProjectMemberDep,
    session: SessionDep,
) -> RunBuildsOut:
    """Every generated code version with its sandbox metrics and test results (FR-11)."""
    await _get_project_run(session, project_id, run_id)
    return RunBuildsOut(attempts=await build_service.build_attempts(session, run_id))


@router.post("/{run_id}/clarifications", response_model=RunOut)
async def answer_clarifications(
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    body: ClarificationAnswers,
    engineer: EngineerDep,
    session: SessionDep,
    request: Request,
    background_tasks: BackgroundTasks,
) -> RunOut:
    """Accept answers to the current questions and durably schedule their delivery."""
    await _get_project_run(session, project_id, run_id)
    reply = ClarificationReply(
        user_id=engineer.id,
        answers=[
            ClarificationAnswer(question=item.question, answer=item.answer) for item in body.answers
        ],
    )
    return await _accept_human_reply(
        request, background_tasks, project_id, run_id, body.interrupt_id, reply
    )


@router.post("/{run_id}/design-decision", response_model=RunOut)
async def decide_design(
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    body: DesignDecision,
    engineer: EngineerDep,
    session: SessionDep,
    request: Request,
    background_tasks: BackgroundTasks,
) -> RunOut:
    """Accept one Engineer decision for the exact design currently under review."""
    await _get_project_run(session, project_id, run_id)
    reply = DesignGateReply(
        user_id=engineer.id,
        decision=body.decision,
        edited_design=body.edited_design,
        comment=body.comment,
    )
    return await _accept_human_reply(
        request,
        background_tasks,
        project_id,
        run_id,
        body.interrupt_id,
        reply,
        body.design_version_id,
    )


async def _accept_human_reply(
    request: Request,
    background_tasks: BackgroundTasks,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    interrupt_id: str,
    reply: ClarificationReply | DesignGateReply,
    design_version_id: uuid.UUID | None = None,
) -> RunOut:
    factory = request.app.state.sessionmaker
    graph = request.app.state.graph
    context = request.app.state.graph_context
    try:
        run = await run_service.resume_run(
            factory,
            graph,
            context,
            run_id,
            project_id=project_id,
            interrupt_id=interrupt_id,
            reply=reply,
            design_version_id=design_version_id,
        )
    except run_service.RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Run not found in this project") from exc
    except (
        RunBusyError,
        run_service.RunDecisionConflictError,
        run_service.RunStateConflictError,
    ) as exc:
        raise HTTPException(
            status_code=409, detail="The run has changed or is busy; refresh its status"
        ) from exc
    except run_service.RunReplyValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    response = run_out(run)
    background_tasks.add_task(run_service.deliver_resume_intents, factory, graph, context, run_id)
    return response


@router.get("/{run_id}/code")
async def get_code(project_id: uuid.UUID, run_id: uuid.UUID) -> dict[str, Any]:
    """TODO: files of the current code version plus diff against the previous version."""
    raise NotImplementedError


@router.put("/{run_id}/code", response_model=RunOut)
async def edit_code(project_id: uuid.UUID, run_id: uuid.UUID, body: list[FileEdit]) -> RunOut:
    """TODO: user edit creates a new CodeVersion, invalidates approvals and re-runs checks."""
    raise NotImplementedError


@router.get("/{run_id}/evidence")
async def get_evidence(project_id: uuid.UUID, run_id: uuid.UUID) -> dict[str, Any]:
    """TODO: test results, perf comparison, rewrite log, dashboard config and current
    fingerprint.
    """
    raise NotImplementedError


@router.post("/{run_id}/code-decision", response_model=RunOut)
async def decide_code(project_id: uuid.UUID, run_id: uuid.UUID, body: CodeDecision) -> RunOut:
    """TODO: gate 2: reviewer only; reject when body.fingerprint differs from the current one."""
    raise NotImplementedError


@router.post("/{run_id}/dashboard/retry", response_model=RunOut)
async def retry_dashboard(project_id: uuid.UUID, run_id: uuid.UUID) -> RunOut:
    """TODO: re-run only the Metabase step using stored card/dashboard ids."""
    raise NotImplementedError


async def _get_project_batch(
    session: SessionDep,
    project_id: uuid.UUID,
    batch_id: uuid.UUID,
) -> Batch:
    batch = await session.scalar(
        select(Batch).where(
            Batch.id == batch_id,
            Batch.project_id == project_id,
        )
    )

    if batch is None:
        raise HTTPException(
            status_code=404,
            detail="Batch not found in this project",
        )

    return batch


async def _get_project_run(
    session: SessionDep,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
) -> PipelineRun:
    run = await session.scalar(
        select(PipelineRun).where(
            PipelineRun.id == run_id,
            PipelineRun.project_id == project_id,
        )
    )

    if run is None:
        raise HTTPException(
            status_code=404,
            detail="Run not found in this project",
        )

    return run
