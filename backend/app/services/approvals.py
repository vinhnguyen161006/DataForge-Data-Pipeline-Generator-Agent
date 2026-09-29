import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Approval, ApprovalDecision, Gate
from app.versioning import VersionParts


async def current_version_parts(session: AsyncSession, run_id: uuid.UUID) -> VersionParts:
    """TODO: build VersionParts from the latest design, code version, batch, execution job and
    report.
    """
    raise NotImplementedError


async def record_approval(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    gate: Gate,
    approver_id: uuid.UUID,
    decision: ApprovalDecision,
    comment: str | None,
) -> Approval:
    """TODO: check the approver holds the right role, apply team/solo rules, snapshot the
    fingerprint.
    """
    raise NotImplementedError


async def assert_publishable(session: AsyncSession, run_id: uuid.UUID) -> Approval:
    """TODO: latest gate-2 approval must be APPROVED and match current_version_parts, else
    StaleApprovalError.
    """
    raise NotImplementedError
