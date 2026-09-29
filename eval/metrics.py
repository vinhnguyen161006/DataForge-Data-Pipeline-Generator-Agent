from pydantic import BaseModel, Field


class TaskScore(BaseModel):
    task_id: str
    dbt_compiles: bool
    dag_imports: bool
    tables_match_golden: float
    design_score: float
    tests_pass_on_clean: float
    fault_detection_rate: float
    median_speedup_vs_internal_baseline: float | None = None
    rows_scanned_reduction: float | None = None
    rejected_rewrites: dict[str, int] = Field(default_factory=dict)
    reviewer_edited_lines: int = 0
    fix_rounds: int = 0
    completed: bool = False
    prompt_tokens: int = 0
    output_tokens: int = 0
    rewrite_search_seconds: float = 0.0


def score_design(design: dict, golden: dict) -> float:
    """TODO: score grain, keys and relationships; accept any of several valid golden designs."""
    raise NotImplementedError


def score_tables(duckdb_path: str, golden_dir: str) -> float:
    """TODO: share of mart tables equivalent to golden tables via app.compare.multiset."""
    raise NotImplementedError
