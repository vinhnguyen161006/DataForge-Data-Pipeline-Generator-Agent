"""Committed PostgreSQL ownership and READY snapshots through the real profile child."""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.schema import CreateSchema, DropSchema

from app.db.models import (
    Base,
    Batch,
    BatchStatus,
    Job,
    JobQueue,
    JobStatus,
    PipelineRun,
    Project,
    SourceFile,
    User,
)
from app.db.session import make_sessionmaker
from app.jobs import queue
from app.profiler.schemas import DataProfile
from app.services.batches import BatchError
from tests.profile_jobs import make_profile_job
from worker.profile_preparation import prepare_profile_job
from worker.runner import run_profile
from worker.sandbox import Limits

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from app.ingest.storage import Storage
    from worker.profile_protocol import PreparedProfileJob

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(sys.platform != "linux", reason="Linux confined profile child"),
]


@dataclass
class Scenario:
    factory: async_sessionmaker[AsyncSession]
    storage: Storage
    request: PreparedProfileJob

    async def claim(self) -> Job:
        claimed = await queue.claim_next(
            self.factory, queue=JobQueue.SANDBOX, worker_id="profile-test", lease_seconds=120
        )
        assert claimed is not None
        return claimed


@pytest.fixture
async def profile_job(database_engine: AsyncEngine, tmp_path: Path) -> AsyncIterator[Scenario]:
    schema = "profile_" + uuid4().hex
    async with database_engine.begin() as connection:
        await connection.execute(CreateSchema(schema))
    try:
        engine = database_engine.execution_options(schema_translate_map={None: schema})
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = make_sessionmaker(engine)
        storage, request = make_profile_job(tmp_path)
        identity = request.identity
        async with factory.begin() as session:
            actor = User(email=uuid4().hex + "@example.test", password_hash=uuid4().hex)
            session.add(actor)
            await session.flush()
            session.add(
                Project(
                    id=identity.project_id,
                    slug=uuid4().hex,
                    name="Profile fixture",
                    created_by=actor.id,
                )
            )
            await session.flush()
            session.add(
                Batch(
                    id=identity.batch_id,
                    project_id=identity.project_id,
                    status=BatchStatus.READY,
                    required_files=request.manifest.required_files,
                    manifest_sha256=request.payload.manifest_sha256,
                )
            )
            await session.flush()
            session.add_all(
                [
                    SourceFile(
                        id=source.file_id,
                        batch_id=identity.batch_id,
                        filename=source.filename,
                        storage_path=str(
                            storage.raw_path(
                                identity.project_id, identity.batch_id, source.filename
                            )
                        ),
                        sha256=source.sha256,
                        size_bytes=source.size_bytes,
                        read_config=source.read_config.model_dump(mode="json"),
                        read_config_confirmed=True,
                    )
                    for source in request.manifest.files
                ]
            )
            session.add(
                PipelineRun(
                    id=identity.run_id,
                    project_id=identity.project_id,
                    batch_id=identity.batch_id,
                    request_text="Profile fixture inputs",
                )
            )
            await session.flush()
            session.add(
                Job(
                    id=identity.job_id,
                    queue=JobQueue.SANDBOX,
                    kind="profile",
                    payload=request.payload.model_dump(mode="json"),
                    run_id=identity.run_id,
                )
            )
        yield Scenario(factory, storage, request)
    finally:
        async with database_engine.begin() as connection:
            await connection.execute(DropSchema(schema, cascade=True))


async def test_claim_prepare_child_and_complete_preserve_plain_profile_contract(
    profile_job: Scenario,
) -> None:
    job = await profile_job.claim()
    async with profile_job.factory() as session:
        prepared = await prepare_profile_job(
            session,
            profile_job.storage,
            job_id=job.id,
            worker_id="profile-test",
            attempt=job.attempts,
        )
    assert prepared.identity.attempt == 1
    limits = Limits(
        timeout_seconds=20,
        cpu_seconds=10,
        memory_mb=2048,
        max_file_mb=32,
        max_processes=4096,
    )
    result = await asyncio.to_thread(run_profile, prepared, limits, storage=profile_job.storage)
    profile = DataProfile.model_validate(result)
    assert {table.name: table.row_count for table in profile.tables} == {
        "customers": 2,
        "orders": 3,
    }
    await queue.complete(
        profile_job.factory, job.id, result, worker_id="profile-test", attempt=job.attempts
    )
    async with profile_job.factory() as session:
        finished = await session.get(Job, job.id)
        assert finished is not None
        assert finished.status is JobStatus.SUCCEEDED
        assert finished.result == result
        assert "identity" not in result
        assert not finished.delivered


@pytest.mark.parametrize(
    "invalid",
    [
        "queued",
        "worker",
        "attempt",
        "expired",
        "queue",
        "kind",
        "missing_run",
    ],
)
async def test_preparation_requires_live_owned_profile_attempt(
    profile_job: Scenario, invalid: str
) -> None:
    job = await profile_job.claim()
    async with profile_job.factory.begin() as session:
        stored = await session.get(Job, job.id)
        assert stored is not None
        if invalid == "queued":
            stored.status = JobStatus.QUEUED
        elif invalid == "worker":
            stored.locked_by = "other-worker"
        elif invalid == "attempt":
            stored.attempts += 1
        elif invalid == "expired":
            stored.lease_expires_at = datetime.now(UTC) - timedelta(seconds=5)
        elif invalid == "queue":
            stored.queue = JobQueue.PUBLISHER
        elif invalid == "kind":
            stored.kind = "dbt_build"
        else:
            stored.run_id = None
    async with profile_job.factory() as session:
        with pytest.raises(ValueError, match="live"):
            await prepare_profile_job(
                session, profile_job.storage, job_id=job.id, worker_id="profile-test", attempt=1
            )


@pytest.mark.parametrize("invalid", ["batch_status", "marker", "raw", "payload", "config"])
async def test_preparation_rejects_snapshot_drift(profile_job: Scenario, invalid: str) -> None:
    job = await profile_job.claim()
    identity = profile_job.request.identity
    async with profile_job.factory.begin() as session:
        if invalid == "batch_status":
            batch = await session.get(Batch, identity.batch_id)
            assert batch is not None
            batch.status = BatchStatus.UPLOADING
        elif invalid == "config":
            source = await session.scalar(
                select(SourceFile).where(SourceFile.batch_id == identity.batch_id)
            )
            assert source is not None
            source.read_config_confirmed = False
        elif invalid == "payload":
            stored = await session.get(Job, job.id)
            assert stored is not None
            stored.payload = {**stored.payload, "project_id": str(uuid4())}
    if invalid == "marker":
        profile_job.storage.marker_path(identity.project_id, identity.batch_id).unlink()
    elif invalid == "raw":
        profile_job.storage.raw_path(
            identity.project_id, identity.batch_id, "customers.csv"
        ).write_text("changed")
    async with profile_job.factory() as session:
        with pytest.raises((ValueError, BatchError)):
            await prepare_profile_job(
                session, profile_job.storage, job_id=job.id, worker_id="profile-test", attempt=1
            )


@pytest.mark.parametrize("invalid", [False, True])
async def test_legacy_job_is_normalized_only_after_snapshot_verification(
    profile_job: Scenario, invalid: bool
) -> None:
    job = await profile_job.claim()
    request = profile_job.request
    legacy: dict[str, Any] = {
        "batch_id": str(request.identity.batch_id),
        "files": [
            {
                "filename": entry.filename,
                "storage_path": str(
                    profile_job.storage.raw_path(
                        request.identity.project_id, request.identity.batch_id, entry.filename
                    )
                ),
                "read_config": entry.read_config.model_dump(mode="json"),
            }
            for entry in request.manifest.files
        ],
    }
    if invalid:
        legacy["files"][0]["storage_path"] = "/outside.csv"
    async with profile_job.factory.begin() as session:
        stored = await session.get(Job, job.id)
        assert stored is not None
        stored.payload = legacy
    async with profile_job.factory() as session:
        if invalid:
            with pytest.raises(ValueError, match="Legacy"):
                await prepare_profile_job(
                    session,
                    profile_job.storage,
                    job_id=job.id,
                    worker_id="profile-test",
                    attempt=1,
                )
        else:
            prepared = await prepare_profile_job(
                session,
                profile_job.storage,
                job_id=job.id,
                worker_id="profile-test",
                attempt=1,
            )
            assert prepared.payload == request.payload
