"""Own a private DuckDB file and expose only a verified locked connection."""

from __future__ import annotations

import os
import shutil
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

import duckdb
from pydantic import BaseModel, ConfigDict, Field

from app.ingest.filenames import csv_filename
from app.ingest.sniff import CsvReadConfig
from app.profiler.schemas import LoadedTable
from worker.sandbox import DUCKDB_LOCKDOWN_SETTINGS, duckdb_lockdown_sql

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence


class DuckDBLimits(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, revalidate_instances="always"
    )

    threads: int = Field(default=2, gt=0, le=64)
    memory_mb: int = Field(default=256, gt=0, le=1_048_576)
    max_temp_mb: int = Field(default=512, gt=0, le=1_048_576)


class CsvTableInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")

    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,62}$")
    path: Path
    read_config: CsvReadConfig


@dataclass(frozen=True)
class ProfileDatabase:
    connection: duckdb.DuckDBPyConnection
    tables: tuple[LoadedTable, ...]
    path: Path


def _root(workspace: Path) -> Path:
    absolute = workspace.absolute()
    if any(path.is_symlink() for path in (absolute, *absolute.parents)):
        raise ValueError("DuckDB workspace cannot contain symlinks")
    if any(char in str(absolute) for char in "*?[]{}"):
        raise ValueError("DuckDB workspace cannot contain glob patterns")
    if not absolute.is_dir():
        raise ValueError("DuckDB workspace must be an existing directory")
    return absolute.resolve(strict=True)


def _local_path(root: Path, path: Path) -> Path:
    candidate = path if path.is_absolute() else root / path
    if ".." in candidate.parts or not candidate.is_relative_to(root):
        raise ValueError("DuckDB paths must stay inside the workspace")
    if any(part.is_symlink() for part in (candidate, *candidate.parents)):
        raise ValueError("DuckDB paths cannot contain symlinks")
    if candidate.exists() and (not candidate.is_file() or candidate.stat().st_nlink != 1):
        raise ValueError("DuckDB files must be regular files without hard links")
    return candidate


@contextmanager
def _ownership(root: Path) -> Iterator[None]:
    if sys.platform != "linux":
        raise OSError("Private DuckDB execution requires Linux")
    import fcntl

    lock_path = _local_path(root, root / ".profile.lock")
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("The DuckDB workspace is already in use") from None
        yield
    finally:
        os.close(descriptor)


def _connect(root: Path, limits: DuckDBLimits, *, reopen: bool) -> duckdb.DuckDBPyConnection:
    database = _local_path(root, root / "profile.duckdb")
    for suffix in (".wal", ".wal.checkpoint", ".wal.recovery"):
        _local_path(root, root / ("profile.duckdb" + suffix))
    if database.exists() != reopen:
        raise ValueError("Create requires a fresh database; reopen requires an existing database")
    temp = root / "duckdb-tmp"
    if temp.is_symlink() or (temp.exists() and not temp.is_dir()):
        raise ValueError("DuckDB scratch must be a workspace directory without a symlink")
    temp.mkdir(mode=0o700, exist_ok=True)
    for entry in temp.rglob("*"):
        if entry.is_symlink() or (entry.is_file() and entry.stat().st_nlink != 1):
            raise ValueError("DuckDB scratch cannot contain symlinks or hard links")
    return duckdb.connect(
        str(database),
        config={
            "threads": str(limits.threads),
            "memory_limit": f"{limits.memory_mb}MiB",
            "temp_directory": str(temp),
            "max_temp_directory_size": f"{limits.max_temp_mb}MiB",
            "enable_external_access": "true",
            "autoinstall_known_extensions": "false",
            "autoload_known_extensions": "false",
        },
    )


def _seal(connection: duckdb.DuckDBPyConnection, root: Path) -> None:
    connection.execute(
        "SET allowed_paths = []; SET allowed_directories = []; SET allowed_configs = []"
    )
    connection.execute(duckdb_lockdown_sql())
    for name, expected in DUCKDB_LOCKDOWN_SETTINGS.items():
        row = connection.execute("SELECT current_setting(?)", [name]).fetchone()
        if row != (expected == "true",):
            raise RuntimeError("DuckDB lockdown verification failed")
    expected_exceptions = {
        "allowed_paths": sorted(
            str(root / ("profile.duckdb" + suffix))
            for suffix in ("", ".wal", ".wal.checkpoint", ".wal.recovery")
        ),
        "allowed_directories": [str(root / "duckdb-tmp") + "/"],
        "allowed_configs": [],
    }
    for name, paths in expected_exceptions.items():
        actual = connection.execute("SELECT current_setting(?)", [name]).fetchone()
        if actual is None or sorted(actual[0]) != sorted(paths):
            raise RuntimeError("DuckDB lockdown exceptions do not match private scratch")


def _load(
    connection: duckdb.DuckDBPyConnection, root: Path, sources: Sequence[CsvTableInput]
) -> tuple[LoadedTable, ...]:
    validated = [CsvTableInput.model_validate(source) for source in sources]
    if not validated or len({source.name for source in validated}) != len(validated):
        raise ValueError("CSV inputs require distinct table names and at least one source")
    paths = [_local_path(root, source.path) for source in validated]
    if len(set(paths)) != len(paths):
        raise ValueError("CSV input paths must be distinct")
    for path in paths:
        csv_filename(path.name)
        if not path.is_file():
            raise ValueError("CSV inputs must be existing workspace files")
    tables: list[LoadedTable] = []
    with TemporaryDirectory(prefix="csv-load-", dir=root) as directory:
        for index, (source, path) in enumerate(zip(validated, paths, strict=True)):
            normalized = Path(directory) / f"source-{index}.csv"
            with (
                path.open("r", encoding=source.read_config.encoding, newline="") as original,
                normalized.open("w", encoding="utf-8", newline="") as target,
            ):
                shutil.copyfileobj(original, target, length=64 * 1024)
            config = CsvReadConfig.model_validate(
                {**source.read_config.model_dump(), "encoding": "utf-8"}
            )
            connection.read_csv(
                str(normalized),
                delimiter=config.delimiter,
                quotechar=config.quote,
                escapechar=config.escape,
                header=config.has_header,
                skiprows=config.skip_rows,
                na_values=config.null_tokens,
                all_varchar=True,
                date_format=config.date_format,
                timestamp_format=config.timestamp_format,
            ).create(source.name)
            tables.append(LoadedTable(name=source.name, source_file=path.name))
    return tuple(tables)


@contextmanager
def create_profile_database(
    workspace: Path,
    sources: Sequence[CsvTableInput],
    *,
    limits: DuckDBLimits | None = None,
) -> Iterator[ProfileDatabase]:
    """Load confirmed CSV inputs as VARCHAR tables, then lock before yielding.

    Only trusted worker code may call the loader. The caller owns manifest and
    hash verification and supplies files already staged inside a private attempt.
    A failed attempt is retained for inspection; retry uses a new workspace.
    """
    root = _root(workspace)
    budget = DuckDBLimits.model_validate(limits or DuckDBLimits())
    with _ownership(root):
        connection = _connect(root, budget, reopen=False)
        try:
            tables = _load(connection, root, sources)
            _seal(connection, root)
            yield ProfileDatabase(connection, tables, root / "profile.duckdb")
        finally:
            connection.close()


@contextmanager
def reopen_profile_database(
    workspace: Path, *, limits: DuckDBLimits | None = None
) -> Iterator[ProfileDatabase]:
    """Reapply policy on every open; security settings are not persisted in the file.

    Resource and scratch settings require trusted initialization with external
    access enabled. No caller SQL runs before sealing. Table source metadata must
    come from the verified manifest; reopening does not reconstruct that metadata.
    """
    root = _root(workspace)
    budget = DuckDBLimits.model_validate(limits or DuckDBLimits())
    with _ownership(root):
        connection = _connect(root, budget, reopen=True)
        try:
            _seal(connection, root)
            yield ProfileDatabase(connection, (), root / "profile.duckdb")
        finally:
            connection.close()
