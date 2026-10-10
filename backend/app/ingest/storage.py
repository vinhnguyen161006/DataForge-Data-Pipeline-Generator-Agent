import uuid
import hashlib
import os
from pathlib import Path
from typing import BinaryIO


class Storage:
    """Layout of the shared persistent volume.

    projects/<project_id>/batches/<batch_id>/raw/<filename>
    projects/<project_id>/batches/<batch_id>/_READY
    projects/<project_id>/runs/<run_id>/code/v<N>/
    projects/<project_id>/runs/<run_id>/workspaces/<job_id>/
    projects/<project_id>/approved/<code_version_id>/
    """

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
        return self.root / "projects" / str(project_id) / "runs" / str(run_id) / "code" / f"v{version}"

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

    def save_raw(self, dest: Path, stream: BinaryIO) -> tuple[str, int]:
        """Stream bytes to a temporary file and publish them without overwriting."""
        destination = dest.resolve()
        root = self.root.resolve()
        if not destination.is_relative_to(root):
            raise ValueError("destination must be inside the storage root")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise FileExistsError(destination)
        partial = destination.with_name(destination.name + ".part")
        if partial.exists():
            raise FileExistsError(partial)
        digest = hashlib.sha256()
        size = 0
        try:
            with partial.open("xb") as output:
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
                output.flush()
                os.fsync(output.fileno())
            if destination.exists():
                raise FileExistsError(destination)
            os.link(partial, destination)
            partial.unlink()
        except BaseException:
            partial.unlink(missing_ok=True)
            raise
        return digest.hexdigest(), size

    def mark_ready(self, project_id: uuid.UUID, batch_id: uuid.UUID) -> None:
        """Create the batch readiness marker atomically."""
        batch = self.batch_dir(project_id, batch_id)
        raw = batch / "raw"
        if not raw.is_dir() or not any(
            path.is_file() and not path.name.endswith(".part") for path in raw.iterdir()
        ):
            raise ValueError("cannot mark an empty batch ready")
        batch.mkdir(parents=True, exist_ok=True)
        marker = batch / "_READY"
        if marker.exists():
            return
        temporary = batch / "._READY.part"
        try:
            temporary.write_text("", encoding="utf-8")
            os.replace(temporary, marker)
        finally:
            temporary.unlink(missing_ok=True)
