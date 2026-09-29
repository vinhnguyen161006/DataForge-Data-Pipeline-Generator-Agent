from pathlib import Path

import pytest

DAGS_DIR = Path(__file__).resolve().parents[1] / "dags"


@pytest.mark.skip(reason="TODO")
def test_dagbag_has_no_import_errors() -> None:
    """TODO: load DagBag(DAGS_DIR, include_examples=False) and assert import_errors is empty."""


@pytest.mark.skip(reason="TODO")
def test_invalid_config_is_skipped() -> None:
    """TODO: a malformed dag_config.json yields no DAG and does not break other pipelines."""
