from pydantic import BaseModel, Field


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
    """Result of a sandbox "dbt_build" job, written by the worker and judged by the graph."""

    compiled: bool
    succeeded: bool
    models: list[ModelMetrics] = Field(default_factory=list)
    tests: list[DbtTestResult] = Field(default_factory=list)
    quarantine_counts: dict[str, int] = Field(default_factory=dict)
    total_seconds: float = 0.0
    error: str | None = None
