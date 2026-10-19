"""Real batch API checks using committed PostgreSQL sessions and isolated storage."""

from __future__ import annotations

import asyncio
import hashlib
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.routes import auth, batches, projects
from app.core.config import get_api_settings
from app.core.security import create_access_token, hash_password
from app.db.models import Batch, BatchStatus, Project, ProjectMember, ProjectRole, SourceFile, User
from app.ingest.sniff import CsvReadConfig
from app.ingest.storage import Storage
from app.services import batches as service

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable

    from app.ingest.manifest import BatchManifest

pytestmark = pytest.mark.integration
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "upload"


@dataclass
class BatchScenario:
    client: AsyncClient
    factory: async_sessionmaker[AsyncSession]
    storage: Storage
    project_id: UUID
    other_project_id: UUID
    headers: dict[str, dict[str, str]]

    def path(self, batch_id: UUID, project_id: UUID | None = None) -> str:
        return f"/api/projects/{project_id or self.project_id}/batches/{batch_id}"

    async def create(self, names: list[str] | None = None, *, other: bool = False) -> UUID:
        project = self.other_project_id if other else self.project_id
        actor = "reviewer" if other else "engineer"
        result = await self.client.post(
            f"/api/projects/{project}/batches",
            headers=self.headers[actor],
            json={
                "required_files": names if names is not None else ["customers.csv", "orders.csv"]
            },
        )
        assert result.status_code == 200, result.text
        assert result.json()["status"] == "uploading"
        return UUID(result.json()["id"])

    async def upload(
        self, batch_id: UUID, filename: str, *, case: str = "complete", content: bytes | None = None
    ) -> Response:
        payload = content if content is not None else (FIXTURES / case / filename).read_bytes()
        return await self.client.post(
            self.path(batch_id) + "/files",
            headers=self.headers["engineer"],
            files={"file": (filename, payload, "text/csv")},
        )

    async def confirm(
        self, batch_id: UUID, file_id: UUID, config: dict[str, Any] | None = None
    ) -> Response:
        return await self.client.put(
            self.path(batch_id) + f"/files/{file_id}/read-config",
            headers=self.headers["engineer"],
            json={
                "read_config": config
                or CsvReadConfig(null_tokens=["", "NA"]).model_dump(mode="json")
            },
        )

    async def ready(self, batch_id: UUID) -> Response:
        return await self.client.post(
            self.path(batch_id) + "/ready", headers=self.headers["engineer"]
        )

    async def row(self, batch_id: UUID) -> Batch:
        async with self.factory() as observer:
            batch = await observer.get(Batch, batch_id)
        assert batch is not None
        return batch

    async def files(self, batch_id: UUID) -> list[SourceFile]:
        async with self.factory() as observer:
            return list(
                await observer.scalars(select(SourceFile).where(SourceFile.batch_id == batch_id))
            )

    async def populated(self, *, confirmed: bool = True) -> tuple[UUID, list[UUID]]:
        batch_id = await self.create()
        ids = []
        for name in ("customers.csv", "orders.csv"):
            result = await self.upload(batch_id, name)
            assert result.status_code == 200, result.text
            file_id = UUID(result.json()["id"])
            ids.append(file_id)
            if confirmed:
                result = await self.confirm(batch_id, file_id)
                assert result.status_code == 200, result.text
        return batch_id, ids

    async def snapshot(self, batch_id: UUID) -> BatchManifest:
        async with self.factory() as observer:
            return await service.assert_batch_ready(
                observer, self.storage, project_id=self.project_id, batch_id=batch_id
            )


@pytest.fixture(scope="module")
def batch_password_hash() -> str:
    return hash_password(secrets.token_urlsafe(24))


@pytest.fixture
async def scenario(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    batch_password_hash: str,
) -> AsyncIterator[BatchScenario]:
    secret = secrets.token_urlsafe(48)
    monkeypatch.setenv("DATAFORGE_JWT_SECRET", secret)
    monkeypatch.setenv("DATAFORGE_STORAGE_ROOT", str(tmp_path / "storage"))
    get_api_settings.cache_clear()
    users = [uuid4() for _ in range(3)]
    project_ids = [uuid4(), uuid4()]
    app = FastAPI()
    app.state.sessionmaker = session_factory
    for router in (auth.router, projects.router, batches.router):
        app.include_router(router, prefix="/api")
    try:
        async with session_factory.begin() as session:
            session.add_all(
                [
                    User(
                        id=user,
                        email=f"batch-{user}@example.test",
                        password_hash=batch_password_hash,
                    )
                    for user in users
                ]
            )
            await session.flush()
            session.add_all(
                [
                    Project(
                        id=project_ids[index],
                        name="Batch Project",
                        slug=f"batch-{project_ids[index].hex}",
                        created_by=users[index],
                    )
                    for index in range(2)
                ]
            )
            await session.flush()
            session.add_all(
                [
                    ProjectMember(
                        project_id=project_ids[0], user_id=users[0], role=ProjectRole.ENGINEER
                    ),
                    ProjectMember(
                        project_id=project_ids[0], user_id=users[1], role=ProjectRole.REVIEWER
                    ),
                    ProjectMember(
                        project_id=project_ids[1], user_id=users[1], role=ProjectRole.ENGINEER
                    ),
                ]
            )
        headers = {
            label: {"Authorization": f"Bearer {create_access_token(user, secret, 10)}"}
            for label, user in zip(("engineer", "reviewer", "outsider"), users, strict=True)
        }
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://batch.test",
        ) as client:
            yield BatchScenario(
                client,
                session_factory,
                Storage(tmp_path / "storage"),
                project_ids[0],
                project_ids[1],
                headers,
            )
    finally:
        async with session_factory.begin() as cleanup:
            batch_ids = select(Batch.id).where(Batch.project_id.in_(project_ids))
            await cleanup.execute(delete(SourceFile).where(SourceFile.batch_id.in_(batch_ids)))
            await cleanup.execute(delete(Batch).where(Batch.project_id.in_(project_ids)))
            await cleanup.execute(
                delete(ProjectMember).where(ProjectMember.project_id.in_(project_ids))
            )
            await cleanup.execute(delete(Project).where(Project.id.in_(project_ids)))
            await cleanup.execute(delete(User).where(User.id.in_(users)))
        get_api_settings.cache_clear()


async def test_complete_batch_publishes_verified_snapshot(scenario: BatchScenario) -> None:
    batch_id, _ = await scenario.populated()
    result = await scenario.ready(batch_id)
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "ready"
    snapshot = await scenario.snapshot(batch_id)
    row = await scenario.row(batch_id)
    content = scenario.storage.manifest_path(scenario.project_id, batch_id).read_bytes()
    assert row.manifest_sha256 == hashlib.sha256(content).hexdigest() == snapshot.digest()
    assert snapshot.required_files == ["customers.csv", "orders.csv"]
    for entry in snapshot.files:
        raw = scenario.storage.raw_path(scenario.project_id, batch_id, entry.filename)
        assert raw.read_bytes() == (FIXTURES / "complete" / entry.filename).read_bytes()
        assert entry.read_config_confirmed is True
    assert not list(scenario.storage.root.rglob("*.part"))


@pytest.mark.parametrize("state", ["empty", "missing", "unconfirmed", "partially_confirmed"])
async def test_ready_requires_every_file_and_confirmation(
    scenario: BatchScenario, state: str
) -> None:
    batch_id = await scenario.create()
    if state != "empty":
        first = await scenario.upload(batch_id, "customers.csv", case="missing")
        assert first.status_code == 200
        if state in ("missing", "partially_confirmed"):
            assert (await scenario.confirm(batch_id, UUID(first.json()["id"]))).status_code == 200
    if state in ("unconfirmed", "partially_confirmed"):
        assert (await scenario.upload(batch_id, "orders.csv")).status_code == 200
    assert (await scenario.ready(batch_id)).status_code == 409
    assert (await scenario.row(batch_id)).status is BatchStatus.UPLOADING
    assert not scenario.storage.marker_path(scenario.project_id, batch_id).exists()


@pytest.mark.parametrize(
    "names",
    [
        [],
        ["customers.csv", "customers.csv"],
        ["Customers.csv", "customers.csv"],
        ["../customers.csv"],
        ["nested/customers.csv"],
        ["nested\\customers.csv"],
        ["C:customers.csv"],
        ["CON.csv"],
        [" customers.csv"],
        ["customers.csv "],
        ["bad\x00.csv"],
        [".csv"],
        ["customers.txt"],
    ],
)
async def test_create_rejects_invalid_declarations(
    scenario: BatchScenario, names: list[str]
) -> None:
    result = await scenario.client.post(
        f"/api/projects/{scenario.project_id}/batches",
        headers=scenario.headers["engineer"],
        json={"required_files": names},
    )
    assert result.status_code == 422
    async with scenario.factory() as observer:
        assert (
            await observer.scalar(
                select(func.count())
                .select_from(Batch)
                .where(Batch.project_id == scenario.project_id)
            )
            == 0
        )
    assert not scenario.storage.root.exists()


@pytest.mark.parametrize(
    ("actor", "expected"), [("reviewer", 403), ("outsider", 403), ("missing", 401)]
)
@pytest.mark.parametrize("operation", ["create", "upload", "confirm", "ready"])
async def test_mutations_require_project_engineer(
    scenario: BatchScenario, actor: str, expected: int, operation: str
) -> None:
    batch_id = await scenario.create()
    uploaded = await scenario.upload(batch_id, "customers.csv")
    file_id = uploaded.json()["id"]
    headers = scenario.headers.get(actor, {})
    path = scenario.path(batch_id)
    if operation == "create":
        result = await scenario.client.post(
            f"/api/projects/{scenario.project_id}/batches",
            headers=headers,
            json={"required_files": ["customers.csv"]},
        )
    elif operation == "upload":
        result = await scenario.client.post(
            path + "/files",
            headers=headers,
            files={"file": ("orders.csv", b"order_id\n1\n", "text/csv")},
        )
    elif operation == "confirm":
        result = await scenario.client.put(
            path + f"/files/{file_id}/read-config",
            headers=headers,
            json={"read_config": {"delimiter": ","}},
        )
    else:
        result = await scenario.client.post(path + "/ready", headers=headers)
    assert result.status_code == expected
    assert len(await scenario.files(batch_id)) == 1
    assert (await scenario.row(batch_id)).status is BatchStatus.UPLOADING


async def test_cross_project_batch_and_cross_batch_file_are_rejected(
    scenario: BatchScenario,
) -> None:
    other = await scenario.create(other=True)
    assert (await scenario.upload(other, "customers.csv")).status_code == 404
    assert (await scenario.ready(other)).status_code == 404
    first, ids = await scenario.populated()
    second = await scenario.create()
    assert (await scenario.confirm(second, ids[0])).status_code == 404
    assert len(await scenario.files(first)) == 2
    assert await scenario.files(second) == []


@pytest.mark.parametrize("filename", ["notes.csv", "../orders.csv", "nested\\orders.csv"])
async def test_upload_rejects_undeclared_or_unsafe_names(
    scenario: BatchScenario, filename: str
) -> None:
    batch_id = await scenario.create()
    result = await scenario.upload(batch_id, filename, content=b"id\n1\n")
    assert result.status_code == 422
    assert await scenario.files(batch_id) == []
    assert not scenario.storage.root.exists()


async def test_duplicate_upload_never_overwrites_raw(scenario: BatchScenario) -> None:
    batch_id = await scenario.create()
    assert (await scenario.upload(batch_id, "customers.csv")).status_code == 200
    original = (FIXTURES / "complete/customers.csv").read_bytes()
    assert (
        await scenario.upload(batch_id, "customers.csv", content=b"replacement\nwrong\n")
    ).status_code == 409
    raw = scenario.storage.raw_path(scenario.project_id, batch_id, "customers.csv")
    assert raw.read_bytes() == original
    sources = await scenario.files(batch_id)
    assert len(sources) == 1
    assert sources[0].sha256 == hashlib.sha256(original).hexdigest()
    assert not sources[0].read_config_confirmed


async def test_submitted_config_controls_preview_without_changing_raw(
    scenario: BatchScenario,
) -> None:
    batch_id = await scenario.create()
    result = await scenario.upload(batch_id, "customers.csv")
    file_id = UUID(result.json()["id"])
    raw = scenario.storage.raw_path(scenario.project_id, batch_id, "customers.csv")
    content = raw.read_bytes()
    result = await scenario.confirm(batch_id, file_id, {"null_tokens": [""]})
    assert result.status_code == 200, result.text
    assert result.json()["preview"][1][2] == "NA"
    result = await scenario.confirm(batch_id, file_id, {"null_tokens": ["", "NA"]})
    assert result.status_code == 200
    assert result.json()["preview"][1] == ["002", "Binh", None]
    assert raw.read_bytes() == content
    saved = (await scenario.files(batch_id))[0]
    assert saved.read_config["null_tokens"] == ["", "NA"]
    assert saved.read_config_confirmed
    assert saved.sha256 == hashlib.sha256(content).hexdigest()


async def test_confirm_reads_semicolon_configuration(scenario: BatchScenario) -> None:
    batch_id = await scenario.create()
    result = await scenario.upload(batch_id, "orders.csv", case="semicolon")
    assert result.status_code == 200
    file_id = UUID(result.json()["id"])
    wrong = await scenario.confirm(batch_id, file_id, {"delimiter": ","})
    assert wrong.status_code == 200
    assert len(wrong.json()["columns"]) == 1
    correct = await scenario.confirm(batch_id, file_id, {"delimiter": ";"})
    assert correct.status_code == 200
    assert correct.json()["columns"] == ["order_id", "customer_id", "amount"]


@pytest.mark.parametrize("confirmed", [False, True])
@pytest.mark.parametrize(
    "config",
    [
        {"delimiter": ";;"},
        {"skip_rows": -1},
        {"encoding": "not-an-encoding"},
        {"encoding": "utf-16"},
        {"skip_rows": 100},
        {"quote": "xx"},
        {"storage_path": "/etc/passwd"},
    ],
)
async def test_invalid_config_preserves_previous_state(
    scenario: BatchScenario, confirmed: bool, config: dict[str, Any]
) -> None:
    batch_id = await scenario.create()
    result = await scenario.upload(batch_id, "customers.csv")
    file_id = UUID(result.json()["id"])
    if confirmed:
        assert (await scenario.confirm(batch_id, file_id)).status_code == 200
    before = (await scenario.files(batch_id))[0]
    result = await scenario.confirm(batch_id, file_id, config)
    assert result.status_code == 422, result.text
    after = (await scenario.files(batch_id))[0]
    assert after.read_config == before.read_config
    assert after.read_config_confirmed is confirmed
    assert after.sha256 == before.sha256


async def test_ready_is_idempotent_and_blocks_further_mutation(scenario: BatchScenario) -> None:
    batch_id, ids = await scenario.populated()
    assert (await scenario.ready(batch_id)).status_code == 200
    snapshot = await scenario.snapshot(batch_id)
    first = scenario.storage.manifest_path(scenario.project_id, batch_id).read_bytes()
    assert (await scenario.ready(batch_id)).status_code == 200
    assert scenario.storage.manifest_path(scenario.project_id, batch_id).read_bytes() == first
    assert (await scenario.snapshot(batch_id)).digest() == snapshot.digest()
    assert (await scenario.upload(batch_id, "customers.csv")).status_code == 409
    assert (await scenario.confirm(batch_id, ids[0], {"null_tokens": [""]})).status_code == 409
    assert len(await scenario.files(batch_id)) == 2


async def test_consumer_rejects_uploading_batch(scenario: BatchScenario) -> None:
    batch_id, _ = await scenario.populated()
    with pytest.raises(service.BatchError, match="not ready"):
        await scenario.snapshot(batch_id)


@pytest.mark.parametrize(
    "damage",
    [
        "manifest_missing",
        "manifest_invalid",
        "marker_missing",
        "marker_invalid",
        "raw_missing",
        "raw_changed",
        "metadata_changed",
        "extra_file",
        "unfinished_file",
    ],
)
async def test_consumer_fails_closed_for_damaged_snapshot(
    scenario: BatchScenario, damage: str
) -> None:
    batch_id, _ = await scenario.populated()
    assert (await scenario.ready(batch_id)).status_code == 200
    raw = scenario.storage.raw_path(scenario.project_id, batch_id, "customers.csv")
    manifest = scenario.storage.manifest_path(scenario.project_id, batch_id)
    marker = scenario.storage.marker_path(scenario.project_id, batch_id)
    if damage == "manifest_missing":
        manifest.unlink()
    elif damage == "manifest_invalid":
        manifest.write_bytes(b"{broken")
    elif damage == "marker_missing":
        marker.unlink()
    elif damage == "marker_invalid":
        marker.write_text("0" * 64 + "\n")
    elif damage == "raw_missing":
        raw.unlink()
    elif damage == "raw_changed":
        raw.write_bytes(raw.read_bytes() + b"x")
    elif damage == "metadata_changed":
        async with scenario.factory.begin() as session:
            source = await session.scalar(select(SourceFile).where(SourceFile.batch_id == batch_id))
            assert source is not None
            source.read_config = CsvReadConfig(null_tokens=[""]).model_dump(mode="json")
    else:
        (raw.parent / ("extra.csv" if damage == "extra_file" else ".upload.part")).write_bytes(b"x")
    with pytest.raises(service.BatchError):
        await scenario.snapshot(batch_id)


async def test_ready_rejects_raw_path_outside_batch(
    scenario: BatchScenario, tmp_path: Path
) -> None:
    batch_id, ids = await scenario.populated()
    outside = tmp_path / "outside.csv"
    outside.write_bytes(b"unrelated")
    async with scenario.factory.begin() as session:
        source = await session.get(SourceFile, ids[0])
        assert source is not None
        source.storage_path = str(outside)
    assert (await scenario.ready(batch_id)).status_code == 409
    assert outside.read_bytes() == b"unrelated"
    assert (await scenario.row(batch_id)).status is BatchStatus.UPLOADING


async def test_ready_rejects_raw_symlink(scenario: BatchScenario, tmp_path: Path) -> None:
    batch_id, _ = await scenario.populated()
    raw = scenario.storage.raw_path(scenario.project_id, batch_id, "customers.csv")
    target = tmp_path / "external.csv"
    target.write_bytes(raw.read_bytes())
    raw.unlink()
    raw.symlink_to(target)
    assert (await scenario.ready(batch_id)).status_code == 409
    assert (await scenario.row(batch_id)).status is BatchStatus.UPLOADING


@pytest.mark.parametrize("after_commit", [False, True])
async def test_upload_commit_failure_preserves_raw_and_safe_retry(
    scenario: BatchScenario, monkeypatch: pytest.MonkeyPatch, after_commit: bool
) -> None:
    batch_id = await scenario.create()
    original = AsyncSession.commit

    async def fail_commit(session: AsyncSession) -> None:
        if after_commit:
            await original(session)
        raise RuntimeError("Injected commit failure")

    with monkeypatch.context() as patcher:
        patcher.setattr(AsyncSession, "commit", fail_commit)
        result = await scenario.upload(batch_id, "customers.csv")
    assert result.status_code == 500
    raw = scenario.storage.raw_path(scenario.project_id, batch_id, "customers.csv")
    assert raw.read_bytes() == (FIXTURES / "complete/customers.csv").read_bytes()
    result = await scenario.upload(batch_id, "customers.csv")
    assert result.status_code == (409 if after_commit else 200), result.text
    assert len(await scenario.files(batch_id)) == 1
    assert not list(raw.parent.glob("*.part"))


async def test_orphan_retry_with_different_bytes_is_rejected(
    scenario: BatchScenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    batch_id = await scenario.create()

    def fail_sniff(path: Path) -> Any:
        raise ValueError("Injected sniff failure")

    with monkeypatch.context() as patcher:
        patcher.setattr(service, "sniff_csv", fail_sniff)
        result = await scenario.upload(batch_id, "customers.csv")
    assert result.status_code == 422
    assert await scenario.files(batch_id) == []
    raw = scenario.storage.raw_path(scenario.project_id, batch_id, "customers.csv")
    original = raw.read_bytes()
    assert (await scenario.upload(batch_id, "customers.csv", content=b"id\n9\n")).status_code == 409
    assert raw.read_bytes() == original
    assert (await scenario.upload(batch_id, "customers.csv")).status_code == 200


async def test_upload_byte_limit_leaves_no_partial_file(
    scenario: BatchScenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    batch_id = await scenario.create()
    monkeypatch.setenv("DATAFORGE_MAX_UPLOAD_BYTES", "8")
    get_api_settings.cache_clear()
    assert (await scenario.upload(batch_id, "customers.csv")).status_code == 413
    assert await scenario.files(batch_id) == []
    assert not list(scenario.storage.root.rglob("*.part"))
    assert not scenario.storage.raw_path(scenario.project_id, batch_id, "customers.csv").exists()


@pytest.mark.parametrize("stage", ["manifest", "marker"])
async def test_ready_retries_filesystem_failure_without_changing_snapshot(
    scenario: BatchScenario, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    batch_id, _ = await scenario.populated()

    def fail_write(*args: Any, **kwargs: Any) -> None:
        raise OSError("Injected storage failure")

    with monkeypatch.context() as patcher:
        patcher.setattr(
            Storage, "write_manifest" if stage == "manifest" else "mark_ready", fail_write
        )
        result = await scenario.ready(batch_id)
    assert result.status_code == 503
    before = await scenario.row(batch_id)
    assert before.status is (BatchStatus.UPLOADING if stage == "manifest" else BatchStatus.READY)
    assert not scenario.storage.marker_path(scenario.project_id, batch_id).exists()
    with pytest.raises(service.BatchError):
        await scenario.snapshot(batch_id)
    assert (await scenario.ready(batch_id)).status_code == 200
    after = await scenario.row(batch_id)
    if stage == "marker":
        assert after.manifest_sha256 == before.manifest_sha256
    await scenario.snapshot(batch_id)


async def test_failed_ready_commit_does_not_publish_marker(
    scenario: BatchScenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    batch_id, _ = await scenario.populated()

    async def fail_commit(session: AsyncSession) -> None:
        raise RuntimeError("Injected database commit failure")

    with monkeypatch.context() as patcher:
        patcher.setattr(AsyncSession, "commit", fail_commit)
        result = await scenario.ready(batch_id)
    assert result.status_code == 500
    assert (await scenario.row(batch_id)).status is BatchStatus.UPLOADING
    assert scenario.storage.manifest_path(scenario.project_id, batch_id).exists()
    assert not scenario.storage.marker_path(scenario.project_id, batch_id).exists()
    assert (await scenario.ready(batch_id)).status_code == 200


async def test_corrupt_published_manifest_is_not_silently_replaced(scenario: BatchScenario) -> None:
    batch_id, _ = await scenario.populated()
    assert (await scenario.ready(batch_id)).status_code == 200
    before = (await scenario.row(batch_id)).manifest_sha256
    manifest = scenario.storage.manifest_path(scenario.project_id, batch_id)
    manifest.write_bytes(b"corrupted")
    assert (await scenario.ready(batch_id)).status_code == 409
    assert manifest.read_bytes() == b"corrupted"
    assert (await scenario.row(batch_id)).manifest_sha256 == before


async def test_database_enforces_unique_filename_per_batch(scenario: BatchScenario) -> None:
    batch_id, _ = await scenario.populated()
    source = (await scenario.files(batch_id))[0]
    with pytest.raises(IntegrityError):
        async with scenario.factory.begin() as session:
            session.add(
                SourceFile(
                    batch_id=batch_id,
                    filename=source.filename,
                    storage_path=source.storage_path,
                    sha256=source.sha256,
                    size_bytes=source.size_bytes,
                    read_config=source.read_config,
                    read_config_confirmed=False,
                )
            )


async def wait_for_waiters(
    factory: async_sessionmaker[AsyncSession], blocker_pid: int, count: int
) -> None:
    async def observe() -> None:
        while True:
            async with factory() as observer:
                actual = await observer.scalar(
                    text(
                        "WITH RECURSIVE waiting(pid) AS ("
                        "SELECT pid FROM pg_stat_activity WHERE datname=current_database() "
                        "AND :pid = ANY(pg_blocking_pids(pid)) UNION "
                        "SELECT activity.pid FROM pg_stat_activity AS activity JOIN waiting "
                        "ON waiting.pid = ANY(pg_blocking_pids(activity.pid)) "
                        "WHERE activity.datname=current_database()) SELECT count(*) FROM waiting"
                    ),
                    {"pid": blocker_pid},
                )
            if actual == count:
                return
            await asyncio.sleep(0.01)

    await asyncio.wait_for(observe(), timeout=10)


async def race_under_batch_lock(
    scenario: BatchScenario, batch_id: UUID, operations: list[Awaitable[Response]]
) -> list[Response]:
    tasks = []
    async with scenario.factory() as blocker:
        await blocker.execute(select(Batch).where(Batch.id == batch_id).with_for_update())
        pid = await blocker.scalar(text("SELECT pg_backend_pid()"))
        assert isinstance(pid, int)
        try:
            tasks = [asyncio.ensure_future(operation) for operation in operations]
            await wait_for_waiters(scenario.factory, pid, len(tasks))
            await blocker.commit()
            return list(await asyncio.wait_for(asyncio.gather(*tasks), timeout=15))
        finally:
            await blocker.rollback()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


async def test_concurrent_duplicate_upload_creates_one_source_file(scenario: BatchScenario) -> None:
    batch_id = await scenario.create()
    results = await race_under_batch_lock(
        scenario,
        batch_id,
        [scenario.upload(batch_id, "customers.csv"), scenario.upload(batch_id, "customers.csv")],
    )
    assert sorted(result.status_code for result in results) == [200, 409]
    assert len(await scenario.files(batch_id)) == 1
    raw = scenario.storage.raw_path(scenario.project_id, batch_id, "customers.csv")
    assert raw.read_bytes() == (FIXTURES / "complete/customers.csv").read_bytes()


async def test_upload_racing_ready_cannot_skip_confirmation(scenario: BatchScenario) -> None:
    batch_id = await scenario.create()
    first = await scenario.upload(batch_id, "customers.csv")
    assert (await scenario.confirm(batch_id, UUID(first.json()["id"]))).status_code == 200
    results = await race_under_batch_lock(
        scenario, batch_id, [scenario.upload(batch_id, "orders.csv"), scenario.ready(batch_id)]
    )
    assert [result.status_code for result in results] == [200, 409]
    assert (await scenario.row(batch_id)).status is BatchStatus.UPLOADING
    assert not scenario.storage.marker_path(scenario.project_id, batch_id).exists()


async def test_two_ready_requests_publish_one_snapshot(scenario: BatchScenario) -> None:
    batch_id, _ = await scenario.populated()
    results = await race_under_batch_lock(
        scenario, batch_id, [scenario.ready(batch_id), scenario.ready(batch_id)]
    )
    assert [result.status_code for result in results] == [200, 200]
    assert (await scenario.row(batch_id)).manifest_sha256 == (
        await scenario.snapshot(batch_id)
    ).digest()


async def test_ready_waits_for_confirmed_configuration(
    scenario: BatchScenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    batch_id, ids = await scenario.populated(confirmed=False)
    assert (await scenario.confirm(batch_id, ids[0])).status_code == 200
    locked = asyncio.Event()
    release = asyncio.Event()
    holder: list[int] = []
    original = service._locked_batch

    async def pause_confirm(session: AsyncSession, project: UUID, batch: UUID) -> Batch:
        result = await original(session, project, batch)
        task = asyncio.current_task()
        if task is not None and task.get_name() == "confirm-request":
            pid = await session.scalar(text("SELECT pg_backend_pid()"))
            assert isinstance(pid, int)
            holder.append(pid)
            locked.set()
            await release.wait()
        return result

    monkeypatch.setattr(service, "_locked_batch", pause_confirm)
    confirming = asyncio.create_task(
        scenario.confirm(batch_id, ids[1], {"null_tokens": [""]}), name="confirm-request"
    )
    pending: list[asyncio.Task[Response]] = [confirming]
    try:
        await asyncio.wait_for(locked.wait(), timeout=10)
        pending.append(asyncio.create_task(scenario.ready(batch_id)))
        await wait_for_waiters(scenario.factory, holder[0], 1)
        release.set()
        results = await asyncio.wait_for(asyncio.gather(*pending), timeout=15)
        assert [result.status_code for result in results] == [200, 200]
        snapshot = await scenario.snapshot(batch_id)
        orders = next(file for file in snapshot.files if file.filename == "orders.csv")
        assert orders.read_config.null_tokens == [""]
    finally:
        release.set()
        for task in pending:
            if not task.done():
                task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)


@pytest.mark.skipif(
    not os.environ.get("DATAFORGE_OULAD_RAW_DIR"), reason="OULAD raw directory is opt-in"
)
async def test_oulad_seven_file_batch_round_trip(
    scenario: BatchScenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = Path(os.environ["DATAFORGE_OULAD_RAW_DIR"])
    names = [
        "assessments.csv",
        "courses.csv",
        "studentAssessment.csv",
        "studentInfo.csv",
        "studentRegistration.csv",
        "studentVle.csv",
        "vle.csv",
    ]
    with TemporaryDirectory(prefix="oulad-batch-", dir=scenario.storage.root.parent) as workspace:
        monkeypatch.setenv("DATAFORGE_STORAGE_ROOT", workspace)
        get_api_settings.cache_clear()
        scenario.storage = Storage(Path(workspace))
        batch_id = await scenario.create(names)
        originals = {}
        for name in names:
            source = raw / name
            assert source.is_file(), f"Missing declared OULAD file: {name}"
            with source.open("rb") as stream:
                originals[name] = hashlib.file_digest(stream, "sha256").hexdigest()
            with source.open("rb") as stream:
                response = await scenario.client.post(
                    scenario.path(batch_id) + "/files",
                    headers=scenario.headers["engineer"],
                    files={"file": (name, stream, "text/csv")},
                )
            assert response.status_code == 200, response.text
            assert response.json()["sha256"] == originals[name]
            assert response.json()["size_bytes"] == source.stat().st_size
            assert response.json()["read_config_confirmed"] is False
            confirmed = await scenario.confirm(
                batch_id, UUID(response.json()["id"]), response.json()["read_config"]
            )
            assert confirmed.status_code == 200, confirmed.text
        response = await scenario.ready(batch_id)
        assert response.status_code == 200, response.text
        snapshot = await scenario.snapshot(batch_id)
        assert len(snapshot.files) == 7
        assert {entry.filename: entry.sha256 for entry in snapshot.files} == originals
        for name in names:
            with (raw / name).open("rb") as stream:
                assert hashlib.file_digest(stream, "sha256").hexdigest() == originals[name]


async def test_ready_rejects_a_legacy_batch_without_a_declaration(scenario: BatchScenario) -> None:
    async with scenario.factory.begin() as session:
        batch = Batch(project_id=scenario.project_id)
        session.add(batch)
        await session.flush()
        batch_id = batch.id
    result = await scenario.ready(batch_id)
    assert result.status_code == 409
    assert (await scenario.row(batch_id)).required_files is None
    assert not scenario.storage.marker_path(scenario.project_id, batch_id).exists()


async def test_ready_rejects_wrong_names_even_when_file_count_matches(
    scenario: BatchScenario,
) -> None:
    batch_id, ids = await scenario.populated()
    async with scenario.factory.begin() as session:
        source = await session.get(SourceFile, ids[0])
        assert source is not None
        source.filename = "notes.csv"
    assert len(await scenario.files(batch_id)) == 2
    assert (await scenario.ready(batch_id)).status_code == 409
    assert (await scenario.row(batch_id)).status is BatchStatus.UPLOADING
    assert not scenario.storage.marker_path(scenario.project_id, batch_id).exists()


async def test_raw_storage_failure_does_not_create_metadata(
    scenario: BatchScenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    batch_id = await scenario.create()

    def fail_save(*args: Any, **kwargs: Any) -> None:
        raise OSError("Injected raw storage failure")

    monkeypatch.setattr(Storage, "save_raw", fail_save)
    assert (await scenario.upload(batch_id, "customers.csv")).status_code == 503
    assert await scenario.files(batch_id) == []
    assert not scenario.storage.raw_path(scenario.project_id, batch_id, "customers.csv").exists()


async def test_ready_retry_rejects_a_corrupt_marker(scenario: BatchScenario) -> None:
    batch_id, _ = await scenario.populated()
    assert (await scenario.ready(batch_id)).status_code == 200
    original_hash = (await scenario.row(batch_id)).manifest_sha256
    marker = scenario.storage.marker_path(scenario.project_id, batch_id)
    marker.write_bytes(b"wrong snapshot")
    assert (await scenario.ready(batch_id)).status_code == 409
    assert marker.read_bytes() == b"wrong snapshot"
    assert (await scenario.row(batch_id)).manifest_sha256 == original_hash


async def test_failure_after_marker_publish_can_be_retried(
    scenario: BatchScenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    batch_id, _ = await scenario.populated()
    original = Storage.mark_ready

    def fail_after_publish(storage: Storage, project: UUID, batch: UUID, digest: str) -> None:
        original(storage, project, batch, digest)
        raise OSError("Injected failure after publishing")

    with monkeypatch.context() as patcher:
        patcher.setattr(Storage, "mark_ready", fail_after_publish)
        assert (await scenario.ready(batch_id)).status_code == 503
    snapshot = await scenario.snapshot(batch_id)
    assert (await scenario.ready(batch_id)).status_code == 200
    assert (await scenario.snapshot(batch_id)).digest() == snapshot.digest()
