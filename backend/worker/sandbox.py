import os
import selectors
import signal
import subprocess
import sys
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from threading import Event

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from worker.sandbox_limits import Limits as Limits
from worker.sandbox_limits import SandboxLaunchRequest

READ_CHUNK_BYTES = 64 * 1024
POLL_SECONDS = 0.05
TERMINATION_GRACE_SECONDS = 0.2
REAP_TIMEOUT_SECONDS = 2.0

ENV_ALLOWLIST = ("PATH", "LANG", "LC_ALL", "TZ", "SYSTEMROOT")

WORKSPACE_ENV_PATHS = {
    "HOME": "home",
    "USERPROFILE": "home",
    "XDG_CACHE_HOME": "home/.cache",
    "XDG_CONFIG_HOME": "home/.config",
    "TMPDIR": "tmp",
    "TEMP": "tmp",
    "TMP": "tmp",
    "DBT_PROFILES_DIR": "dbt/profiles",
    "DBT_PROJECT_DIR": ".",
    "DBT_TARGET_PATH": "dbt/target",
    "DBT_LOG_PATH": "dbt/logs",
}


class ChildEnvOverrides(BaseModel):
    """Only workspace-relative dbt directories may be supplied by the caller."""

    model_config = ConfigDict(extra="forbid", strict=True)

    profiles_dir: str | None = Field(default=None, alias="DBT_PROFILES_DIR", min_length=1)
    project_dir: str | None = Field(default=None, alias="DBT_PROJECT_DIR", min_length=1)
    target_path: str | None = Field(default=None, alias="DBT_TARGET_PATH", min_length=1)
    log_path: str | None = Field(default=None, alias="DBT_LOG_PATH", min_length=1)


DUCKDB_LOCKDOWN_SETTINGS = {
    "enable_external_access": "false",
    "autoinstall_known_extensions": "false",
    "autoload_known_extensions": "false",
    "lock_configuration": "true",
}


@dataclass
class SandboxResult:
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool
    output_limited: bool = False
    cancelled: bool = False


def _workspace_root(workspace: Path) -> Path:
    if workspace.is_symlink() or not workspace.is_dir():
        raise ValueError("The child workspace must be an existing directory without a symlink")
    return workspace.resolve(strict=True)


def _workspace_directory(root: Path, relative: str) -> Path:
    if not relative.strip() or "\x00" in relative or "\\" in relative or ":" in relative:
        raise ValueError("Child directories must use workspace-relative paths")
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("Child directories must stay inside the workspace")
    directory = root
    for part in path.parts:
        directory = directory / part
        if directory.is_symlink():
            raise ValueError("Child directories cannot contain symlinks")
    if not directory.resolve().is_relative_to(root):
        raise ValueError("Child directories must stay inside the workspace")
    if directory.exists() and not directory.is_dir():
        raise ValueError("A child directory is occupied by a file")
    return directory


def build_env(workspace: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    """Build an independent child environment and prepare workspace-local directories.

    Only ENV_ALLOWLIST is inherited. All optional overrides are validated dbt
    directory paths; neither credentials nor executable-search settings can be added.
    DuckDB scratch configuration is applied separately on its connection.
    """
    root = _workspace_root(workspace)
    try:
        overrides = ChildEnvOverrides.model_validate(extra if extra is not None else {})
    except ValidationError:
        raise ValueError("Unsupported or invalid child environment overrides") from None
    relative_paths = {
        **WORKSPACE_ENV_PATHS,
        **overrides.model_dump(by_alias=True, exclude_none=True),
    }
    directories = {
        key: _workspace_directory(root, relative) for key, relative in relative_paths.items()
    }
    for directory in set(directories.values()):
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    env = {key: os.environ[key] for key in ENV_ALLOWLIST if key in os.environ}
    env.update({key: str(directory) for key, directory in directories.items()})
    env.update(
        PYTHONNOUSERSITE="1",
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONUNBUFFERED="1",
    )
    return env


def start_child_process(
    args: list[str],
    *,
    workspace: Path,
    extra_env: dict[str, str] | None = None,
    start_new_session: bool = False,
) -> subprocess.Popen[bytes]:
    """Launch fixed argv with a clean environment; the caller owns limits and cleanup.

    This primitive is also used for trusted probes. run_sandboxed wraps its job
    with the rlimit launcher, bounded output, cancellation and process cleanup.
    """
    if not args or any(not item or "\x00" in item for item in args):
        raise ValueError("Child argv must contain nonempty strings without NUL")
    executable = Path(args[0])
    if not executable.is_absolute() or not executable.is_file():
        raise ValueError("The child executable must be an absolute file path")
    root = _workspace_root(workspace)
    return subprocess.Popen(
        args.copy(),
        cwd=root,
        env=build_env(root, extra_env),
        shell=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        close_fds=True,
        start_new_session=start_new_session,
    )


def duckdb_lockdown_sql() -> str:
    """Render the trusted SQL policy with configuration locking applied last."""
    settings = [
        (name, value)
        for name, value in DUCKDB_LOCKDOWN_SETTINGS.items()
        if name != "lock_configuration"
    ]
    settings.append(("lock_configuration", DUCKDB_LOCKDOWN_SETTINGS["lock_configuration"]))
    return "\n".join(f"SET {name} = {value};" for name, value in settings)


def _signal_group(child: subprocess.Popen[bytes], sig: signal.Signals) -> None:
    """Use the session leader id even when the leader has already exited."""
    with suppress(ProcessLookupError):
        os.killpg(child.pid, sig)


def _leader_exited(child: subprocess.Popen[bytes]) -> bool:
    """Observe exit without reaping, retaining the group leader identity until cleanup."""
    return os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None


def _collect_child(
    child: subprocess.Popen[bytes],
    limits: Limits,
    deadline: float,
    stop_event: Event | None,
) -> SandboxResult:
    stdout = bytearray()
    stderr = bytearray()
    timed_out = False
    output_limited = False
    cancelled = False
    terminating_at: float | None = None
    if child.stdout is None or child.stderr is None:
        raise RuntimeError("Sandbox output pipes were not created")
    with selectors.DefaultSelector() as selector:
        for stream, buffer in ((child.stdout, stdout), (child.stderr, stderr)):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream.fileno(), selectors.EVENT_READ, buffer)
        while selector.get_map() or not _leader_exited(child):
            now = time.monotonic()
            if terminating_at is None:
                cancelled = stop_event is not None and stop_event.is_set()
                timed_out = not cancelled and now >= deadline
                if cancelled or timed_out or output_limited:
                    _signal_group(child, signal.SIGTERM)
                    terminating_at = now
            if terminating_at is not None and now >= terminating_at + TERMINATION_GRACE_SECONDS:
                _signal_group(child, signal.SIGKILL)
                break
            if _leader_exited(child):
                _signal_group(child, signal.SIGKILL)
            next_check = (
                deadline if terminating_at is None else terminating_at + TERMINATION_GRACE_SECONDS
            )
            pause = min(POLL_SECONDS, max(0.0, next_check - now))
            if not selector.get_map():
                time.sleep(pause)
                continue
            for key, _events in selector.select(timeout=pause):
                try:
                    chunk = os.read(key.fd, READ_CHUNK_BYTES)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fd)
                    continue
                room = limits.max_output_bytes - len(stdout) - len(stderr)
                key.data.extend(chunk[:room])
                if len(chunk) > room:
                    output_limited = True
    return SandboxResult(
        returncode=child.returncode,
        stdout=stdout.decode("utf-8", errors="replace"),
        stderr=stderr.decode("utf-8", errors="replace"),
        timed_out=timed_out,
        output_limited=output_limited,
        cancelled=cancelled,
    )


def run_sandboxed(
    args: list[str],
    *,
    workspace: Path,
    limits: Limits,
    extra_env: dict[str, str] | None = None,
    stop_event: Event | None = None,
) -> SandboxResult:
    """Execute a Linux job with rlimits, a deadline and bounded combined output.

    Requests to stop return cancelled=True after group cleanup. Process-group
    cleanup covers descendants that remain in that group, not escaped sessions.
    """
    if sys.platform != "linux":
        raise OSError("Resource-limited sandbox execution requires Linux")
    request = SandboxLaunchRequest(command=args, limits=limits)
    if stop_event is not None and stop_event.is_set():
        return SandboxResult(None, "", "", False, cancelled=True)
    launcher = Path(__file__).with_name("limit_exec.py").resolve(strict=True)
    command = [sys.executable, "-I", str(launcher), request.model_dump_json()]
    deadline = time.monotonic() + limits.timeout_seconds
    child = start_child_process(
        command,
        workspace=workspace,
        extra_env=extra_env,
        start_new_session=True,
    )
    try:
        result = _collect_child(child, limits, deadline, stop_event)
    finally:
        try:
            _signal_group(child, signal.SIGKILL)
        finally:
            try:
                child.wait(timeout=REAP_TIMEOUT_SECONDS)
            finally:
                if child.stdout is not None:
                    child.stdout.close()
                if child.stderr is not None:
                    child.stderr.close()
    result.returncode = child.returncode
    return result
