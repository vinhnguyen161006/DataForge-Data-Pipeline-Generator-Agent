import argparse
import json
import platform
from datetime import UTC, datetime
from pathlib import Path

import duckdb


def positive_int(value: str) -> int:
    """Parse a strictly positive integer."""
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("Value must be positive")
    return parsed


def parse_args() -> argparse.Namespace:
    """Read reproducible experiment settings."""
    parser = argparse.ArgumentParser(
        description="Prepare a DuckDB profiling experiment."
    )
    parser.add_argument("--rows", type=positive_int, default=1_000_000)
    parser.add_argument("--threads", type=positive_int, default=1)
    parser.add_argument("--memory-limit", default="512MB")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("../data/spikes/duckdb/e1"),
    )
    return parser.parse_args()


def main() -> None:
    """Validate DuckDB execution and save environment metadata."""
    args = parse_args()

    with duckdb.connect(
        database=":memory:",
        config={
            "threads": args.threads,
            "memory_limit": args.memory_limit,
        },
    ) as connection:
        settings = connection.execute(
            "SELECT current_setting('threads'), "
            "current_setting('memory_limit')"
        ).fetchone()
        if settings is None:
            raise RuntimeError("DuckDB did not return its settings")

        result = connection.execute("SELECT 1 AS ready").fetchall()
        if result != [(1,)]:
            raise RuntimeError("DuckDB readiness query failed")

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
            "rows_created": None,
            "profiling_status": "not_started",
            "measurements": None,
        }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    destination = args.output_dir / "environment.json"
    serialized = json.dumps(metadata, indent=2)
    destination.write_text(serialized + "\n", encoding="utf-8")

    print(serialized)
    print(f"Saved metadata to {destination.resolve()}")


if __name__ == "__main__":
    main()