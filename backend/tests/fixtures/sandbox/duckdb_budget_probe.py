"""Small real DuckDB workload under the worker's memory budget and Docker cgroup."""

import json
import sys
import tempfile
from pathlib import Path


def main() -> None:
    sys.path.insert(0, "/app")
    from worker.sandbox import Limits, run_sandboxed

    source = """
import json, resource, duckdb
from pathlib import Path
with duckdb.connect("budget.duckdb", config={
    "threads": 2, "memory_limit": "512MiB", "temp_directory": "tmp",
}) as connection:
    total = connection.execute("SELECT sum(i) FROM range(10000) t(i)").fetchone()[0]
    threads = connection.execute("SELECT current_setting('threads')").fetchone()[0]
print(json.dumps({
    "duckdb_version": duckdb.__version__,
    "total": total,
    "threads": threads,
    "address_space": resource.getrlimit(resource.RLIMIT_AS),
    "database_created": Path("budget.duckdb").is_file(),
}))
"""
    with tempfile.TemporaryDirectory() as directory:
        result = run_sandboxed(
            [sys.executable, "-I", "-c", source],
            workspace=Path(directory),
            limits=Limits(
                timeout_seconds=10,
                memory_mb=2048,
                cpu_seconds=5,
                max_file_mb=32,
                max_open_files=128,
                max_processes=64,
            ),
        )
        assert result.returncode == 0, result.stderr
        assert not result.timed_out
        data = json.loads(result.stdout)
        assert data["duckdb_version"] == "1.5.5"
        assert data["total"] == 49995000
        assert data["threads"] == 2
        assert data["address_space"] == [2 * 1024**3, 2 * 1024**3]
        assert data["database_created"]
        print(json.dumps(data))


if __name__ == "__main__":
    main()
