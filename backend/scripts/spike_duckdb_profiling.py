import argparse
import hashlib
import json
import os
import platform
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from time import perf_counter
from uuid import uuid4

import duckdb
from pydantic import BaseModel, ConfigDict, Field

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

MEMORY_PRESSURE_QUERY = """
SELECT SUM(group_amount) AS checksum
FROM (
    SELECT id, SUM(amount) AS group_amount
    FROM sample
    GROUP BY id
) AS grouped
""".strip()

EXPLICIT_METRICS = dict.fromkeys(
    (
        "QUERY_NAME",
        "LATENCY",
        "ROWS_RETURNED",
        "CUMULATIVE_ROWS_SCANNED",
        "SYSTEM_PEAK_BUFFER_MEMORY",
        "OPERATOR_NAME",
        "OPERATOR_TYPE",
        "OPERATOR_CARDINALITY",
        "OPERATOR_ROWS_SCANNED",
        "OPERATOR_TIMING",
        "EXTRA_INFO",
    ),
    "true",
)

REQUIRED_METRICS = (
    "latency",
    "cumulative_rows_scanned",
    "system_peak_buffer_memory",
)


class ProfileMetrics(BaseModel):
    """Validate available root metrics without replacing missing values."""

    model_config = ConfigDict(strict=True)

    query_name: str
    latency: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    rows_returned: int | None = Field(default=None, ge=0)
    cumulative_rows_scanned: int | None = Field(default=None, ge=0)
    system_peak_buffer_memory: int | None = Field(default=None, ge=0)


class ScanMetrics(BaseModel):
    """Retain scan metrics and their exact path in the original JSON."""

    model_config = ConfigDict(strict=True)

    json_path: str
    operator_name: str | None = None
    operator_type: str | None = None
    operator_cardinality: int | None = Field(default=None, ge=0)
    operator_rows_scanned: int | None = Field(default=None, ge=0)
    operator_timing: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    extra_info: dict[str, object] = Field(default_factory=dict)


class ProfileSample(BaseModel):
    """Describe one profiled execution and its evidence."""

    label: str
    recorded_at_utc: str
    process_id: int
    duckdb_version: str
    query_sha256: str
    profile_path: str
    query_path: str
    metric_mode: str
    python_elapsed_seconds: float
    result_rows: int
    result_sha256: str
    metrics: ProfileMetrics
    scans: list[ScanMetrics]
    missing_metrics: list[str]


def positive_int(value: str) -> int:
    """Parse a strictly positive integer."""
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("Value must be positive")
    return parsed


def parse_args() -> argparse.Namespace:
    """Read reproducible experiment settings."""
    parser = argparse.ArgumentParser(
        description="Capture DuckDB query profiles and investigate buffer memory."
    )
    parser.add_argument("--rows", type=positive_int, default=1_000_000)
    parser.add_argument("--threads", type=positive_int, default=1)
    parser.add_argument("--memory-limit", default="512MB")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--database",
        type=Path,
        help="Profile an existing sample database instead of generating new data.",
    )
    parser.add_argument(
        "--memory-study",
        action="store_true",
        help="Compare fresh, reused, pressured, and reopened connections.",
    )
    parser.add_argument(
        "--explicit-metrics",
        action="store_true",
        help="Request the required metrics through custom_profiling_settings.",
    )
    parser.add_argument(
        "--benchmark",
        action="store_true",
        help="Run warmup and repeated measurements on a separate connection.",
    )
    parser.add_argument("--warmup", type=positive_int, default=1)
    parser.add_argument("--repeats", type=positive_int, default=5)
    args = parser.parse_args()
    if args.output_dir is None:
        args.output_dir = Path(
            "../data/spikes/duckdb/e4" if args.benchmark else "../data/spikes/duckdb/e3"
        )
    return args


def write_json(path: Path, value: object) -> None:
    """Save a UTF-8 JSON artifact."""
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_json_object(path: Path) -> dict[str, object]:
    """Read a JSON object while preserving the original metric values."""
    raw: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("DuckDB profile root must be a JSON object")
    return {str(key): value for key, value in raw.items()}


def sample_row_count(connection: duckdb.DuckDBPyConnection) -> int:
    """Read the source row count outside the profiled query."""
    result = connection.execute("SELECT COUNT(*) FROM sample").fetchone()
    if result is None:
        raise RuntimeError("DuckDB did not return the sample row count")
    return int(result[0])


def build_sample(connection: duckdb.DuckDBPyConnection, rows: int) -> int:
    """Materialize deterministic data and verify its row count."""
    connection.execute(CREATE_SAMPLE_SQL, [rows])
    actual_rows = sample_row_count(connection)
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
    entries = [{"explain_key": str(row[0]), "explain_value": str(row[1])} for row in rows]
    write_json(output_dir / f"{name}.json", entries)
    rendered = "\n\n".join(f"{entry['explain_key']}\n{entry['explain_value']}" for entry in entries)
    (output_dir / f"{name}.txt").write_text(rendered + "\n", encoding="utf-8")


def scan_metrics(node: dict[str, object], path: str = "$") -> list[ScanMetrics]:
    """Walk the original tree without adding parent and child scan totals."""
    found: list[ScanMetrics] = []
    name = node.get("operator_name")
    kind = node.get("operator_type")
    if (isinstance(name, str) and "SCAN" in name.upper()) or (
        isinstance(kind, str) and "SCAN" in kind.upper()
    ):
        found.append(ScanMetrics.model_validate(node | {"json_path": path}))

    children = node.get("children", [])
    if not isinstance(children, list):
        raise ValueError("DuckDB profile children must be a JSON array")
    for index, child in enumerate(children):
        if not isinstance(child, dict):
            raise ValueError("DuckDB profile child must be a JSON object")
        child_node = {str(key): value for key, value in child.items()}
        found.extend(scan_metrics(child_node, f"{path}.children[{index}]"))
    return found


def result_digest(value: object) -> str:
    """Fingerprint deterministic query results including their order."""
    encoded = json.dumps(value, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def capture_profile(
    connection: duckdb.DuckDBPyConnection,
    output_dir: Path,
    label: str,
    *,
    query: str = SAMPLE_QUERY,
    explicit_metrics: bool = False,
    expected_result_sha256: str | None = None,
) -> ProfileSample:
    """Fetch one query and snapshot its profile before executing more SQL."""
    profile_path = output_dir / f"profile-{label}.json"
    if profile_path.exists():
        raise FileExistsError("Profile output already exists")
    query_path = output_dir / f"query-{label}.sql"
    query_path.write_text(query + "\n", encoding="utf-8")

    destination = str(profile_path.resolve()).replace("'", "''")
    connection.execute("SET profiling_coverage = 'SELECT'")
    if explicit_metrics:
        settings_json = json.dumps(EXPLICIT_METRICS)
        connection.execute(f"PRAGMA custom_profiling_settings = '{settings_json}'")
    connection.execute("PRAGMA enable_profiling = 'json'")

    try:
        connection.execute(f"PRAGMA profiling_output = '{destination}'")
        started = perf_counter()
        result = connection.execute(query).fetchall()
        elapsed = perf_counter() - started
        if not profile_path.is_file():
            raise RuntimeError("DuckDB did not write the expected profile")

        profile_text = profile_path.read_text(encoding="utf-8")
        profile = load_json_object(profile_path)
        metrics = ProfileMetrics.model_validate(profile)
        expected_query = " ".join(query.split()).rstrip(";")
        observed_query = " ".join(metrics.query_name.split()).rstrip(";")
        if observed_query != expected_query:
            raise ValueError("DuckDB profile belongs to another query")
        if metrics.rows_returned is not None and metrics.rows_returned != len(result):
            raise ValueError("Profile row count does not match the fetched result")
        digest = result_digest(result)
        if expected_result_sha256 is not None and digest != expected_result_sha256:
            raise ValueError("Profiled result differs from the prepared reference")

        sample = ProfileSample(
            label=label,
            recorded_at_utc=datetime.now(UTC).isoformat(),
            process_id=os.getpid(),
            duckdb_version=duckdb.__version__,
            query_sha256=hashlib.sha256(query.encode("utf-8")).hexdigest(),
            profile_path=str(profile_path.resolve()),
            query_path=str(query_path.resolve()),
            metric_mode="explicit" if explicit_metrics else "default",
            python_elapsed_seconds=elapsed,
            result_rows=len(result),
            result_sha256=digest,
            metrics=metrics,
            scans=scan_metrics(profile),
            missing_metrics=[name for name in REQUIRED_METRICS if getattr(metrics, name) is None],
        )
    finally:
        connection.execute("PRAGMA disable_profiling")

    profile_path.write_text(profile_text, encoding="utf-8")
    write_json(output_dir / f"measurement-{label}.json", sample.model_dump())
    return sample


def memory_observations(samples: list[ProfileSample]) -> dict[str, object]:
    """Report observed peaks without claiming that retained state was reset."""
    peaks = {sample.label: sample.metrics.system_peak_buffer_memory for sample in samples}
    baseline = peaks.get("fresh")
    pressure = peaks.get("pressure")
    after = peaks.get("after-pressure")
    reopened = peaks.get("reopened")
    return {
        "memory_scope": "DuckDB buffer manager; not worker RSS or incremental query memory",
        "reset_status": "not_established",
        "peaks_bytes": peaks,
        "pressure_exceeded_fresh": (
            pressure > baseline if pressure is not None and baseline is not None else None
        ),
        "after_pressure_exceeded_fresh": (
            after > baseline if after is not None and baseline is not None else None
        ),
        "after_pressure_below_pressure": (
            after < pressure if after is not None and pressure is not None else None
        ),
        "reopened_below_after_pressure": (
            reopened < after if reopened is not None and after is not None else None
        ),
        "interpretation": (
            "Differences can reflect retained buffers and cache state. "
            "Equal peaks alone do not establish reset behavior. "
            "Compare a separate CLI process using the same database."
        ),
    }


def file_digest(path: Path) -> str:
    """Identify the database file outside the query timing window."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def benchmark_query(
    connection: duckdb.DuckDBPyConnection,
    output_dir: Path,
    *,
    warmup: int,
    repeats: int,
    explicit_metrics: bool,
    expected_result_sha256: str,
) -> tuple[dict[str, object], list[ProfileSample]]:
    """Exclude warmup and retain each repeated measurement on one connection."""
    if warmup < 1 or repeats < 1:
        raise ValueError("Warmup and repeats must be positive")

    warmup_samples: list[ProfileSample] = []
    for index in range(warmup):
        warmup_samples.append(
            capture_profile(
                connection,
                output_dir,
                f"benchmark-warmup-{index + 1}",
                explicit_metrics=explicit_metrics,
                expected_result_sha256=expected_result_sha256,
            )
        )
    write_json(
        output_dir / "benchmark-warmup.json",
        [sample.model_dump() for sample in warmup_samples],
    )

    measured: list[ProfileSample] = []
    for index in range(repeats):
        measured.append(
            capture_profile(
                connection,
                output_dir,
                f"benchmark-trial-{index + 1}",
                explicit_metrics=explicit_metrics,
                expected_result_sha256=expected_result_sha256,
            )
        )

    python_times = [sample.python_elapsed_seconds for sample in measured]
    latencies = [
        sample.metrics.latency for sample in measured if sample.metrics.latency is not None
    ]
    summary: dict[str, object] = {
        "schema_version": 1,
        "run_id": output_dir.name,
        "query_id": "sample-amount-groupby-v1",
        "query_sha256": measured[0].query_sha256,
        "result_sha256": measured[0].result_sha256,
        "warmup_count": warmup,
        "requested_repeats": repeats,
        "measured_count": len(measured),
        "latency_sample_count": len(latencies),
        "all_required_metrics_present": all(not sample.missing_metrics for sample in measured),
        "python_elapsed_samples_seconds": python_times,
        "duckdb_latency_samples_seconds": [sample.metrics.latency for sample in measured],
        "median_python_elapsed_seconds": median(python_times),
        "median_duckdb_latency_seconds": (median(latencies) if len(latencies) == repeats else None),
        "rows_scanned_samples": [sample.metrics.cumulative_rows_scanned for sample in measured],
        "peak_buffer_samples_bytes": [
            sample.metrics.system_peak_buffer_memory for sample in measured
        ],
        "missing_metrics_by_sample": {sample.label: sample.missing_metrics for sample in measured},
        "profile_paths": [sample.profile_path for sample in measured],
        "profiling_enabled": True,
        "metric_mode": "explicit" if explicit_metrics else "default",
        "connection_policy": "separate benchmark connection reused after warmup",
        "cache_policy": "connection warmed by warmup queries; OS cache uncontrolled",
        "timing_scope": (
            "execute plus fetch; excludes preparation, connection opening, JSON parsing"
        ),
        "memory_scope": "DuckDB buffer peak on a reused instance; not worker RSS",
        "buffer_peak_reset_status": "not_established",
    }
    write_json(
        output_dir / "benchmark-samples.json",
        [sample.model_dump() for sample in measured],
    )
    write_json(output_dir / "benchmark-summary.json", summary)
    return summary, measured


def handoff_record(
    output_dir: Path,
    database_path: Path,
    database_sha256: str,
    source_rows: int,
    config: dict[str, object],
    summary: dict[str, object],
    measured: list[ProfileSample],
) -> dict[str, object]:
    """Propose a versioned record without changing the worker API contract."""
    return {
        "schema_version": 1,
        "contract_status": "proposal",
        "run_id": output_dir.name,
        "model_id": None,
        "query_id": "sample-amount-groupby-v1",
        "query_sha256": measured[0].query_sha256,
        "result_sha256": measured[0].result_sha256,
        "workload_kind": "select_fetch_all",
        "engine": {"name": "duckdb", "version": duckdb.__version__},
        "environment": {
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "architecture": platform.machine(),
            "process_id": os.getpid(),
        },
        "dataset": {
            "database_path": str(database_path.resolve()),
            "file_sha256": database_sha256,
            "source_rows": source_rows,
            "identity_scope": "physical database file; not semantic dataset equivalence",
        },
        "config": config,
        "method": {
            "warmup_count": summary["warmup_count"],
            "requested_repeats": summary["requested_repeats"],
            "profiling_enabled": summary["profiling_enabled"],
            "metric_mode": summary["metric_mode"],
            "connection_policy": summary["connection_policy"],
            "cache_policy": summary["cache_policy"],
            "timing_scope": summary["timing_scope"],
            "memory_scope": summary["memory_scope"],
            "buffer_peak_reset_status": summary["buffer_peak_reset_status"],
        },
        "units": {
            "samples[*].python_elapsed_seconds": "seconds",
            "samples[*].metrics.latency": "seconds",
            "samples[*].metrics.cumulative_rows_scanned": "rows",
            "samples[*].metrics.system_peak_buffer_memory": "bytes",
        },
        "summary": summary,
        "samples": [
            {"sample_index": index + 1} | sample.model_dump()
            for index, sample in enumerate(measured)
        ],
        "limitations": [
            "Profiling instrumentation is enabled in all measured samples.",
            "Buffer peaks can retain history from warmup and previous queries.",
            "OS cache is not controlled by this experiment.",
            "Result hashes validate this deterministic query, not arbitrary rewrite equivalence.",
            "SELECT measurements do not establish dbt materialization performance.",
            "The worker memory contract and any RSS requirement still need team agreement.",
        ],
    }


def run_experiment(args: argparse.Namespace, output_dir: Path) -> dict[str, object]:
    """Prepare a database, close preparation, and profile separate connections."""
    database_path = (
        args.database.resolve() if args.database is not None else output_dir / "sample.duckdb"
    )
    if args.database is not None and not database_path.is_file():
        raise FileNotFoundError("The existing sample database does not exist")
    config = {"threads": args.threads, "memory_limit": args.memory_limit}
    with duckdb.connect(
        database=str(database_path),
        read_only=args.database is not None,
        config=config,
    ) as connection:
        settings = connection.execute(
            "SELECT current_setting('threads'), current_setting('memory_limit')"
        ).fetchone()
        if settings is None:
            raise RuntimeError("DuckDB did not return its settings")
        if connection.execute("SELECT 1 AS ready").fetchall() != [(1,)]:
            raise RuntimeError("DuckDB readiness query failed")

        actual_rows = (
            sample_row_count(connection)
            if args.database is not None
            else build_sample(connection, args.rows)
        )
        (output_dir / "query.sql").write_text(SAMPLE_QUERY + "\n", encoding="utf-8")
        save_plan(connection, "EXPLAIN " + SAMPLE_QUERY, output_dir, "explain")
        save_plan(connection, "EXPLAIN ANALYZE " + SAMPLE_QUERY, output_dir, "explain_analyze")
        reference = connection.execute(SAMPLE_QUERY).fetchall()
        write_json(output_dir / "result.json", reference)
        expected_result = result_digest(reference)

    samples: list[ProfileSample] = []
    with duckdb.connect(database=str(database_path), read_only=True, config=config) as connection:
        fresh = capture_profile(
            connection,
            output_dir,
            "fresh",
            explicit_metrics=args.explicit_metrics,
            expected_result_sha256=expected_result,
        )
        samples.append(fresh)
        if args.memory_study:
            samples.append(
                capture_profile(
                    connection,
                    output_dir,
                    "reused",
                    explicit_metrics=args.explicit_metrics,
                    expected_result_sha256=expected_result,
                )
            )
            samples.append(
                capture_profile(
                    connection,
                    output_dir,
                    "pressure",
                    query=MEMORY_PRESSURE_QUERY,
                    explicit_metrics=args.explicit_metrics,
                )
            )
            samples.append(
                capture_profile(
                    connection,
                    output_dir,
                    "after-pressure",
                    explicit_metrics=args.explicit_metrics,
                    expected_result_sha256=expected_result,
                )
            )

    if args.memory_study:
        with duckdb.connect(
            database=str(database_path), read_only=True, config=config
        ) as connection:
            samples.append(
                capture_profile(
                    connection,
                    output_dir,
                    "reopened",
                    explicit_metrics=args.explicit_metrics,
                    expected_result_sha256=expected_result,
                )
            )
        write_json(output_dir / "memory-study.json", memory_observations(samples))

    benchmark_summary: dict[str, object] | None = None
    if args.benchmark:
        database_sha256 = file_digest(database_path)
        with duckdb.connect(
            database=str(database_path), read_only=True, config=config
        ) as benchmark_connection:
            benchmark_settings = benchmark_connection.execute(
                "SELECT current_setting('threads'), current_setting('memory_limit')"
            ).fetchone()
            if benchmark_settings is None:
                raise RuntimeError("DuckDB did not return benchmark settings")
            benchmark_summary, measured = benchmark_query(
                benchmark_connection,
                output_dir,
                warmup=args.warmup,
                repeats=args.repeats,
                explicit_metrics=args.explicit_metrics,
                expected_result_sha256=expected_result,
            )
        write_json(
            output_dir / "benchmark-record.json",
            handoff_record(
                output_dir,
                database_path,
                database_sha256,
                actual_rows,
                {
                    "threads_requested": args.threads,
                    "threads_effective": benchmark_settings[0],
                    "memory_limit_requested": args.memory_limit,
                    "memory_limit_effective": benchmark_settings[1],
                },
                benchmark_summary,
                measured,
            ),
        )

    write_json(output_dir / "samples.json", [sample.model_dump() for sample in samples])
    return {
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        "duckdb_version": duckdb.__version__,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "architecture": platform.machine(),
        "process_id": os.getpid(),
        "database": str(database_path.resolve()),
        "database_reused": args.database is not None,
        "threads_requested": args.threads,
        "threads_effective": settings[0],
        "memory_limit_requested": args.memory_limit,
        "memory_limit_effective": settings[1],
        "rows_planned": args.rows,
        "rows_created": actual_rows if args.database is None else None,
        "source_rows": actual_rows,
        "result_rows": fresh.result_rows,
        "result_sha256": fresh.result_sha256,
        "query_sha256": fresh.query_sha256,
        "profile_path": fresh.profile_path,
        "profiling_status": (
            "captured_with_missing_metrics" if fresh.missing_metrics else "json_profile_captured"
        ),
        "metric_mode": fresh.metric_mode,
        "missing_metrics": fresh.missing_metrics,
        "measurements": {
            "python_elapsed_seconds": fresh.python_elapsed_seconds,
            "duckdb_latency_seconds": fresh.metrics.latency,
            "rows_scanned": fresh.metrics.cumulative_rows_scanned,
            "peak_buffer_memory_bytes": fresh.metrics.system_peak_buffer_memory,
        },
        "scans": [scan.model_dump() for scan in fresh.scans],
        "memory_study_enabled": args.memory_study,
        "benchmark_enabled": args.benchmark,
        "benchmark": benchmark_summary,
        "memory_scope": "DuckDB buffer manager; worker RSS is not measured",
        "timing_scope": "execute plus fetch; database creation and connection opening excluded",
        "metric_mapping": {
            "duckdb_latency_seconds": {"json_path": "$.latency", "unit": "seconds"},
            "rows_scanned": {"json_path": "$.cumulative_rows_scanned", "unit": "rows"},
            "peak_buffer_memory_bytes": {
                "json_path": "$.system_peak_buffer_memory",
                "unit": "bytes",
            },
        },
    }


def main() -> None:
    """Create a unique artifact directory and run the profiling experiment."""
    args = parse_args()
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid4().hex[:8]
    output_dir = args.output_dir.resolve() / run_id
    output_dir.mkdir(parents=True, exist_ok=False)
    try:
        metadata = run_experiment(args, output_dir)
    except duckdb.Error as error:
        write_json(
            output_dir / "failure.json",
            {
                "recorded_at_utc": datetime.now(UTC).isoformat(),
                "duckdb_version": duckdb.__version__,
                "exception_type": type(error).__name__,
                "error": str(error),
                "metric_mode": "explicit" if args.explicit_metrics else "default",
                "threads_requested": args.threads,
                "memory_limit_requested": args.memory_limit,
            },
        )
        raise

    metadata["run_id"] = run_id
    destination = output_dir / "environment.json"
    write_json(destination, metadata)
    print(json.dumps(metadata, indent=2))
    print(f"Saved artifacts to {output_dir}")


if __name__ == "__main__":
    main()
