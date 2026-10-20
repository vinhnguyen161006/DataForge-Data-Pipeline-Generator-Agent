from fastapi import HTTPException
from pydantic import ValidationError

from app.api.schemas import RunOut
from app.db.models import PipelineRun, RunStatus
from app.graph.interrupts import WAITING_STATUS, pending_adapter

PUBLIC_STEPS = frozenset(
    {
        "profile",
        "modeler",
        "clarify",
        "design_gate",
        "codegen",
        "execute",
        "optimize",
        "code_gate",
        "publish",
        "dashboard",
    }
)


def _public_pending(run: PipelineRun) -> dict[str, object] | None:
    if run.status not in WAITING_STATUS.values():
        return None

    try:
        pending = pending_adapter.validate_python(run.pending)
    except ValidationError as exc:
        raise HTTPException(
            status_code=500,
            detail="Run state is unavailable",
        ) from exc

    if WAITING_STATUS[pending.kind] != run.status:
        raise HTTPException(
            status_code=500,
            detail="Run state is unavailable",
        )

    return pending.model_dump(mode="json")


def run_out(run: PipelineRun) -> RunOut:
    """Present persisted run state without exposing internal exception details."""
    return RunOut(
        id=run.id,
        status=run.status,
        current_step=(run.current_step if run.current_step in PUBLIC_STEPS else None),
        pending=_public_pending(run),
        error=(
            "The run failed. Use the run ID when reporting this issue."
            if run.status == RunStatus.FAILED
            else None
        ),
        updated_at=run.updated_at,
    )
