"""Exercise isolation and denied operations against the pinned DuckDB engine."""

from __future__ import annotations

import sys
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
from typing import TYPE_CHECKING

import duckdb
import pytest

from app.ingest.sniff import CsvReadConfig
from worker.duckdb_runtime import (
    CsvTableInput,
    DuckDBLimits,
    create_profile_database,
    reopen_profile_database,
)
from worker.sandbox import DUCKDB_LOCKDOWN_SETTINGS, Limits, duckdb_lockdown_sql, run_sandboxed

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux private DuckDB workspace")


@pytest.fixture
def source(tmp_path: Path) -> CsvTableInput:
    path = tmp_path / "customers.csv"
    path.write_text("id,name\n00001,Alice\n00002,\n", encoding="utf-8")
    return CsvTableInput(name="customers", path=path, read_config=CsvReadConfig())


@pytest.fixture
def locked(tmp_path: Path, source: CsvTableInput) -> Iterator[duckdb.DuckDBPyConnection]:
    with create_profile_database(tmp_path, [source]) as database:
        yield database.connection


def test_runtime_matches_dependency_lock() -> None:
    import tomllib

    backend = Path(__file__).resolve().parents[2]
    project = tomllib.loads((backend / "pyproject.toml").read_text())
    packages = tomllib.loads((backend / "uv.lock").read_text())["package"]
    for name in ("duckdb", "dbt-core", "dbt-duckdb"):
        installed = version(name)
        assert f"{name}=={installed}" in project["project"]["dependencies"]
        assert any(item["name"] == name and item["version"] == installed for item in packages)


def test_renderer_orders_configuration_lock_last() -> None:
    statements = duckdb_lockdown_sql().splitlines()
    assert statements[-1] == "SET lock_configuration = true;"
    assert len(statements) == len(DUCKDB_LOCKDOWN_SETTINGS)
    assert set(statements) == {
        f"SET {name} = {value};" for name, value in DUCKDB_LOCKDOWN_SETTINGS.items()
    }


def test_loaded_tables_support_statistics_and_preserve_identifiers(
    tmp_path: Path, source: CsvTableInput
) -> None:
    with create_profile_database(tmp_path, [source]) as database:
        assert database.path == tmp_path / "profile.duckdb"
        assert [(item.name, item.source_file) for item in database.tables] == [
            ("customers", "customers.csv")
        ]
        assert database.connection.execute(
            "SELECT count(*), count(name), count(DISTINCT id), min(id), typeof(min(id)) "
            "FROM customers"
        ).fetchone() == (2, 1, 2, "00001", "VARCHAR")
        assert not list(tmp_path.glob("csv-load-*"))
        source.path.unlink()
        assert database.connection.execute("SELECT count(*) FROM customers").fetchone() == (2,)


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT * FROM read_csv('outside.csv')",
        "SELECT * FROM read_text('outside.txt')",
        "SELECT * FROM read_parquet('outside.parquet')",
        "COPY customers TO 'export.csv'",
        "COPY customers FROM 'outside.csv'",
        "ATTACH 'other.duckdb' AS other",
        "INSTALL '/tmp/lockdown-probe.duckdb_extension'",
        "LOAD '/tmp/lockdown-probe.duckdb_extension'",
    ],
)
def test_external_operations_are_denied(locked: duckdb.DuckDBPyConnection, statement: str) -> None:
    with pytest.raises(duckdb.PermissionException):
        locked.execute(statement)


@pytest.mark.parametrize(
    "statement",
    [
        "SET enable_external_access = true",
        "SET autoinstall_known_extensions = true",
        "SET autoload_known_extensions = true",
        "SET lock_configuration = false",
        "SET threads = 4",
        "SET memory_limit = '1GiB'",
        "SET temp_directory = '/tmp'",
        "SET allowed_paths = ['/tmp/secret.csv']",
        "SET allowed_directories = ['/tmp']",
        "SET allowed_configs = ['enable_external_access']",
    ],
)
def test_configuration_cannot_be_weakened(
    locked: duckdb.DuckDBPyConnection, statement: str
) -> None:
    with pytest.raises(duckdb.InvalidInputException, match="locked"):
        locked.execute(statement)


def test_original_source_is_also_unreadable_after_lockdown(
    locked: duckdb.DuckDBPyConnection, source: CsvTableInput
) -> None:
    with pytest.raises(duckdb.PermissionException):
        locked.execute("SELECT * FROM read_csv(?)", [str(source.path)])


def test_cursor_inherits_policy(locked: duckdb.DuckDBPyConnection) -> None:
    cursor = locked.cursor()
    try:
        assert cursor.execute(
            "SELECT current_setting('enable_external_access'), "
            "current_setting('lock_configuration')"
        ).fetchone() == (False, True)
        with pytest.raises(duckdb.PermissionException):
            cursor.execute("COPY customers TO 'export.csv'")
    finally:
        cursor.close()


def test_reopen_reapplies_nonpersistent_policy(tmp_path: Path, source: CsvTableInput) -> None:
    with create_profile_database(tmp_path, [source]):
        pass
    with duckdb.connect(str(tmp_path / "profile.duckdb")) as plain:
        assert plain.execute(
            "SELECT current_setting('enable_external_access'), "
            "current_setting('lock_configuration')"
        ).fetchone() == (True, False)
    source.path.unlink()
    with reopen_profile_database(tmp_path) as database:
        assert database.connection.execute("SELECT count(*) FROM customers").fetchone() == (2,)
        with pytest.raises(duckdb.PermissionException):
            database.connection.execute("COPY customers TO 'export.csv'")
        with pytest.raises(duckdb.InvalidInputException, match="locked"):
            database.connection.execute("SET lock_configuration = false")


def test_resource_configuration_is_applied_before_lock(
    tmp_path: Path, source: CsvTableInput
) -> None:
    with create_profile_database(
        tmp_path, [source], limits=DuckDBLimits(threads=1, memory_mb=128, max_temp_mb=64)
    ) as database:
        assert database.connection.execute(
            "SELECT current_setting('threads'), current_setting('memory_limit'), "
            "current_setting('max_temp_directory_size'), current_setting('temp_directory')"
        ).fetchone() == (1, "128.0 MiB", "64.0 MiB", str(tmp_path / "duckdb-tmp"))
        for name in ("allowed_configs",):
            assert database.connection.execute("SELECT current_setting(?)", [name]).fetchone() == (
                [],
            )


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "utf-16", "latin-1", "cp1252"])
def test_confirmed_encoding_delimiter_skip_and_nulls_are_used(
    tmp_path: Path, encoding: str
) -> None:
    path = tmp_path / "source['quoted'].csv"
    path.write_text('ignored\ncode;label\n00001;"caf\u00e9;shop"\n00002;NULL\n', encoding=encoding)
    config = CsvReadConfig(
        encoding=encoding, delimiter=";", skip_rows=1, null_tokens=["NULL"], has_header=True
    )
    before = sha256(path.read_bytes()).hexdigest()
    with create_profile_database(
        tmp_path, [CsvTableInput(name="labels", path=path, read_config=config)]
    ) as database:
        assert database.connection.execute("SELECT * FROM labels ORDER BY code").fetchall() == [
            ("00001", "caf\u00e9;shop"),
            ("00002", None),
        ]
    assert config.encoding == encoding
    assert sha256(path.read_bytes()).hexdigest() == before


def test_headerless_input_and_custom_quote_are_used(tmp_path: Path) -> None:
    path = tmp_path / "rows.csv"
    path.write_text("001|'value|one'\n002|'value|two'\n", encoding="utf-8")
    config = CsvReadConfig(delimiter="|", quote="'", escape="'", has_header=False)
    with create_profile_database(
        tmp_path, [CsvTableInput(name="rows", path=path, read_config=config)]
    ) as database:
        assert database.connection.execute("SELECT * FROM rows").fetchall() == [
            ("001", "value|one"),
            ("002", "value|two"),
        ]


@pytest.mark.parametrize("name", ['x"; DROP TABLE customers; --', "../customers", "Customers", ""])
def test_untrusted_table_names_are_rejected(source: CsvTableInput, name: str) -> None:
    with pytest.raises(ValueError, match="name"):
        CsvTableInput(name=name, path=source.path, read_config=source.read_config)


@pytest.mark.parametrize("field", ["threads", "memory_mb", "max_temp_mb"])
@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_invalid_database_budgets_are_rejected(field: str, value: object) -> None:
    with pytest.raises(ValueError, match=field):
        DuckDBLimits.model_validate({field: value})


def test_mutated_budget_is_revalidated(tmp_path: Path, source: CsvTableInput) -> None:
    invalid = DuckDBLimits().model_copy(update={"threads": 0})
    with (
        pytest.raises(ValueError, match="threads"),
        create_profile_database(tmp_path, [source], limits=invalid),
    ):
        pytest.fail("An invalid budget reached the profiler")


def test_only_one_owner_can_use_an_attempt(tmp_path: Path, source: CsvTableInput) -> None:
    with (
        create_profile_database(tmp_path, [source]),
        pytest.raises(RuntimeError, match="already in use"),
        reopen_profile_database(tmp_path),
    ):
        pytest.fail("A second owner acquired the workspace")
    with reopen_profile_database(tmp_path) as database:
        assert database.connection.execute("SELECT count(*) FROM customers").fetchone() == (2,)


def test_existing_database_cannot_be_overwritten(tmp_path: Path, source: CsvTableInput) -> None:
    with create_profile_database(tmp_path, [source]):
        pass
    with pytest.raises(ValueError, match="fresh"), create_profile_database(tmp_path, [source]):
        pytest.fail("An existing attempt was overwritten")


def test_reopen_does_not_create_an_empty_database(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="existing"), reopen_profile_database(tmp_path):
        pytest.fail("A missing database was created")
    assert not (tmp_path / "profile.duckdb").exists()


@pytest.mark.parametrize("relative", ["../outside.csv", "/outside.csv"])
def test_input_cannot_escape_workspace(tmp_path: Path, relative: str) -> None:
    source = CsvTableInput(name="outside", path=Path(relative), read_config=CsvReadConfig())
    with pytest.raises(ValueError, match="inside"), create_profile_database(tmp_path, [source]):
        pytest.fail("An outside path reached the loader")


@pytest.mark.parametrize("target", ["source", "database", "scratch", "lock", "workspace"])
def test_symlink_paths_are_rejected(tmp_path: Path, source: CsvTableInput, target: str) -> None:
    workspace = tmp_path
    if target == "source":
        link = tmp_path / "linked.csv"
        link.symlink_to(source.path)
        source = CsvTableInput(name="linked", path=link, read_config=CsvReadConfig())
    elif target == "workspace":
        workspace = tmp_path / "linked-workspace"
        workspace.symlink_to(tmp_path, target_is_directory=True)
    else:
        name = {"database": "profile.duckdb", "scratch": "duckdb-tmp", "lock": ".profile.lock"}[
            target
        ]
        (tmp_path / name).symlink_to(source.path)
    with pytest.raises(ValueError, match="symlink"), create_profile_database(workspace, [source]):
        pytest.fail("A symlink reached DuckDB")


def test_hardlinked_database_is_rejected(tmp_path: Path, source: CsvTableInput) -> None:
    with create_profile_database(tmp_path, [source]):
        pass
    (tmp_path / "shared.duckdb").hardlink_to(tmp_path / "profile.duckdb")
    with pytest.raises(ValueError, match="hard links"), reopen_profile_database(tmp_path):
        pytest.fail("A hardlinked database was opened")


@pytest.mark.parametrize("duplicate", ["names", "paths", "empty"])
def test_duplicate_or_empty_inputs_are_rejected(
    tmp_path: Path, source: CsvTableInput, duplicate: str
) -> None:
    sources = [source, source]
    if duplicate == "paths":
        sources = [
            source,
            CsvTableInput(name="other", path=source.path, read_config=CsvReadConfig()),
        ]
    if duplicate == "empty":
        sources = []
    with pytest.raises(ValueError, match="distinct"), create_profile_database(tmp_path, sources):
        pytest.fail("Ambiguous inputs reached the profiler")


def test_loader_failure_closes_connection_releases_lock_and_removes_transcoding_files(
    tmp_path: Path, source: CsvTableInput
) -> None:
    source.path.write_bytes(b"id,name\n1,\xff\n")
    with pytest.raises(UnicodeDecodeError), create_profile_database(tmp_path, [source]):
        pytest.fail("Invalid encoded data reached the profiler")
    assert not list(tmp_path.glob("csv-load-*"))
    with reopen_profile_database(tmp_path) as database:
        assert database.connection.execute("SELECT 1").fetchone() == (1,)


def test_profiler_exception_still_closes_connection(tmp_path: Path, source: CsvTableInput) -> None:
    with (
        pytest.raises(RuntimeError, match="profile failed"),
        create_profile_database(tmp_path, [source]) as database,
    ):
        raise RuntimeError("profile failed")
    with pytest.raises(duckdb.ConnectionException, match="closed"):
        database.connection.execute("SELECT 1")
    with reopen_profile_database(tmp_path) as reopened:
        assert reopened.connection.execute("SELECT count(*) FROM customers").fetchone() == (2,)


def test_two_active_workspaces_have_distinct_databases(tmp_path: Path) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    one = first / "one.csv"
    two = second / "two.csv"
    one.write_text("id\n001\n", encoding="utf-8")
    two.write_text("id\n002\n003\n", encoding="utf-8")
    with (
        create_profile_database(
            first, [CsvTableInput(name="one", path=one, read_config=CsvReadConfig())]
        ) as left,
        create_profile_database(
            second, [CsvTableInput(name="two", path=two, read_config=CsvReadConfig())]
        ) as right,
    ):
        assert left.path != right.path
        assert left.connection.execute("SELECT * FROM one").fetchall() == [("001",)]
        assert right.connection.execute("SELECT * FROM two").fetchall() == [("002",), ("003",)]
        with pytest.raises(duckdb.CatalogException):
            left.connection.execute("SELECT * FROM two")
        with pytest.raises(duckdb.CatalogException):
            right.connection.execute("SELECT * FROM one")


def test_lockdown_runs_inside_resource_limited_child(tmp_path: Path) -> None:
    probe = Path(__file__).resolve().parents[1] / "fixtures/sandbox/duckdb_lockdown_probe.py"
    result = run_sandboxed(
        [sys.executable, "-I", str(probe), str(tmp_path)],
        workspace=tmp_path,
        limits=Limits(
            timeout_seconds=20,
            cpu_seconds=10,
            memory_mb=2048,
            max_file_mb=32,
            max_processes=4096,
        ),
    )
    assert not result.timed_out
    assert not result.output_limited
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "duckdb-lockdown-ok"


def test_private_engine_exceptions_are_exact(
    locked: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    allowed = locked.execute("SELECT current_setting('allowed_paths')").fetchone()
    assert allowed is not None
    assert set(allowed[0]) == {
        str(tmp_path / ("profile.duckdb" + suffix))
        for suffix in ("", ".wal", ".wal.checkpoint", ".wal.recovery")
    }
    assert locked.execute(
        "SELECT current_setting('allowed_directories'), current_setting('allowed_configs')"
    ).fetchone() == ([str(tmp_path / "duckdb-tmp") + "/"], [])


def test_temp_exception_does_not_include_sibling_directory(
    locked: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    sibling = tmp_path / "duckdb-tmp-neighbor"
    sibling.mkdir()
    secret = sibling / "private.csv"
    secret.write_text("secret\nfixture-only\n", encoding="utf-8")
    with pytest.raises(duckdb.PermissionException):
        locked.execute("SELECT * FROM read_csv(?)", [str(secret)])


@pytest.mark.parametrize("suffix", [".wal", ".wal.checkpoint", ".wal.recovery"])
def test_internal_wal_symlinks_are_rejected(
    tmp_path: Path, source: CsvTableInput, suffix: str
) -> None:
    (tmp_path / ("profile.duckdb" + suffix)).symlink_to(source.path)
    with pytest.raises(ValueError, match="symlink"), create_profile_database(tmp_path, [source]):
        pytest.fail("An internal WAL symlink reached DuckDB")


def test_scratch_cannot_hide_symlinks(tmp_path: Path, source: CsvTableInput) -> None:
    scratch = tmp_path / "duckdb-tmp"
    scratch.mkdir()
    (scratch / "hidden.csv").symlink_to(source.path)
    with pytest.raises(ValueError, match="symlinks"), create_profile_database(tmp_path, [source]):
        pytest.fail("An unsafe scratch file reached DuckDB")


def test_glob_workspace_is_rejected(tmp_path: Path, source: CsvTableInput) -> None:
    workspace = tmp_path / "attempt[1]"
    workspace.mkdir()
    with pytest.raises(ValueError, match="glob"), create_profile_database(workspace, [source]):
        pytest.fail("A glob workspace reached the CSV loader")


def test_unverified_lockdown_never_reaches_profiler(
    tmp_path: Path, source: CsvTableInput, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "worker.duckdb_runtime.duckdb_lockdown_sql", lambda: "SET enable_external_access = false"
    )
    with (
        pytest.raises(RuntimeError, match="verification"),
        create_profile_database(tmp_path, [source]),
    ):
        pytest.fail("An unlocked connection reached the profiler")
    monkeypatch.undo()
    with reopen_profile_database(tmp_path) as database:
        assert database.connection.execute("SELECT count(*) FROM customers").fetchone() == (2,)
