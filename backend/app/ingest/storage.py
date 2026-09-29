import uuid
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
        """TODO: return the batch directory."""
        raise NotImplementedError

    def raw_path(self, project_id: uuid.UUID, batch_id: uuid.UUID, filename: str) -> Path:
        """TODO: return the raw file path; strip directories from filename to block traversal."""
        raise NotImplementedError

    def code_dir(self, project_id: uuid.UUID, run_id: uuid.UUID, version: int) -> Path:
        """TODO: return the directory of one code version."""
        raise NotImplementedError

    def workspace_dir(self, project_id: uuid.UUID, run_id: uuid.UUID, job_id: uuid.UUID) -> Path:
        """TODO: return the per-job sandbox workspace."""
        raise NotImplementedError

    def approved_dir(self, project_id: uuid.UUID, code_version_id: uuid.UUID) -> Path:
        """TODO: return the directory Airflow reads approved code from."""
        raise NotImplementedError

    def save_raw(self, dest: Path, stream: BinaryIO) -> tuple[str, int]:
        """TODO: stream the upload to dest unchanged (write .part then rename); return (sha256,
        size).
        """
        raise NotImplementedError

    def mark_ready(self, project_id: uuid.UUID, batch_id: uuid.UUID) -> None:
        """TODO: create the _READY marker once every required file is present."""
        raise NotImplementedError
