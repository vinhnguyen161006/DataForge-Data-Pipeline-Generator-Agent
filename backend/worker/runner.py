from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from app.ingest.snapshot import checked_regular_path, verify_snapshot
from app.ingest.storage import Storage, file_digest
from app.profiler.profile import table_name_for
from app.profiler.schemas import DataProfile
from worker.duckdb_runtime import DuckDBLimits
from worker.profile_protocol import (
    MAX_PROTOCOL_BYTES,
    PreparedProfileJob,
    ProfileChildRequest,
    ProfileChildResponse,
)
from worker.sandbox import Limits, run_sandboxed

if TYPE_CHECKING:
    from threading import Event

DEFAULT_MAX_INPUT_BYTES = 2 * 1024 * 1024 * 1024


class ProfileExecutionError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(f"Profile execution failed: {code}")


def _create_profile_workspace(storage: Storage, job: PreparedProfileJob) -> Path:
    identity = job.identity
    workspace = (
        storage.workspace_dir(identity.project_id, identity.run_id, identity.job_id).absolute()
        / f"attempt-{identity.attempt:04d}"
    )
    if not workspace.is_relative_to(storage.root.absolute()):
        raise ValueError("Profile workspace must stay inside storage")
    if any(path.is_symlink() for path in (workspace, *workspace.parents)):
        raise ValueError("Profile workspace cannot contain symlinks")
    workspace.mkdir(mode=0o700, parents=True, exist_ok=False)
    return workspace


def _stage_profile_inputs(
    storage: Storage, job: PreparedProfileJob, workspace: Path, stop_event: Event | None
) -> None:
    target = workspace / "input"
    target.mkdir(mode=0o700)
    for source in job.manifest.files:
        original = checked_regular_path(
            storage,
            storage.raw_path(job.identity.project_id, job.identity.batch_id, source.filename),
        )
        digest = hashlib.sha256()
        size = 0
        descriptor = os.open(original, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        with (
            os.fdopen(descriptor, "rb") as input_file,
            (target / source.filename).open("xb") as output,
        ):
            while chunk := input_file.read(64 * 1024):
                if stop_event is not None and stop_event.is_set():
                    raise ProfileExecutionError("cancelled")
                size += len(chunk)
                if size > source.size_bytes:
                    raise ProfileExecutionError("source_changed")
                digest.update(chunk)
                output.write(chunk)
        if (digest.hexdigest(), size) != (source.sha256, source.size_bytes):
            raise ProfileExecutionError("source_changed")


class ModelMetrics(BaseModel):
    model_name: str
    status: str
    seconds: float
    rows_scanned: int | None = None
    peak_memory_bytes: int | None = None


class DbtTestResult(BaseModel):
    test_name: str
    model_name: str
    status: str
    failures: int


class ExecutionReportData(BaseModel):
    compiled: bool
    succeeded: bool
    models: list[ModelMetrics] = Field(default_factory=list)
    tests: list[DbtTestResult] = Field(default_factory=list)
    quarantine_counts: dict[str, int] = Field(default_factory=dict)
    total_seconds: float = 0.0
    error: str | None = None


def prepare_workspace(code_dir: Path, raw_dir: Path, workspace: Path) -> None:
    """TODO: copy the code version into a fresh workspace and link raw CSVs read-only."""
    raise NotImplementedError


def run_profile(
    job: PreparedProfileJob,
    limits: Limits,
    *,
    storage: Storage,
    duckdb_limits: DuckDBLimits | None = None,
    stop_event: Event | None = None,
    max_input_bytes: int = DEFAULT_MAX_INPUT_BYTES,
) -> dict[str, Any]:
    """Stage a verified snapshot and return only a validated profile from a confined child.

    The caller supplies metadata prepared from live DB ownership. Call this blocking
    runner off the event loop while maintaining the queue lease. It never retries
    or completes the queue job and retains failed workspaces for inspection.
    """
    job = PreparedProfileJob.model_validate(job.model_dump())
    if stop_event is not None and stop_event.is_set():
        raise ProfileExecutionError("cancelled")
    if (
        max_input_bytes <= 0
        or sum(source.size_bytes for source in job.manifest.files) > max_input_bytes
    ):
        raise ProfileExecutionError("input_too_large")
    verify_snapshot(storage, job.manifest, job.payload.manifest_sha256)
    workspace = _create_profile_workspace(storage, job)
    _stage_profile_inputs(storage, job, workspace, stop_event)
    request = ProfileChildRequest(job=job, duckdb_limits=duckdb_limits or DuckDBLimits())
    encoded = request.model_dump_json().encode()
    if len(encoded) > MAX_PROTOCOL_BYTES:
        raise ProfileExecutionError("request_too_large")
    request_path = workspace / "request.json"
    with request_path.open("xb") as stream:
        stream.write(encoded)
    entrypoint = Path(__file__).with_name("profile_child.py").resolve(strict=True)
    result = run_sandboxed(
        [sys.executable, "-I", str(entrypoint), str(request_path)],
        workspace=workspace,
        limits=limits,
        stop_event=stop_event,
    )
    for failed, code in (
        (result.cancelled, "cancelled"),
        (result.timed_out, "timeout"),
        (result.output_limited, "output_too_large"),
        (result.returncode != 0, "child_failed"),
    ):
        if failed:
            raise ProfileExecutionError(code)
    if len(result.stdout.encode()) > MAX_PROTOCOL_BYTES:
        raise ProfileExecutionError("response_too_large")
    try:
        response = ProfileChildResponse.model_validate_json(result.stdout)
    except ValueError:
        raise ProfileExecutionError("invalid_response") from None
    if response.identity != job.identity:
        raise ProfileExecutionError("response_identity_mismatch")
    expected = {(table_name_for(source.filename), source.filename) for source in job.manifest.files}
    actual = [(table.name, table.source_file) for table in response.profile.tables]
    if len(actual) != len(expected) or set(actual) != expected:
        raise ProfileExecutionError("response_tables_mismatch")
    for source in job.manifest.files:
        original = checked_regular_path(
            storage,
            storage.raw_path(job.identity.project_id, job.identity.batch_id, source.filename),
        )
        if file_digest(original) != (source.sha256, source.size_bytes):
            raise ProfileExecutionError("source_changed")
    profile = DataProfile.model_validate(response.profile.model_dump())
    with (workspace / "profile.json").open("x", encoding="utf-8") as stream:
        stream.write(profile.model_dump_json())
    return profile.model_dump(mode="json")


def run_dbt_build(payload: dict[str, Any], limits: Limits) -> ExecutionReportData:
    """TODO: job kind "dbt_build": dbt compile + build in the sandbox, then collect metrics.

    Read target/run_results.json for status/timing and DuckDB profiling output
    for rows scanned and peak memory per model (FR-11).
    """
    raise NotImplementedError


def run_rewrite_benchmark(payload: dict[str, Any], limits: Limits) -> dict[str, Any]:
    """TODO: job kind "rewrite_benchmark": execute original and candidate SQL on the same
    DuckDB file.

    Return equivalence (compare/multiset) and timing samples (compare/benchmark);
    the API process turns them into a judgement.
    """
    raise NotImplementedError
