import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Approval,
    ApprovalDecision,
    Batch,
    BatchStatus,
    CodeVersion,
    DesignVersion,
    ExecutionReport,
    Gate,
)
from app.jobs.profile import ProfileJobPayload

PRESENTED_VERSION_PART = "presented_design_version_id"


class DesignNotApprovedError(RuntimeError):
    """Code generation was reached without a gate-1 approval of the current design (FR-06)."""


async def profile_job_payload(session: AsyncSession, batch_id: uuid.UUID) -> dict[str, Any]:
    batch = await session.get(Batch, batch_id)
    if batch is None or batch.status is not BatchStatus.READY or batch.manifest_sha256 is None:
        raise ValueError("Profile jobs require a committed READY snapshot")
    return ProfileJobPayload(
        project_id=batch.project_id,
        batch_id=batch.id,
        manifest_sha256=batch.manifest_sha256,
    ).model_dump(mode="json")


async def add_design_version(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    content: dict[str, Any],
    content_hash: str,
    edited_by_user: bool,
) -> DesignVersion:
    latest: int | None = await session.scalar(
        select(func.max(DesignVersion.version)).where(DesignVersion.run_id == run_id)
    )
    version = DesignVersion(
        run_id=run_id,
        version=(latest or 0) + 1,
        content=content,
        content_hash=content_hash,
        edited_by_user=edited_by_user,
    )
    session.add(version)
    await session.flush()
    return version


async def find_edit_of(
    session: AsyncSession, presented: DesignVersion, content_hash: str
) -> DesignVersion | None:
    """Return the edited version already stored for this decision by an interrupted re-run."""
    return await session.scalar(
        select(DesignVersion).where(
            DesignVersion.run_id == presented.run_id,
            DesignVersion.version > presented.version,
            DesignVersion.edited_by_user.is_(True),
            DesignVersion.content_hash == content_hash,
        )
    )


async def find_decision_on(session: AsyncSession, presented: DesignVersion) -> Approval | None:
    """Each presented design version receives at most one gate-1 decision."""
    return await session.scalar(
        select(Approval).where(
            Approval.run_id == presented.run_id,
            Approval.gate == Gate.DESIGN,
            Approval.fingerprint_parts[PRESENTED_VERSION_PART].as_string() == str(presented.id),
        )
    )


def design_decision(
    *,
    project_id: uuid.UUID,
    presented: DesignVersion,
    decided: DesignVersion,
    approver_id: uuid.UUID,
    decision: ApprovalDecision,
    comment: str | None,
) -> Approval:
    """Gate 1 is the Engineer's own review, so it never counts as an independent review."""
    return Approval(
        project_id=project_id,
        run_id=decided.run_id,
        gate=Gate.DESIGN,
        fingerprint=decided.content_hash,
        fingerprint_parts={
            "design_hash": decided.content_hash,
            "design_version_id": str(decided.id),
            PRESENTED_VERSION_PART: str(presented.id),
        },
        decision=decision,
        approver_id=approver_id,
        independent_review=False,
        comment=comment,
    )


async def next_code_version(session: AsyncSession, run_id: uuid.UUID) -> int:
    latest: int | None = await session.scalar(
        select(func.max(CodeVersion.version)).where(CodeVersion.run_id == run_id)
    )
    return (latest or 0) + 1


async def has_execution_report(session: AsyncSession, job_id: uuid.UUID) -> bool:
    """A delivered build job is recorded once, even when its node re-runs after a crash."""
    found = await session.scalar(select(ExecutionReport.id).where(ExecutionReport.job_id == job_id))
    return found is not None


async def assert_design_approved(session: AsyncSession, design_version_id: uuid.UUID) -> None:
    design = await session.get(DesignVersion, design_version_id)
    approval = (
        None
        if design is None
        else await session.scalar(
            select(Approval).where(
                Approval.run_id == design.run_id,
                Approval.gate == Gate.DESIGN,
                Approval.decision == ApprovalDecision.APPROVED,
                Approval.fingerprint == design.content_hash,
                Approval.fingerprint_parts["design_version_id"].as_string() == str(design.id),
            )
        )
    )
    if approval is None:
        raise DesignNotApprovedError(f"Design version {design_version_id} has no gate-1 approval")
