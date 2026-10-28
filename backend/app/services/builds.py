import uuid

from sqlalchemy import String, cast, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import BuildAttemptOut
from app.db.models import CodeVersion, ExecutionReport, Job
from app.graph.nodes import BUILD_JOB_KEY_PREFIX
from app.jobs.reports import ExecutionReportData


async def build_attempts(session: AsyncSession, run_id: uuid.UUID) -> list[BuildAttemptOut]:
    """List every code version of a run, oldest first, with its build job and report.

    Job errors stay internal; only the dbt report, which describes the generated
    code, is returned to the Engineer.
    """
    job_key = literal(BUILD_JOB_KEY_PREFIX) + cast(CodeVersion.id, String)
    rows = await session.execute(
        select(CodeVersion, Job, ExecutionReport)
        .outerjoin(Job, Job.idempotency_key == job_key)
        .outerjoin(ExecutionReport, ExecutionReport.job_id == Job.id)
        .where(CodeVersion.run_id == run_id)
        .order_by(CodeVersion.version)
    )
    return [
        BuildAttemptOut(
            code_version_id=code.id,
            version=code.version,
            origin=code.origin,
            generated_at=code.created_at,
            job_status=job.status if job else None,
            queued_at=job.created_at if job else None,
            finished_at=job.finished_at if job else None,
            report=ExecutionReportData.model_validate(report.report) if report else None,
        )
        for code, job, report in rows
    ]
