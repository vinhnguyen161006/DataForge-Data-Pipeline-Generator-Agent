"""Verify published bytes before a consumer stages immutable batch inputs."""

import hashlib
from pathlib import Path

from app.ingest.manifest import BatchManifest
from app.ingest.storage import Storage, stream_digest

MAX_MANIFEST_BYTES = 4 * 1024 * 1024


def checked_regular_path(storage: Storage, path: Path) -> Path:
    root = storage.root.absolute()
    candidate = path.absolute()
    if not candidate.is_relative_to(root) or ".." in candidate.parts:
        raise ValueError("Snapshot paths must stay inside storage")
    if any(part.is_symlink() for part in (candidate, *candidate.parents)):
        raise ValueError("Snapshot paths cannot contain symlinks")
    if candidate.exists() and (not candidate.is_file() or candidate.stat().st_nlink != 1):
        raise ValueError("Snapshot inputs must be regular files without hard links")
    return candidate


def verify_snapshot(storage: Storage, snapshot: BatchManifest, digest: str) -> None:
    """Require marker, canonical manifest, declared file set and raw bytes to agree."""
    manifest = checked_regular_path(
        storage, storage.manifest_path(snapshot.project_id, snapshot.batch_id)
    )
    marker = checked_regular_path(
        storage, storage.marker_path(snapshot.project_id, snapshot.batch_id)
    )
    if not manifest.is_file() or not marker.is_file():
        raise ValueError("Batch publication is incomplete")
    if manifest.stat().st_size > MAX_MANIFEST_BYTES or marker.stat().st_size != 65:
        raise ValueError("Batch publication has invalid metadata size")
    content = manifest.read_bytes()
    parsed = BatchManifest.model_validate_json(content)
    if (
        hashlib.sha256(content).hexdigest() != digest
        or snapshot.digest() != digest
        or parsed.canonical_bytes() != snapshot.canonical_bytes()
        or marker.read_bytes() != (digest + "\n").encode("ascii")
    ):
        raise ValueError("The manifest or readiness marker does not match the committed snapshot")
    raw = manifest.parent / "raw"
    if raw.is_symlink() or not raw.is_dir():
        raise ValueError("The raw directory is invalid")
    if sorted(path.name for path in raw.iterdir()) != snapshot.required_files:
        raise ValueError("The raw directory contains missing, unexpected or unfinished files")
    for entry in snapshot.files:
        path = checked_regular_path(storage, raw / entry.filename)
        if not path.is_file() or path.stat().st_size != entry.size_bytes:
            raise ValueError("A raw file is missing or differs from its recorded bytes")
        with path.open("rb") as stream:
            if stream_digest(stream, max_bytes=entry.size_bytes) != (
                entry.sha256,
                entry.size_bytes,
            ):
                raise ValueError("A raw file is missing or differs from its recorded bytes")
