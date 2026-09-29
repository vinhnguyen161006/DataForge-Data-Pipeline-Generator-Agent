from dataclasses import dataclass
from pathlib import Path

ENV_ALLOWLIST = ("PATH", "LANG", "LC_ALL", "TZ", "SYSTEMROOT", "TEMP", "TMP")

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


def build_env(workspace: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    """TODO: build the child env from ENV_ALLOWLIST only, plus dbt/DuckDB paths in workspace.

    Never inherit os.environ: it holds the app database URL and API keys.
    Refuse any extra key that looks like a DSN, database URL, password or token.
    """
    raise NotImplementedError


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
