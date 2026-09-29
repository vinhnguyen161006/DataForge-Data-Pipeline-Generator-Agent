import uuid
from typing import Any

from fastapi import APIRouter

from app.api.schemas import (
    ClarificationAnswers,
    CodeDecision,
    DesignDecision,
    FileEdit,
    RunCreate,
    RunOut,
)

router = APIRouter(prefix="/projects/{project_id}/runs", tags=["runs"])


@router.post("", response_model=RunOut)
async def create_run(project_id: uuid.UUID, body: RunCreate) -> RunOut:
    """TODO: start a pipeline run for a ready batch; engineer only."""
    raise NotImplementedError


@router.get("/{run_id}", response_model=RunOut)
async def get_run(project_id: uuid.UUID, run_id: uuid.UUID) -> RunOut:
    """TODO: polling endpoint: status, current step and pending interrupt payload."""
    raise NotImplementedError


@router.post("/{run_id}/clarifications", response_model=RunOut)
async def answer_clarifications(
    project_id: uuid.UUID, run_id: uuid.UUID, body: ClarificationAnswers
) -> RunOut:
    """TODO: resume the Modeler with the Engineer's answers."""
    raise NotImplementedError


@router.post("/{run_id}/design-decision", response_model=RunOut)
async def decide_design(project_id: uuid.UUID, run_id: uuid.UUID, body: DesignDecision) -> RunOut:
    """TODO: gate 1: approve (optionally with edits, stored as a new DesignVersion) or return."""
    raise NotImplementedError


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
