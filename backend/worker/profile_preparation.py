"""Resolve live queue ownership and committed batch identity in the parent process."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select

from app.db.models import Job, JobQueue, JobStatus, PipelineRun
from app.ingest.sniff import CsvReadConfig
from app.jobs.profile import ProfileJobPayload
from app.services.batches import assert_batch_ready
from worker.profile_protocol import PreparedProfileJob, ProfileIdentity

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.ingest.manifest import BatchManifest
    from app.ingest.storage import Storage


class LegacyProfileFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str
    storage_path: str
    read_config: CsvReadConfig


class LegacyProfilePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_id: UUID
    files: list[LegacyProfileFile]


def _verified_payload(
    value: dict[str, Any], snapshot: BatchManifest, storage: Storage
) -> ProfileJobPayload:
    if "schema_version" in value:
        return ProfileJobPayload.model_validate(value)
    legacy = LegacyProfilePayload.model_validate(value)
    files = {entry.filename: entry for entry in legacy.files}
    if (
        legacy.batch_id != snapshot.batch_id
        or len(files) != len(legacy.files)
        or set(files) != set(snapshot.required_files)
    ):
        raise ValueError("Legacy profile payload does not match the committed snapshot")
    for source in snapshot.files:
        entry = files[source.filename]
        expected = storage.raw_path(snapshot.project_id, snapshot.batch_id, source.filename)
        if entry.storage_path != str(expected) or entry.read_config != source.read_config:
            raise ValueError("Legacy profile file differs from the committed snapshot")
    return ProfileJobPayload(
        project_id=snapshot.project_id,
        batch_id=snapshot.batch_id,
        manifest_sha256=snapshot.digest(),
    )


async def prepare_profile_job(
    session: AsyncSession,
    storage: Storage,
    *,
    job_id: UUID,
    worker_id: str,
    attempt: int,
) -> PreparedProfileJob:
    """Read authoritative identity without giving credentials to the eventual child."""
    job = await session.scalar(
        select(Job).where(
            Job.id == job_id,
            Job.queue == JobQueue.SANDBOX,
            Job.kind == "profile",
            Job.status == JobStatus.RUNNING,
            Job.locked_by == worker_id,
            Job.attempts == attempt,
            Job.lease_expires_at > func.clock_timestamp(),
        )
    )
    if job is None or job.run_id is None:
        raise ValueError("No live profile job is owned by this worker and attempt")
    run = await session.get(PipelineRun, job.run_id)
    if run is None:
        raise ValueError("Profile job has no pipeline run")
    snapshot = await assert_batch_ready(
        session, storage, project_id=run.project_id, batch_id=run.batch_id
    )
    payload = _verified_payload(job.payload, snapshot, storage)
    return PreparedProfileJob(
        identity=ProfileIdentity(
            project_id=run.project_id,
            batch_id=run.batch_id,
            run_id=run.id,
            job_id=job.id,
            attempt=attempt,
        ),
        payload=payload,
        manifest=snapshot,
    )
