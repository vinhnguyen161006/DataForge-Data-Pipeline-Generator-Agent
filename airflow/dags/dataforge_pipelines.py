"""Fixed DAG template. Generated pipelines only contribute dag_config.json, never Python."""

import os
from pathlib import Path
from typing import Any

from airflow.sdk import DAG

DATA_ROOT = Path(os.environ.get("DATAFORGE_DATA_ROOT", "/data"))
CONFIG_GLOB = "projects/*/approved/*/dag_config.json"
DBT_BIN = os.environ.get("DATAFORGE_DBT_BIN", "/opt/dbt-venv/bin/dbt")


def load_pipeline_config(path: Path) -> dict[str, Any] | None:
    """TODO: parse and validate one dag_config.json; log and return None when invalid.

    One broken config must never break parsing of the other pipelines.
    Parse-time code reads only local files: no API calls, no database, no Variables.
    """
    raise NotImplementedError


def wait_for_ready_batch(config: dict[str, Any]) -> str:
    """TODO: sensor: return the batch id once every required file exists and _READY is present."""
    raise NotImplementedError


def check_schema(config: dict[str, Any], batch_id: str) -> None:
    """TODO: fail and notify the Engineer when the batch schema fingerprint differs (FR-17)."""
    raise NotImplementedError


def dbt_build(config: dict[str, Any], batch_id: str) -> str:
    """TODO: run `DBT_BIN build` of the approved version in a fresh workspace with batch vars.

    dbt lives in its own virtualenv, never in the Airflow environment. Each run
    gets its own DuckDB file because DuckDB allows a single writer per file.
    Snapshot replace: rerunning the same batch replaces tables and never duplicates rows.
    Any failing approved test stops the run before publishing.
    """
    raise NotImplementedError


def request_publish(config: dict[str, Any], batch_id: str, duckdb_path: str) -> None:
    """TODO: ask the platform to enqueue a publisher job.

    Airflow never holds warehouse credentials.
    """
    raise NotImplementedError


def build_dag(config: dict[str, Any]) -> DAG:
    """TODO: DAG with a stable dag_id per pipeline and max_active_runs=1 (per-pipeline lock)."""
    raise NotImplementedError


for config_path in sorted(DATA_ROOT.glob(CONFIG_GLOB)):
    pipeline_config = load_pipeline_config(config_path)
    if pipeline_config is not None:
        globals()[f"dataforge_{pipeline_config['pipeline_id']}"] = build_dag(pipeline_config)
