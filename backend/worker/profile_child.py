"""Fixed, isolated profile entrypoint; stdout is reserved for one response document."""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    sys.dont_write_bytecode = True
    try:
        if len(sys.argv) != 2:
            raise ValueError("A profile request file is required")
        backend = Path(__file__).resolve().parents[1]
        sys.path.insert(0, str(backend))
        from worker.filesystem import confine_profile_filesystem

        workspace = Path.cwd().resolve(strict=True)
        request_path = workspace / "request.json"
        if Path(sys.argv[1]) != request_path or request_path.is_symlink():
            raise ValueError("The profile request must be the workspace request file")
        confine_profile_filesystem(workspace, backend)
        from app.ingest.storage import file_digest
        from app.profiler.profile import profile_files, table_name_for
        from worker.duckdb_runtime import CsvTableInput, create_profile_database
        from worker.profile_protocol import (
            MAX_PROTOCOL_BYTES,
            ProfileChildRequest,
            ProfileChildResponse,
        )

        if request_path.stat().st_size > MAX_PROTOCOL_BYTES:
            raise ValueError("The profile request is too large")
        request = ProfileChildRequest.model_validate_json(request_path.read_bytes())
        sources: list[CsvTableInput] = []
        for source in request.job.manifest.files:
            path = workspace / "input" / source.filename
            if path.is_symlink() or file_digest(path) != (source.sha256, source.size_bytes):
                raise ValueError("Staged source differs from the snapshot")
            sources.append(
                CsvTableInput(
                    name=table_name_for(source.filename), path=path, read_config=source.read_config
                )
            )
        with create_profile_database(workspace, sources, limits=request.duckdb_limits) as database:
            profile = profile_files(database.tables, connection=database.connection)
        response = ProfileChildResponse(identity=request.job.identity, profile=profile)
        encoded = response.model_dump_json()
        if len(encoded.encode()) > MAX_PROTOCOL_BYTES:
            raise ValueError("The profile response is too large")
        sys.stdout.write(encoded + "\n")
        return 0
    except Exception as exc:
        sys.stderr.write(f"Profile child failed: {type(exc).__name__}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
