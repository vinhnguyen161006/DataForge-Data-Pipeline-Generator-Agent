import hashlib
import os
import uuid
from pathlib import Path
from typing import BinaryIO


class UploadTooLargeError(ValueError):
    """An incoming stream exceeded the configured byte limit."""


def stream_digest(stream: BinaryIO, max_bytes: int | None = None) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    while chunk := stream.read(1024 * 1024):
        size += len(chunk)
        if max_bytes is not None and size > max_bytes:
            raise UploadTooLargeError("The uploaded file exceeds the configured size limit")
        digest.update(chunk)
    return digest.hexdigest(), size


def file_digest(path: Path) -> tuple[str, int]:
    with path.open("rb") as stream:
        return stream_digest(stream)


class Storage:
    """Persistent batch inputs, immutable manifests and per-job workspaces."""

    def __init__(self, root: Path):
        self.root = root

    def batch_dir(self, project_id: uuid.UUID, batch_id: uuid.UUID) -> Path:
        return self.root / "projects" / str(project_id) / "batches" / str(batch_id)

    def raw_path(self, project_id: uuid.UUID, batch_id: uuid.UUID, filename: str) -> Path:
        safe_name = Path(filename).name
        if safe_name in {"", ".", ".."}:
            raise ValueError("filename must contain a file name")
        return self.batch_dir(project_id, batch_id) / "raw" / safe_name

    def code_dir(self, project_id: uuid.UUID, run_id: uuid.UUID, version: int) -> Path:
        if version < 1:
            raise ValueError("version must be positive")
        return (
            self.root / "projects" / str(project_id) / "runs" / str(run_id) / "code" / f"v{version}"
        )

    def workspace_dir(self, project_id: uuid.UUID, run_id: uuid.UUID, job_id: uuid.UUID) -> Path:
        return (
            self.root
            / "projects"
            / str(project_id)
            / "runs"
            / str(run_id)
            / "workspaces"
            / str(job_id)
        )

    def approved_dir(self, project_id: uuid.UUID, code_version_id: uuid.UUID) -> Path:
        return self.root / "projects" / str(project_id) / "approved" / str(code_version_id)

    def checked_path(self, path: Path) -> Path:
        if path.is_symlink() or not path.resolve().is_relative_to(self.root.resolve()):
            raise ValueError("destination must be inside the storage root without symlinks")
        return path

    def save_raw(
        self, dest: Path, stream: BinaryIO, *, max_bytes: int | None = None
    ) -> tuple[str, int]:
        """Publish complete raw bytes without replacement; remove only this writer's temporary."""
        destination = self.checked_path(dest)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise FileExistsError(destination)
        partial = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.part")
        digest = hashlib.sha256()
        size = 0
        try:
            with partial.open("xb") as output:
                while chunk := stream.read(1024 * 1024):
                    size += len(chunk)
                    if max_bytes is not None and size > max_bytes:
                        raise UploadTooLargeError(
                            "The uploaded file exceeds the configured size limit"
                        )
                    output.write(chunk)
                    digest.update(chunk)
                output.flush()
                os.fsync(output.fileno())
            os.link(partial, destination)
            self._sync_directory(destination.parent)
        finally:
            partial.unlink(missing_ok=True)
        return digest.hexdigest(), size

    def manifest_path(self, project_id: uuid.UUID, batch_id: uuid.UUID) -> Path:
        return self.checked_path(self.batch_dir(project_id, batch_id) / "manifest.json")

    def marker_path(self, project_id: uuid.UUID, batch_id: uuid.UUID) -> Path:
        return self.checked_path(self.batch_dir(project_id, batch_id) / "_READY")

    @staticmethod
    def _sync_directory(directory: Path) -> None:
        if os.name == "posix":
            descriptor = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)

    def _atomic_write(self, path: Path, content: bytes) -> None:
        self.checked_path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_name(f".{path.name}.{uuid.uuid4().hex}.part")
        try:
            with partial.open("xb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(partial, path)
            self._sync_directory(path.parent)
        finally:
            partial.unlink(missing_ok=True)

    def write_manifest(self, project_id: uuid.UUID, batch_id: uuid.UUID, content: bytes) -> None:
        path = self.manifest_path(project_id, batch_id)
        if self.marker_path(project_id, batch_id).exists():
            if not path.exists() or path.read_bytes() != content:
                raise ValueError("A published batch manifest cannot be replaced")
            return
        self._atomic_write(path, content)

    def mark_ready(self, project_id: uuid.UUID, batch_id: uuid.UUID, manifest_sha256: str) -> None:
        """Publish the manifest digest only after the caller committed READY in PostgreSQL."""
        raw = self.batch_dir(project_id, batch_id) / "raw"
        if not raw.is_dir() or not any(path.is_file() for path in raw.iterdir()):
            raise ValueError("cannot mark an empty batch ready")
        manifest = self.manifest_path(project_id, batch_id)
        if not manifest.is_file() or file_digest(manifest)[0] != manifest_sha256:
            raise ValueError("Manifest does not match the committed snapshot")
        marker = self.marker_path(project_id, batch_id)
        content = (manifest_sha256 + "\n").encode("ascii")
        if marker.exists():
            if marker.read_bytes() != content:
                raise ValueError("Readiness marker does not match the committed snapshot")
            return
        self._atomic_write(marker, content)
