"""Verify the real database policy in a child with resource limits."""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    backend = Path("/app") if Path("/app/worker").is_dir() else Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(backend))
    import duckdb

    from app.ingest.sniff import CsvReadConfig
    from worker.duckdb_runtime import (
        CsvTableInput,
        create_profile_database,
        reopen_profile_database,
    )

    workspace = Path(sys.argv[1])
    source = workspace / "customers.csv"
    source.write_text("id,name\n00001,Alice\n00002,Bob\n", encoding="utf-8")
    with create_profile_database(
        workspace, [CsvTableInput(name="customers", path=source, read_config=CsvReadConfig())]
    ) as database:
        if database.connection.execute("SELECT min(id), count(*) FROM customers").fetchone() != (
            "00001",
            2,
        ):
            raise RuntimeError("Materialized statistics failed")
        try:
            database.connection.execute("COPY customers TO 'forbidden.csv'")
        except duckdb.PermissionException:
            pass
        else:
            raise RuntimeError("External file write was permitted")
    with reopen_profile_database(workspace) as database:
        try:
            database.connection.execute("SET enable_external_access = true")
        except duckdb.InvalidInputException:
            pass
        else:
            raise RuntimeError("Configuration was unlocked after reopen")
    print("duckdb-lockdown-ok")


if __name__ == "__main__":
    main()
