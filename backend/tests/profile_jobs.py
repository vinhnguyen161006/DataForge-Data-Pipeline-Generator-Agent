"""Filesystem-only READY snapshots for profile protocol and runner tests."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from app.ingest.manifest import BatchManifest, BatchManifestFile
from app.ingest.sniff import CsvReadConfig
from app.ingest.storage import Storage
from app.jobs.profile import ProfileJobPayload
from worker.profile_protocol import PreparedProfileJob, ProfileIdentity

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


def make_profile_job(
    root: Path,
    contents: Mapping[str, str | bytes] | None = None,
    configs: Mapping[str, CsvReadConfig] | None = None,
) -> tuple[Storage, PreparedProfileJob]:
    storage = Storage(root.absolute())
    identity = ProfileIdentity(
        project_id=uuid4(), batch_id=uuid4(), run_id=uuid4(), job_id=uuid4(), attempt=1
    )
    entries: list[BatchManifestFile] = []
    for filename, content in (
        contents
        if contents is not None
        else {
            "customers.csv": "id,name\n00001,Alice\n00002,Bob\n",
            "orders.csv": "id,customer_id,total\n1,00001,12.5\n2,00001,20\n3,00003,\n",
        }
    ).items():
        path = storage.raw_path(identity.project_id, identity.batch_id, filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode() if isinstance(content, str) else content)
        from app.ingest.storage import file_digest

        digest, size = file_digest(path)
        entries.append(
            BatchManifestFile(
                file_id=uuid4(),
                filename=filename,
                relative_path=f"raw/{filename}",
                sha256=digest,
                size_bytes=size,
                read_config=(configs or {}).get(filename, CsvReadConfig()),
                read_config_confirmed=True,
            )
        )
    manifest = BatchManifest(
        project_id=identity.project_id,
        batch_id=identity.batch_id,
        required_files=sorted(entry.filename for entry in entries),
        files=entries,
    )
    storage.write_manifest(identity.project_id, identity.batch_id, manifest.canonical_bytes())
    storage.mark_ready(identity.project_id, identity.batch_id, manifest.digest())
    return storage, PreparedProfileJob(
        identity=identity,
        manifest=manifest,
        payload=ProfileJobPayload(
            project_id=identity.project_id,
            batch_id=identity.batch_id,
            manifest_sha256=manifest.digest(),
        ),
    )
