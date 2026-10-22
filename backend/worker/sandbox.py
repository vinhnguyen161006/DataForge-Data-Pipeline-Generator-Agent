import os
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, ConfigDict, Field, ValidationError

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


@dataclass(frozen=True)
class Limits:
    timeout_seconds: int
    memory_mb: int
    cpu_seconds: int
    max_file_mb: int
    max_open_files: int = 256
    max_processes: int = 64


@dataclass
class SandboxResult:
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool


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
) -> subprocess.Popen[bytes]:
    """Launch fixed argv with a clean environment; the caller owns limits and cleanup.

    This launch primitive does not implement the full sandbox. D2 supplies resource
    limits, bounded pipe consumption, cancellation and process-tree termination.
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
    )


def duckdb_lockdown_sql() -> str:
    """TODO: render SET statements for DUCKDB_LOCKDOWN_SETTINGS, lock_configuration last.

    Run before any generated SQL so models cannot read files, load extensions
    or change settings. Verify setting names against the pinned DuckDB version.
    """
    raise NotImplementedError


def run_sandboxed(
    args: list[str],
    *,
    workspace: Path,
    limits: Limits,
    extra_env: dict[str, str] | None = None,
) -> SandboxResult:
    """TODO: run args in a child process with cwd=workspace, the scrubbed env and hard limits.

    Never use shell=True. Linux: RLIMIT_AS, RLIMIT_CPU, RLIMIT_FSIZE, RLIMIT_NOFILE,
    RLIMIT_NPROC and a new session so the whole tree is killed on timeout. The
    container adds read-only rootfs, no egress, dropped capabilities and cgroup limits.
    """
    raise NotImplementedError
