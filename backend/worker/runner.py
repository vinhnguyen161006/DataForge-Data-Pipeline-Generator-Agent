from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from worker.sandbox import Limits


class ModelMetrics(BaseModel):
    model_name: str
    status: str
    seconds: float
    rows_scanned: int | None = None
    peak_memory_bytes: int | None = None


class DbtTestResult(BaseModel):
    test_name: str
    model_name: str
    status: str
    failures: int


class ExecutionReportData(BaseModel):
    compiled: bool
    succeeded: bool
    models: list[ModelMetrics] = Field(default_factory=list)
    tests: list[DbtTestResult] = Field(default_factory=list)
    quarantine_counts: dict[str, int] = Field(default_factory=dict)
    total_seconds: float = 0.0
    error: str | None = None


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
