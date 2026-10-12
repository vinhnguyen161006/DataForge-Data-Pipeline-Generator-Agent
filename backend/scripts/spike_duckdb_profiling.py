import argparse
import json
import platform
from datetime import UTC, datetime
from pathlib import Path

import duckdb

CREATE_SAMPLE_SQL = """
CREATE TABLE sample AS
SELECT
    i AS id,
    i % 10 AS group_id,
    i % 1000 + 1 AS amount
FROM range(?) AS source(i)
""".strip()

SAMPLE_QUERY = """
SELECT
    group_id,
    COUNT(*) AS matched_rows,
    SUM(amount) AS total_amount
FROM sample
WHERE amount >= 501
GROUP BY group_id
ORDER BY total_amount DESC, group_id ASC
""".strip()


def positive_int(value: str) -> int:
    """Parse a strictly positive integer."""
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("Value must be positive")
    return parsed


def parse_args() -> argparse.Namespace:
    """Read reproducible experiment settings."""
    parser = argparse.ArgumentParser(
        description="Create sample data and capture DuckDB query plans."
    )
    parser.add_argument("--rows", type=positive_int, default=1_000_000)
    parser.add_argument("--threads", type=positive_int, default=1)
    parser.add_argument("--memory-limit", default="512MB")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("../data/spikes/duckdb/e2"),
    )
    return parser.parse_args()


def build_sample(
    connection: duckdb.DuckDBPyConnection,
    rows: int,
) -> int:
    """Materialize deterministic data and verify its row count."""
    connection.execute(CREATE_SAMPLE_SQL, [rows])

    result = connection.execute("SELECT COUNT(*) FROM sample").fetchone()
    if result is None:
        raise RuntimeError("DuckDB did not return the sample row count")

    actual_rows = int(result[0])
    if actual_rows != rows:
        raise RuntimeError("Sample row count does not match the requested size")

    return actual_rows


def save_plan(
    connection: duckdb.DuckDBPyConnection,
    statement: str,
    output_dir: Path,
    name: str,
) -> None:
    """Save every EXPLAIN result row in JSON and readable text."""
    rows = connection.execute(statement).fetchall()
    if not rows:
        raise RuntimeError("DuckDB did not return an explain plan")

    entries = [
        {
            "explain_key": str(row[0]),
            "explain_value": str(row[1]),
        }
        for row in rows
    ]

    serialized = json.dumps(entries, ensure_ascii=False, indent=2)
    (output_dir / f"{name}.json").write_text(
        serialized + "\n",
        encoding="utf-8",
    )

    rendered = "\n\n".join(f"{entry['explain_key']}\n{entry['explain_value']}" for entry in entries)
    (output_dir / f"{name}.txt").write_text(
        rendered + "\n",
        encoding="utf-8",
    )


def main() -> None:
    """Build sample data, capture query plans, and save runtime metadata."""
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    with duckdb.connect(
        database=":memory:",
        config={
            "threads": args.threads,
            "memory_limit": args.memory_limit,
        },
    ) as connection:
        settings = connection.execute(
            "SELECT current_setting('threads'), current_setting('memory_limit')"
        ).fetchone()
        if settings is None:
            raise RuntimeError("DuckDB did not return its settings")

        result = connection.execute("SELECT 1 AS ready").fetchall()
        if result != [(1,)]:
            raise RuntimeError("DuckDB readiness query failed")

        actual_rows = build_sample(connection, args.rows)

        (args.output_dir / "query.sql").write_text(
            SAMPLE_QUERY + "\n",
            encoding="utf-8",
        )

        save_plan(
            connection,
            "EXPLAIN " + SAMPLE_QUERY,
            args.output_dir,
            "explain",
        )
        save_plan(
            connection,
            "EXPLAIN ANALYZE " + SAMPLE_QUERY,
            args.output_dir,
            "explain_analyze",
        )

        query_result = connection.execute(SAMPLE_QUERY).fetchall()
        (args.output_dir / "result.json").write_text(
            json.dumps(query_result, indent=2) + "\n",
            encoding="utf-8",
        )

        metadata: dict[str, object] = {
            "recorded_at_utc": datetime.now(UTC).isoformat(),
            "duckdb_version": duckdb.__version__,
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "architecture": platform.machine(),
            "database": ":memory:",
            "threads_requested": args.threads,
            "threads_effective": settings[0],
            "memory_limit_requested": args.memory_limit,
            "memory_limit_effective": settings[1],
            "rows_planned": args.rows,
            "rows_created": actual_rows,
            "result_rows": len(query_result),
            "profiling_status": "explain_analyze_completed",
            "measurements": None,
        }

    destination = args.output_dir / "environment.json"
    serialized = json.dumps(metadata, indent=2)
    destination.write_text(serialized + "\n", encoding="utf-8")

    print(serialized)
    print(f"Saved metadata to {destination.resolve()}")


if __name__ == "__main__":
    main()
