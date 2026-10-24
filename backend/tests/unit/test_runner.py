"""Real child execution plus fail-closed checks around profile transport and snapshots."""

from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING

import pytest

from app.ingest.sniff import CsvReadConfig
from app.ingest.storage import file_digest
from app.profiler.profile import table_name_for
from app.profiler.schemas import DataProfile, TableProfile
from tests.profile_jobs import make_profile_job
from worker.profile_protocol import MAX_PROTOCOL_BYTES, ProfileChildResponse, ProfileIdentity
from worker.runner import ProfileExecutionError, run_profile
from worker.sandbox import Limits, SandboxResult, run_sandboxed

if TYPE_CHECKING:
    from app.ingest.storage import Storage
    from worker.profile_protocol import PreparedProfileJob

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux confined profile child")


@pytest.fixture
def limits() -> Limits:
    return Limits(
        timeout_seconds=20,
        cpu_seconds=10,
        memory_mb=2048,
        max_file_mb=32,
        max_processes=4096,
    )


def workspace(storage: Storage, job: PreparedProfileJob) -> Path:
    return (
        storage.workspace_dir(job.identity.project_id, job.identity.run_id, job.identity.job_id)
        / f"attempt-{job.identity.attempt:04d}"
    )


def response_for(job: PreparedProfileJob) -> ProfileChildResponse:
    return ProfileChildResponse(
        identity=job.identity,
        profile=DataProfile(
            tables=[
                TableProfile(
                    name=table_name_for(source.filename),
                    source_file=source.filename,
                    row_count=0,
                    columns=[],
                )
                for source in job.manifest.files
            ],
            key_candidates=[],
            relationship_candidates=[],
        ),
    )


def test_real_child_produces_profile_and_preserves_raw(tmp_path: Path, limits: Limits) -> None:
    storage, job = make_profile_job(tmp_path)
    original = {
        source.filename: file_digest(
            storage.raw_path(job.identity.project_id, job.identity.batch_id, source.filename)
        )
        for source in job.manifest.files
    }
    result = DataProfile.model_validate(run_profile(job, limits, storage=storage))
    assert {table.name: table.row_count for table in result.tables} == {"customers": 2, "orders": 3}
    customer = next(table for table in result.tables if table.name == "customers")
    assert customer.columns[0].has_leading_zeros
    assert customer.columns[0].sample_values == ["00001", "00002"]
    root = workspace(storage, job)
    assert (root / "profile.duckdb").is_file()
    assert DataProfile.model_validate_json((root / "profile.json").read_bytes()) == result
    assert not list(root.glob("csv-load-*"))
    for source in job.manifest.files:
        path = storage.raw_path(job.identity.project_id, job.identity.batch_id, source.filename)
        assert file_digest(path) == original[source.filename]
        assert (root / "input" / source.filename).stat().st_ino != path.stat().st_ino
    relation = next(
        item
        for item in result.relationship_candidates
        if item.child_table == "orders" and item.parent_table == "customers"
    )
    assert relation.match_ratio == pytest.approx(2 / 3)
    assert relation.orphan_count == 1


def test_confirmed_encoding_and_config_work_through_child(tmp_path: Path, limits: Limits) -> None:
    config = CsvReadConfig(
        encoding="utf-16",
        delimiter=";",
        skip_rows=1,
        null_tokens=["NULL"],
    )
    storage, job = make_profile_job(
        tmp_path,
        {"labels.csv": "ignored\ncode;label\n001;caf\u00e9\n002;NULL\n".encode("utf-16")},
        {"labels.csv": config},
    )
    result = DataProfile.model_validate(run_profile(job, limits, storage=storage))
    assert result.tables[0].columns[1].null_ratio == 0.5
    assert result.tables[0].columns[1].sample_values == ["caf\u00e9"]


@pytest.mark.parametrize(
    "corruption",
    [
        "marker_missing",
        "marker_hash",
        "manifest_missing",
        "manifest_changed",
        "raw_missing",
        "raw_changed",
        "unexpected_raw",
        "raw_symlink",
        "raw_hardlink",
    ],
)
def test_corrupt_snapshot_never_reaches_child(
    tmp_path: Path, limits: Limits, monkeypatch: pytest.MonkeyPatch, corruption: str
) -> None:
    storage, job = make_profile_job(tmp_path)
    identity = job.identity
    marker = storage.marker_path(identity.project_id, identity.batch_id)
    manifest = storage.manifest_path(identity.project_id, identity.batch_id)
    source = storage.raw_path(identity.project_id, identity.batch_id, "customers.csv")
    if corruption == "marker_missing":
        marker.unlink()
    elif corruption == "marker_hash":
        marker.write_text("0" * 64 + "\n")
    elif corruption == "manifest_missing":
        manifest.unlink()
    elif corruption == "manifest_changed":
        manifest.write_text("{}")
    elif corruption == "raw_missing":
        source.unlink()
    elif corruption == "raw_changed":
        source.write_text("id\nchanged\n")
    elif corruption == "unexpected_raw":
        (source.parent / "partial.part").write_text("unfinished")
    else:
        elsewhere = tmp_path / "outside.csv"
        elsewhere.write_bytes(source.read_bytes())
        source.unlink()
        if corruption == "raw_symlink":
            source.symlink_to(elsewhere)
        else:
            source.hardlink_to(elsewhere)

    def unexpected(*args: object, **kwargs: object) -> SandboxResult:
        pytest.fail("A corrupt snapshot reached subprocess launch")

    monkeypatch.setattr("worker.runner.run_sandboxed", unexpected)
    with pytest.raises(ValueError, match=r".+"):
        run_profile(job, limits, storage=storage)
    assert not workspace(storage, job).exists()


def test_workspace_symlink_is_rejected(tmp_path: Path, limits: Limits) -> None:
    storage, job = make_profile_job(tmp_path)
    root = workspace(storage, job)
    root.parent.mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    root.symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        run_profile(job, limits, storage=storage)


def test_same_attempt_cannot_overwrite_existing_database(tmp_path: Path, limits: Limits) -> None:
    storage, job = make_profile_job(tmp_path)
    run_profile(job, limits, storage=storage)
    before = file_digest(workspace(storage, job) / "profile.duckdb")
    with pytest.raises(FileExistsError):
        run_profile(job, limits, storage=storage)
    assert file_digest(workspace(storage, job) / "profile.duckdb") == before


@pytest.mark.parametrize("code", ["cancelled", "timeout", "output_too_large", "child_failed"])
def test_subprocess_failure_is_classified_and_not_parsed(
    tmp_path: Path, limits: Limits, monkeypatch: pytest.MonkeyPatch, code: str
) -> None:
    storage, job = make_profile_job(tmp_path)
    result = SandboxResult(
        returncode=1 if code == "child_failed" else 0,
        stdout="not json",
        stderr="fixture-parent-secret",
        timed_out=code == "timeout",
        output_limited=code == "output_too_large",
        cancelled=code == "cancelled",
    )
    monkeypatch.setattr("worker.runner.run_sandboxed", lambda *args, **kwargs: result)
    with pytest.raises(ProfileExecutionError) as caught:
        run_profile(job, limits, storage=storage)
    assert caught.value.code == code
    assert "fixture-parent-secret" not in str(caught.value)
    assert workspace(storage, job).is_dir()


@pytest.mark.parametrize("corruption", ["json", "version", "identity", "table", "extra", "large"])
def test_invalid_child_response_is_rejected(
    tmp_path: Path, limits: Limits, monkeypatch: pytest.MonkeyPatch, corruption: str
) -> None:
    storage, job = make_profile_job(tmp_path)
    body = response_for(job).model_dump(mode="json")
    if corruption == "version":
        body["schema_version"] = 2
    elif corruption == "identity":
        body["identity"]["attempt"] = 2
    elif corruption == "table":
        body["profile"]["tables"][0]["source_file"] = "wrong.csv"
    elif corruption == "extra":
        body["profile"]["raw_rows"] = [["fixture-only"]]
    stdout = json.dumps(body)
    if corruption == "json":
        stdout = "log line\n" + stdout
    elif corruption == "large":
        stdout = "x" * (MAX_PROTOCOL_BYTES + 1)
    result = SandboxResult(0, stdout, "", False)
    monkeypatch.setattr("worker.runner.run_sandboxed", lambda *args, **kwargs: result)
    with pytest.raises(ProfileExecutionError):
        run_profile(job, limits, storage=storage)


def test_cancellation_before_start_does_not_create_workspace(
    tmp_path: Path, limits: Limits
) -> None:
    storage, job = make_profile_job(tmp_path)
    event = Event()
    event.set()
    with pytest.raises(ProfileExecutionError, match="cancelled"):
        run_profile(job, limits, storage=storage, stop_event=event)
    assert not workspace(storage, job).exists()


def test_staging_budget_is_checked_before_creating_workspace(
    tmp_path: Path, limits: Limits
) -> None:
    storage, job = make_profile_job(tmp_path)
    with pytest.raises(ProfileExecutionError, match="input_too_large"):
        run_profile(job, limits, storage=storage, max_input_bytes=1)
    assert not workspace(storage, job).exists()


def test_failure_retry_uses_fresh_attempt(
    tmp_path: Path, limits: Limits, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage, job = make_profile_job(tmp_path)
    with monkeypatch.context() as patch:
        patch.setattr(
            "worker.runner.run_sandboxed",
            lambda *args, **kwargs: SandboxResult(1, "", "fixture-only", False),
        )
        with pytest.raises(ProfileExecutionError):
            run_profile(job, limits, storage=storage)
    first = workspace(storage, job)
    (first / "profile.duckdb").write_bytes(b"failed-attempt")
    identity = ProfileIdentity.model_validate({**job.identity.model_dump(), "attempt": 2})
    retried = job.model_copy(update={"identity": identity})
    assert DataProfile.model_validate(run_profile(retried, limits, storage=storage)).tables
    assert (first / "profile.duckdb").read_bytes() == b"failed-attempt"
    assert workspace(storage, retried) != first


def test_two_parallel_runs_do_not_share_database(tmp_path: Path, limits: Limits) -> None:
    left_storage, left = make_profile_job(tmp_path)
    right_storage, right = make_profile_job(tmp_path, {"only.csv": "id\n7\n"})
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(run_profile, left, limits, storage=left_storage)
        second = executor.submit(run_profile, right, limits, storage=right_storage)
        assert {table["name"] for table in first.result()["tables"]} == {"customers", "orders"}
        assert {table["name"] for table in second.result()["tables"]} == {"only"}
    assert workspace(left_storage, left) != workspace(right_storage, right)


def test_child_cannot_access_original_even_by_absolute_path(
    tmp_path: Path, limits: Limits, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = tmp_path / "original.csv"
    original.write_text("id\n001\n", encoding="utf-8")
    before = file_digest(original)
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "symlink.csv").symlink_to(original)
    monkeypatch.setenv("DATAFORGE_APP_DATABASE_URL", "fixture-parent-only")
    monkeypatch.setenv("PGPASSWORD", "fixture-parent-only")
    probe = Path(__file__).resolve().parents[1] / "fixtures/sandbox/profile_filesystem_probe.py"
    result = run_sandboxed(
        [sys.executable, "-I", str(probe), str(root), str(original)],
        workspace=root,
        limits=limits,
    )
    assert result.returncode == 0, result.stderr
    body = json.loads(result.stdout)
    assert set(body["denied"]) == {"read", "write", "rename", "unlink", "hardlink", "symlink_write"}
    assert body["credentials"] == []
    assert file_digest(original) == before
    assert (root / "local.txt").read_text() == "allowed"


def test_runtime_request_cannot_choose_executable(
    tmp_path: Path, limits: Limits, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage, job = make_profile_job(tmp_path)
    event = Event()

    def fake(args: list[str], **kwargs: object) -> SandboxResult:
        assert args[0] == sys.executable
        assert args[1] == "-I"
        assert Path(args[2]).name == "profile_child.py"
        assert kwargs["workspace"] == workspace(storage, job)
        assert kwargs["stop_event"] is event
        return SandboxResult(0, response_for(job).model_dump_json(), "", False)

    monkeypatch.setattr("worker.runner.run_sandboxed", fake)
    assert run_profile(job, limits, storage=storage, stop_event=event)["tables"]


def test_filesystem_policy_refuses_unsupported_kernel(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import Mock

    from worker.filesystem import landlock_abi

    library = Mock()
    library.syscall.return_value = 2
    monkeypatch.setattr("worker.filesystem.ctypes.CDLL", lambda *args, **kwargs: library)
    with pytest.raises(OSError, match="ABI 3"):
        landlock_abi()
