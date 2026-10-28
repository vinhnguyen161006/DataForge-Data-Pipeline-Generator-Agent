"""Batch ingestion and two-phase readiness publication.

PostgreSQL owns the declaration. A manifest is prepared under the batch row lock,
READY and its digest are committed by the caller, and the matching marker is
published last. Raw bytes left by a failed database commit can only be adopted
by a retry carrying identical bytes; final raw files are never blindly deleted.
"""

import csv
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO, ParamSpec, TypeVar

import duckdb
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.api.schemas import BatchOut, SourceFileOut
from app.db.models import Batch, BatchStatus, SourceFile
from app.ingest.filenames import csv_filename, required_filenames
from app.ingest.manifest import BatchManifest, BatchManifestFile
from app.ingest.snapshot import verify_snapshot
from app.ingest.sniff import CsvReadConfig, SniffResult, read_csv_preview, sniff_csv
from app.ingest.storage import Storage, UploadTooLargeError, file_digest, stream_digest

P = ParamSpec("P")
T = TypeVar("T")


class BatchError(Exception):
    def __init__(self, message: str, status_code: int = 409):
        self.status_code = status_code
        super().__init__(message)


async def _disk_call(function: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
    try:
        return await run_in_threadpool(function, *args, **kwargs)
    except UploadTooLargeError as exc:
        raise BatchError(str(exc), 413) from exc
    except FileExistsError as exc:
        raise BatchError("The raw filename is already present") from exc
    except OSError as exc:
        raise BatchError("Batch storage is unavailable; retry the operation", 503) from exc
    except (ValueError, LookupError, csv.Error, duckdb.Error) as exc:
        raise BatchError("The batch input or stored snapshot is invalid") from exc


async def _get_batch(
    session: AsyncSession, project_id: uuid.UUID, batch_id: uuid.UUID, *, lock: bool
) -> Batch:
    statement = select(Batch).where(Batch.id == batch_id, Batch.project_id == project_id)
    if lock:
        statement = statement.with_for_update()
    batch = await session.scalar(statement.execution_options(populate_existing=True))
    if batch is None:
        raise BatchError("Batch not found in this project", 404)
    return batch


async def _locked_batch(session: AsyncSession, project_id: uuid.UUID, batch_id: uuid.UUID) -> Batch:
    return await _get_batch(session, project_id, batch_id, lock=True)


async def _files(session: AsyncSession, batch_id: uuid.UUID) -> list[SourceFile]:
    return list(
        await session.scalars(
            select(SourceFile).where(SourceFile.batch_id == batch_id).order_by(SourceFile.filename)
        )
    )


def _uploading(batch: Batch, storage: Storage) -> list[str]:
    if batch.status is not BatchStatus.UPLOADING:
        raise BatchError("A ready batch cannot be changed; create a new batch")
    if storage.marker_path(batch.project_id, batch.id).exists():
        raise BatchError("An uploading batch has a readiness marker and requires reconciliation")
    try:
        return required_filenames(batch.required_files or [])
    except ValueError as exc:
        raise BatchError("This batch needs an explicit required-file declaration") from exc


def _raw_path(storage: Storage, batch: Batch, source: SourceFile) -> Path:
    expected = storage.raw_path(batch.project_id, batch.id, csv_filename(source.filename))
    stored = storage.checked_path(Path(source.storage_path))
    if stored.resolve() != expected.resolve() or stored.is_symlink():
        raise ValueError("Source metadata does not identify its own batch raw file")
    if not stored.is_file():
        raise ValueError("The stored raw file is missing")
    return stored


async def _source_out(
    storage: Storage, batch: Batch, source: SourceFile, preview: SniffResult | None = None
) -> SourceFileOut:
    if preview is None:
        path = _raw_path(storage, batch, source)
        preview = await _disk_call(
            read_csv_preview, path, CsvReadConfig.model_validate(source.read_config)
        )
    return SourceFileOut(
        id=source.id,
        filename=source.filename,
        sha256=source.sha256,
        size_bytes=source.size_bytes,
        read_config=preview.config,
        read_config_confirmed=source.read_config_confirmed,
        columns=preview.columns,
        preview=preview.preview,
        warnings=preview.warnings,
    )


async def batch_out(session: AsyncSession, storage: Storage, batch: Batch) -> BatchOut:
    return BatchOut(
        id=batch.id,
        status=batch.status.value,
        required_files=batch.required_files,
        files=[
            await _source_out(storage, batch, source) for source in await _files(session, batch.id)
        ],
    )


async def create_batch(
    session: AsyncSession, *, project_id: uuid.UUID, required_files: list[str]
) -> Batch:
    batch = Batch(
        project_id=project_id,
        required_files=required_filenames(required_files),
        status=BatchStatus.UPLOADING,
    )
    session.add(batch)
    await session.flush()
    return batch


def _store_input(
    storage: Storage, path: Path, stream: BinaryIO, max_bytes: int
) -> tuple[str, int, SniffResult]:
    storage.checked_path(path)
    if path.exists():
        stored = file_digest(path)
        incoming = stream_digest(stream, max_bytes)
        if incoming != stored:
            raise BatchError("An untracked raw file exists with different bytes")
        digest, size = stored
    else:
        digest, size = storage.save_raw(path, stream, max_bytes=max_bytes)
    try:
        preview = sniff_csv(path)
        if not preview.columns:
            raise ValueError("No CSV columns were found")
    except (ValueError, UnicodeError, LookupError, csv.Error, duckdb.Error) as exc:
        raise BatchError("The uploaded file cannot be read as CSV", 422) from exc
    return digest, size, preview


async def upload_file(
    session: AsyncSession,
    storage: Storage,
    *,
    project_id: uuid.UUID,
    batch_id: uuid.UUID,
    filename: str,
    stream: BinaryIO,
    max_bytes: int,
) -> SourceFileOut:
    batch = await _locked_batch(session, project_id, batch_id)
    required = _uploading(batch, storage)
    try:
        name = csv_filename(filename)
    except ValueError as exc:
        raise BatchError(str(exc), 422) from exc
    if name not in required:
        raise BatchError("The filename is not declared for this batch", 422)
    if any(source.filename == name for source in await _files(session, batch.id)):
        raise BatchError("This filename has already been uploaded")
    digest, size, preview = await _disk_call(
        _store_input, storage, storage.raw_path(project_id, batch_id, name), stream, max_bytes
    )
    source = SourceFile(
        batch_id=batch.id,
        filename=name,
        storage_path=str(storage.raw_path(project_id, batch_id, name)),
        sha256=digest,
        size_bytes=size,
        read_config=preview.config.model_dump(mode="json"),
        read_config_confirmed=False,
    )
    session.add(source)
    await session.flush()
    return await _source_out(storage, batch, source, preview)


async def confirm_read_config(
    session: AsyncSession,
    storage: Storage,
    *,
    project_id: uuid.UUID,
    batch_id: uuid.UUID,
    file_id: uuid.UUID,
    config: CsvReadConfig,
) -> SourceFileOut:
    batch = await _locked_batch(session, project_id, batch_id)
    _uploading(batch, storage)
    source = await session.scalar(
        select(SourceFile).where(SourceFile.id == file_id, SourceFile.batch_id == batch.id)
    )
    if source is None:
        raise BatchError("Source file not found in this batch", 404)
    try:
        path = _raw_path(storage, batch, source)
        if await _disk_call(file_digest, path) != (source.sha256, source.size_bytes):
            raise BatchError("The raw bytes do not match the recorded upload")
        preview = await run_in_threadpool(read_csv_preview, path, config)
    except (ValueError, UnicodeError, LookupError, csv.Error, duckdb.Error) as exc:
        raise BatchError("The submitted read configuration cannot read this CSV", 422) from exc
    source.read_config = config.model_dump(mode="json")
    source.read_config_confirmed = True
    await session.flush()
    return await _source_out(storage, batch, source, preview)


def _manifest(batch: Batch, sources: list[SourceFile], storage: Storage) -> BatchManifest:
    if any(not source.read_config_confirmed for source in sources):
        raise BatchError("Every file must have a confirmed read configuration")
    try:
        entries = [
            BatchManifestFile(
                file_id=source.id,
                filename=source.filename,
                relative_path=f"raw/{source.filename}",
                sha256=source.sha256,
                size_bytes=source.size_bytes,
                read_config=CsvReadConfig.model_validate(source.read_config),
                read_config_confirmed=True,
            )
            for source in sources
        ]
        snapshot = BatchManifest(
            project_id=batch.project_id,
            batch_id=batch.id,
            required_files=batch.required_files or [],
            files=entries,
        )
        for source in sources:
            _raw_path(storage, batch, source)
        return snapshot
    except ValueError as exc:
        raise BatchError(
            "Every required file must be present and have a confirmed read configuration"
        ) from exc


def _check_snapshot_files(storage: Storage, manifest: BatchManifest) -> None:
    raw = storage.batch_dir(manifest.project_id, manifest.batch_id) / "raw"
    if not raw.is_dir() or sorted(path.name for path in raw.iterdir()) != manifest.required_files:
        raise BatchError("The raw directory contains missing, unexpected or unfinished files")
    for entry in manifest.files:
        path = storage.checked_path(raw / entry.filename)
        if not path.is_file() or file_digest(path) != (entry.sha256, entry.size_bytes):
            raise BatchError("A raw file is missing or differs from its recorded bytes")


def _prepare_manifest(
    storage: Storage, snapshot: BatchManifest, committed_hash: str | None
) -> None:
    _check_snapshot_files(storage, snapshot)
    path = storage.manifest_path(snapshot.project_id, snapshot.batch_id)
    content = snapshot.canonical_bytes()
    if committed_hash is not None:
        if snapshot.digest() != committed_hash:
            raise BatchError("The ready batch metadata differs from its committed snapshot")
        if path.exists() and path.read_bytes() != content:
            raise BatchError("The published manifest is corrupt")
    storage.write_manifest(snapshot.project_id, snapshot.batch_id, content)


async def mark_batch_ready(
    session: AsyncSession, storage: Storage, *, project_id: uuid.UUID, batch_id: uuid.UUID
) -> BatchOut:
    """Prepare the manifest and READY metadata; the caller commits before publishing the marker."""
    batch = await _locked_batch(session, project_id, batch_id)
    if batch.status is BatchStatus.UPLOADING:
        _uploading(batch, storage)
    elif batch.manifest_sha256 is None:
        raise BatchError("A legacy ready batch has no committed manifest")
    snapshot = _manifest(batch, await _files(session, batch.id), storage)
    await _disk_call(_prepare_manifest, storage, snapshot, batch.manifest_sha256)
    batch.manifest_sha256 = snapshot.digest()
    batch.status = BatchStatus.READY
    await session.flush()
    return await batch_out(session, storage, batch)


def _verify_published(storage: Storage, snapshot: BatchManifest, digest: str) -> None:
    try:
        verify_snapshot(storage, snapshot, digest)
    except ValueError as exc:
        raise BatchError(str(exc)) from exc


async def assert_batch_ready(
    session: AsyncSession, storage: Storage, *, project_id: uuid.UUID, batch_id: uuid.UUID
) -> BatchManifest:
    """Fail closed for consumers unless DB, manifest, marker and raw bytes agree."""
    batch = await _get_batch(session, project_id, batch_id, lock=False)
    if batch.status is not BatchStatus.READY or batch.manifest_sha256 is None:
        raise BatchError("Batch is not ready")
    snapshot = _manifest(batch, await _files(session, batch.id), storage)
    if snapshot.digest() != batch.manifest_sha256:
        raise BatchError("Batch metadata no longer matches its committed snapshot")
    await _disk_call(_verify_published, storage, snapshot, batch.manifest_sha256)
    return snapshot


async def publish_ready_marker(
    session: AsyncSession, storage: Storage, *, project_id: uuid.UUID, batch_id: uuid.UUID
) -> None:
    batch = await _locked_batch(session, project_id, batch_id)
    if batch.status is not BatchStatus.READY or batch.manifest_sha256 is None:
        raise BatchError("Readiness must be committed before publishing the marker")
    snapshot = _manifest(batch, await _files(session, batch.id), storage)
    if snapshot.digest() != batch.manifest_sha256:
        raise BatchError("Batch metadata differs from the committed snapshot")
    await _disk_call(_check_snapshot_files, storage, snapshot)
    await _disk_call(storage.mark_ready, project_id, batch_id, batch.manifest_sha256)
    await assert_batch_ready(session, storage, project_id=project_id, batch_id=batch_id)


async def schema_fingerprint(session: AsyncSession, batch_id: uuid.UUID) -> str:
    """TODO: fingerprint filenames, columns and types after finalizing the profiler contract."""
    raise NotImplementedError


async def check_schema_unchanged(
    session: AsyncSession, batch_id: uuid.UUID, approved_fingerprint: str
) -> None:
    """TODO: stop for Engineer review when a new batch changes the approved schema (FR-17)."""
    raise NotImplementedError
