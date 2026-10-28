"""Linux probes verify enforcement, bounded I/O and ownership of process cleanup."""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest

from worker.sandbox import Limits, run_sandboxed, start_child_process
from worker.sandbox_limits import MEBIBYTE, SandboxLaunchRequest

if TYPE_CHECKING:
    import subprocess
    from collections.abc import Iterator

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux rlimit/process-group probes")


@pytest.fixture
def limits() -> Limits:
    return Limits(
        timeout_seconds=6,
        memory_mb=256,
        cpu_seconds=3,
        max_file_mb=8,
        max_open_files=64,
        max_processes=4096,
        max_output_bytes=128 * 1024,
    )


def configured(limits: Limits, **changes: int) -> Limits:
    return Limits.model_validate({**limits.model_dump(), **changes})


def process_alive(pid: int) -> bool:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except FileNotFoundError:
        return False
    return stat.rsplit(")", 1)[1].split()[0] not in {"Z", "X"}


def assert_stopped(pid: int) -> None:
    deadline = time.monotonic() + 2
    while process_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not process_alive(pid), f"Sandbox process {pid} is still running"


@pytest.fixture
def tree_cleanup(tmp_path: Path) -> Iterator[None]:
    """Only signal identities recorded by this test's child, including failed assertions."""
    yield
    for marker in tmp_path.rglob("tree-pids.json"):
        pids = json.loads(marker.read_text())
        with suppress(ProcessLookupError):
            os.killpg(pids["leader"], signal.SIGKILL)
        for pid in pids["children"]:
            if process_alive(pid):
                with suppress(ProcessLookupError):
                    os.kill(pid, signal.SIGKILL)


@pytest.mark.parametrize(
    "field",
    [
        "timeout_seconds",
        "memory_mb",
        "cpu_seconds",
        "max_file_mb",
        "max_open_files",
        "max_processes",
        "max_output_bytes",
    ],
)
@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_invalid_resource_budgets_are_rejected(limits: Limits, field: str, value: object) -> None:
    with pytest.raises(ValueError, match=field):
        Limits.model_validate({**limits.model_dump(), field: value})


def test_existing_limits_constructor_remains_frozen_and_validated(limits: Limits) -> None:
    field = "memory_mb"
    with pytest.raises(ValueError, match="frozen"):
        setattr(limits, field, 1)
    invalid = limits.model_copy(update={"memory_mb": 0})
    with pytest.raises(ValueError, match="memory_mb"):
        SandboxLaunchRequest(command=[sys.executable], limits=invalid)


def test_launcher_contract_is_versioned_and_does_not_accept_extra_fields(limits: Limits) -> None:
    body = {"command": [sys.executable], "limits": limits.model_dump()}
    for change in ({"schema_version": 2}, {"environment": {"SECRET": "fixture-only"}}):
        with pytest.raises(ValueError, match=r"schema_version|environment"):
            SandboxLaunchRequest.model_validate({**body, **change})


def test_child_sees_all_limits_inherited_across_exec_without_changing_parent(
    tmp_path: Path, limits: Limits
) -> None:
    import resource

    names = ["RLIMIT_AS", "RLIMIT_CPU", "RLIMIT_FSIZE", "RLIMIT_NOFILE", "RLIMIT_NPROC"]
    before = {name: resource.getrlimit(getattr(resource, name)) for name in names}
    result = run_sandboxed(
        [
            sys.executable,
            "-I",
            "-c",
            """
import json, os, resource
names = ["RLIMIT_AS", "RLIMIT_CPU", "RLIMIT_FSIZE", "RLIMIT_NOFILE", "RLIMIT_NPROC"]
print(json.dumps({
    "limits": {name: resource.getrlimit(getattr(resource, name)) for name in names},
    "core": resource.getrlimit(resource.RLIMIT_CORE),
    "pid": os.getpid(), "pgid": os.getpgrp(), "sid": os.getsid(0),
}))
""",
        ],
        workspace=tmp_path,
        limits=limits,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["limits"] == {
        "RLIMIT_AS": [limits.memory_mb * MEBIBYTE] * 2,
        "RLIMIT_CPU": [limits.cpu_seconds, limits.cpu_seconds + 1],
        "RLIMIT_FSIZE": [limits.max_file_mb * MEBIBYTE] * 2,
        "RLIMIT_NOFILE": [limits.max_open_files] * 2,
        "RLIMIT_NPROC": [limits.max_processes] * 2,
    }
    assert data["core"] == [0, 0]
    assert data["pid"] == data["pgid"] == data["sid"]
    assert before == {name: resource.getrlimit(getattr(resource, name)) for name in names}


def test_success_and_nonzero_exit_keep_output_and_returncode(
    tmp_path: Path, limits: Limits
) -> None:
    result = run_sandboxed(
        [
            sys.executable,
            "-I",
            "-c",
            'import sys; print("out"); print("err", file=sys.stderr); sys.exit(7)',
        ],
        workspace=tmp_path,
        limits=limits,
    )
    assert result.returncode == 7
    assert result.stdout == "out\n"
    assert result.stderr == "err\n"
    assert not result.timed_out
    assert not result.output_limited
    assert not result.cancelled


def test_wall_timeout_stops_a_sleeping_child(tmp_path: Path, limits: Limits) -> None:
    started = time.monotonic()
    result = run_sandboxed(
        [sys.executable, "-I", "-c", "import time; time.sleep(30)"],
        workspace=tmp_path,
        limits=configured(limits, timeout_seconds=1),
    )
    assert result.timed_out
    assert result.returncode in {-signal.SIGTERM, -signal.SIGKILL}
    assert time.monotonic() - started < 4


def test_timeout_still_applies_when_child_closes_both_output_pipes(
    tmp_path: Path, limits: Limits
) -> None:
    result = run_sandboxed(
        [sys.executable, "-I", "-c", "import os,time; os.close(1); os.close(2); time.sleep(30)"],
        workspace=tmp_path,
        limits=configured(limits, timeout_seconds=1),
    )
    assert result.timed_out
    assert result.returncode is not None


def test_cpu_budget_is_enforced_before_wall_timeout(tmp_path: Path, limits: Limits) -> None:
    result = run_sandboxed(
        [sys.executable, "-I", "-c", "while True: pass"],
        workspace=tmp_path,
        limits=configured(limits, cpu_seconds=1),
    )
    assert not result.timed_out
    assert result.returncode in {-signal.SIGXCPU, -signal.SIGKILL}


def test_address_space_budget_blocks_a_large_allocation(tmp_path: Path, limits: Limits) -> None:
    result = run_sandboxed(
        [
            sys.executable,
            "-I",
            "-c",
            """
try:
    value = bytearray(256 * 1024 * 1024)
except MemoryError:
    print("memory-blocked")
else:
    raise SystemExit("allocation was not limited")
""",
        ],
        workspace=tmp_path,
        limits=configured(limits, memory_mb=64),
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "memory-blocked"
    assert not result.timed_out


def test_file_size_budget_is_per_file_and_blocks_growth(tmp_path: Path, limits: Limits) -> None:
    result = run_sandboxed(
        [
            sys.executable,
            "-I",
            "-c",
            """
with open("large.bin", "wb", buffering=0) as output:
    for _ in range(4):
        output.write(b"x" * (1024 * 1024))
""",
        ],
        workspace=tmp_path,
        limits=configured(limits, max_file_mb=1),
    )
    assert result.returncode != 0
    assert not result.timed_out
    assert (tmp_path / "large.bin").stat().st_size <= MEBIBYTE


def test_open_file_budget_is_enforced(tmp_path: Path, limits: Limits) -> None:
    result = run_sandboxed(
        [
            sys.executable,
            "-I",
            "-c",
            """
import errno
files = []
try:
    for number in range(100):
        files.append(open(f"file-{number}", "wb"))
except OSError as exc:
    assert exc.errno == errno.EMFILE
    print("files-blocked")
else:
    raise SystemExit("open files were not limited")
finally:
    for file in files:
        file.close()
""",
        ],
        workspace=tmp_path,
        limits=configured(limits, max_open_files=32),
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "files-blocked"


@pytest.mark.skipif(
    os.getuid() == 0 if sys.platform == "linux" else True, reason="NPROC needs nonroot"
)
def test_process_budget_blocks_one_bounded_spawn(tmp_path: Path, limits: Limits) -> None:
    result = run_sandboxed(
        [
            sys.executable,
            "-I",
            "-c",
            """
import errno, subprocess, sys
try:
    subprocess.run([sys.executable, "-I", "-c", "pass"], check=True)
except OSError as exc:
    assert exc.errno == errno.EAGAIN
    print("processes-blocked")
else:
    raise SystemExit("process count was not limited")
""",
        ],
        workspace=tmp_path,
        limits=configured(limits, max_processes=1),
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "processes-blocked"


@pytest.mark.parametrize("stream", ["stdout", "stderr", "both"])
def test_output_flood_is_stopped_with_a_combined_byte_budget(
    tmp_path: Path, limits: Limits, stream: str
) -> None:
    source = f"""
import os
fds = {{"stdout": [1], "stderr": [2], "both": [1, 2]}}[{stream!r}]
while True:
    for fd in fds:
        os.write(fd, b"x" * 4096)
"""
    started = time.monotonic()
    result = run_sandboxed(
        [sys.executable, "-I", "-c", source],
        workspace=tmp_path,
        limits=configured(limits, max_output_bytes=1024),
    )
    assert result.output_limited
    assert not result.timed_out
    assert len(result.stdout.encode()) + len(result.stderr.encode()) <= 1024
    assert time.monotonic() - started < 4


def test_exact_output_budget_and_invalid_utf8_are_handled(tmp_path: Path, limits: Limits) -> None:
    result = run_sandboxed(
        [sys.executable, "-I", "-c", 'import os; os.write(1, b"\\xff" * 16)'],
        workspace=tmp_path,
        limits=configured(limits, max_output_bytes=16),
    )
    assert result.returncode == 0
    assert result.stdout == "\ufffd" * 16
    assert not result.output_limited


TREE_SOURCE = """
import json, os, signal, subprocess, sys, time
from pathlib import Path
grandchild = subprocess.Popen(
    [sys.executable, "-I", "-c",
     "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)"]
)
Path("tree-pids.json").write_text(json.dumps({
    "leader": os.getpid(), "children": [grandchild.pid],
}))
print(grandchild.pid, flush=True)
"""


@pytest.mark.usefixtures("tree_cleanup")
def test_timeout_kills_ignoring_child_and_grandchild(tmp_path: Path, limits: Limits) -> None:
    source = (
        TREE_SOURCE
        + """
signal.signal(signal.SIGTERM, signal.SIG_IGN)
time.sleep(30)
"""
    )
    result = run_sandboxed(
        [sys.executable, "-I", "-c", source],
        workspace=tmp_path,
        limits=configured(limits, timeout_seconds=1),
    )
    assert result.timed_out
    assert result.returncode == -signal.SIGKILL
    pids = json.loads((tmp_path / "tree-pids.json").read_text())
    assert_stopped(pids["leader"])
    assert_stopped(pids["children"][0])


@pytest.mark.usefixtures("tree_cleanup")
def test_exited_leader_does_not_leave_a_grandchild_holding_pipes(
    tmp_path: Path, limits: Limits
) -> None:
    result = run_sandboxed(
        [sys.executable, "-I", "-c", TREE_SOURCE + "os._exit(0)\n"],
        workspace=tmp_path,
        limits=limits,
    )
    assert result.returncode == 0
    assert not result.timed_out
    pids = json.loads((tmp_path / "tree-pids.json").read_text())
    assert_stopped(pids["children"][0])


@pytest.mark.usefixtures("tree_cleanup")
def test_normal_exit_also_cleans_background_descendants_with_closed_pipes(
    tmp_path: Path, limits: Limits
) -> None:
    source = """
import json, os, subprocess, sys
from pathlib import Path
grandchild = subprocess.Popen(
    [sys.executable, "-I", "-c", "import time; time.sleep(30)"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)
Path("tree-pids.json").write_text(json.dumps({
    "leader": os.getpid(), "children": [grandchild.pid],
}))
"""
    result = run_sandboxed([sys.executable, "-I", "-c", source], workspace=tmp_path, limits=limits)
    assert result.returncode == 0
    pids = json.loads((tmp_path / "tree-pids.json").read_text())
    assert_stopped(pids["children"][0])


def wait_for_file(path: Path) -> None:
    deadline = time.monotonic() + 5
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert path.exists(), "The child did not reach its readiness marker"


def test_cancellation_stops_only_its_own_session(tmp_path: Path, limits: Limits) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    stop = Event()
    source_a = 'from pathlib import Path; import time; Path("ready").touch(); time.sleep(30)'
    source_b = (
        'from pathlib import Path; import time; Path("ready").touch(); time.sleep(1); print("ok")'
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(
            run_sandboxed,
            [sys.executable, "-I", "-c", source_a],
            workspace=first,
            limits=limits,
            stop_event=stop,
        )
        b = pool.submit(
            run_sandboxed,
            [sys.executable, "-I", "-c", source_b],
            workspace=second,
            limits=limits,
        )
        try:
            wait_for_file(first / "ready")
            wait_for_file(second / "ready")
        finally:
            stop.set()
        cancelled = a.result(timeout=4)
        normal = b.result(timeout=4)
    assert cancelled.cancelled
    assert not cancelled.timed_out
    assert normal.returncode == 0, normal.stderr
    assert normal.stdout == "ok\n"
    assert not normal.cancelled


def test_cancelled_before_launch_does_not_start_a_process(
    tmp_path: Path, limits: Limits, monkeypatch: pytest.MonkeyPatch
) -> None:
    stop = Event()
    stop.set()
    launch = Mock(side_effect=AssertionError("Cancelled work must not be launched"))
    monkeypatch.setattr("worker.sandbox.start_child_process", launch)
    result = run_sandboxed(
        [sys.executable, "-I", "-c", "pass"],
        workspace=tmp_path,
        limits=limits,
        stop_event=stop,
    )
    assert result.cancelled
    assert result.returncode is None
    launch.assert_not_called()


def test_collection_failure_still_reaps_child_and_closes_pipes(
    tmp_path: Path, limits: Limits, monkeypatch: pytest.MonkeyPatch
) -> None:
    children: list[subprocess.Popen[bytes]] = []

    def fail(child: subprocess.Popen[bytes], *args: object, **kwargs: object) -> object:
        children.append(child)
        raise RuntimeError("Injected collection failure")

    monkeypatch.setattr("worker.sandbox._collect_child", fail)
    with pytest.raises(RuntimeError, match="Injected collection"):
        run_sandboxed(
            [sys.executable, "-I", "-c", "import time; time.sleep(30)"],
            workspace=tmp_path,
            limits=limits,
        )
    assert len(children) == 1
    child = children[0]
    assert child.poll() is not None
    assert child.stdout is not None
    assert child.stdout.closed
    assert child.stderr is not None
    assert child.stderr.closed
    assert_stopped(child.pid)


def test_launcher_does_not_run_job_if_inherited_hard_limit_is_too_small(
    tmp_path: Path, limits: Limits
) -> None:
    request = SandboxLaunchRequest(
        command=[
            sys.executable,
            "-I",
            "-c",
            'from pathlib import Path; Path("must-not-run").touch()',
        ],
        limits=limits,
    )
    launcher = Path(__file__).resolve().parents[2] / "worker" / "limit_exec.py"
    source = """
import os, resource, sys
resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))
os.execv(sys.executable, [sys.executable, "-I", sys.argv[1], sys.argv[2]])
"""
    with start_child_process(
        [sys.executable, "-I", "-c", source, str(launcher), request.model_dump_json()],
        workspace=tmp_path,
    ) as child:
        try:
            stdout, stderr = child.communicate(timeout=5)
        finally:
            if child.poll() is None:
                child.kill()
                child.communicate(timeout=2)
    assert child.returncode == 125
    assert stdout == b""
    assert b"Sandbox setup failed" in stderr
    assert not (tmp_path / "must-not-run").exists()


def test_sandbox_preserves_d1_environment_guards(
    tmp_path: Path, limits: Limits, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATAFORGE_APP_DATABASE_URL", "fixture-do-not-inherit")
    monkeypatch.setenv("PYTHONPATH", "fixture-untrusted-path")
    source = """
import json, os
from pathlib import Path
print(json.dumps({
    "credential": "DATAFORGE_APP_DATABASE_URL" in os.environ,
    "injection": "PYTHONPATH" in os.environ,
    "home": str(Path.home()), "cwd": str(Path.cwd()),
}))
"""
    result = run_sandboxed([sys.executable, "-I", "-c", source], workspace=tmp_path, limits=limits)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["credential"] is False
    assert data["injection"] is False
    assert Path(data["home"]).is_relative_to(tmp_path.resolve())
    assert Path(data["cwd"]) == tmp_path.resolve()
    assert "fixture-do-not-inherit" not in result.stdout + result.stderr


def test_unsupported_platform_is_rejected_before_launch(
    tmp_path: Path, limits: Limits, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("worker.sandbox.sys.platform", "win32")
    launch = Mock(side_effect=AssertionError("No unsafe fallback"))
    monkeypatch.setattr("worker.sandbox.start_child_process", launch)
    with pytest.raises(OSError, match="requires Linux"):
        run_sandboxed([sys.executable], workspace=tmp_path, limits=limits)
    launch.assert_not_called()


def test_timeout_flag_is_preserved_when_child_handles_sigterm_and_exits_zero(
    tmp_path: Path, limits: Limits
) -> None:
    source = """
import signal, sys, time
signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
time.sleep(30)
"""
    result = run_sandboxed(
        [sys.executable, "-I", "-c", source],
        workspace=tmp_path,
        limits=configured(limits, timeout_seconds=1),
    )
    assert result.returncode == 0
    assert result.timed_out
    assert not result.cancelled


def test_cpu_hard_limit_stops_a_child_ignoring_the_soft_signal(
    tmp_path: Path, limits: Limits
) -> None:
    source = """
import signal
signal.signal(signal.SIGXCPU, signal.SIG_IGN)
while True:
    pass
"""
    result = run_sandboxed(
        [sys.executable, "-I", "-c", source],
        workspace=tmp_path,
        limits=configured(limits, cpu_seconds=1),
    )
    assert result.returncode == -signal.SIGKILL
    assert not result.timed_out


def test_file_budget_does_not_claim_to_limit_total_workspace_usage(
    tmp_path: Path, limits: Limits
) -> None:
    source = """
from pathlib import Path
for name in ("one.bin", "two.bin"):
    Path(name).write_bytes(b"x" * (768 * 1024))
"""
    result = run_sandboxed(
        [sys.executable, "-I", "-c", source],
        workspace=tmp_path,
        limits=configured(limits, max_file_mb=1),
    )
    assert result.returncode == 0, result.stderr
    assert sum(path.stat().st_size for path in tmp_path.glob("*.bin")) > MEBIBYTE
