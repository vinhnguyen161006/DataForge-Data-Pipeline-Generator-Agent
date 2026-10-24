from pathlib import Path
from typing import Any

from app.jobs.reports import ExecutionReportData
from worker.sandbox import Limits


def prepare_workspace(code_dir: Path, raw_dir: Path, workspace: Path) -> None:
    """TODO: copy the code version into a fresh workspace and link raw CSVs read-only."""
    raise NotImplementedError


def run_profile(payload: dict[str, Any], limits: Limits) -> dict[str, Any]:
    """TODO: job kind "profile": run the profiler on the batch and return DataProfile JSON."""
    raise NotImplementedError


def run_dbt_build(payload: dict[str, Any], limits: Limits) -> ExecutionReportData:
    """TODO: job kind "dbt_build": dbt compile + build in the sandbox, then collect metrics.

    Read target/run_results.json for status/timing and DuckDB profiling output
    for rows scanned and peak memory per model (FR-11).
    """
    raise NotImplementedError


def run_rewrite_benchmark(payload: dict[str, Any], limits: Limits) -> dict[str, Any]:
    """TODO: job kind "rewrite_benchmark": execute original and candidate SQL on the same
    DuckDB file.

    Return equivalence (compare/multiset) and timing samples (compare/benchmark);
    the API process turns them into a judgement.
    """
    raise NotImplementedError
