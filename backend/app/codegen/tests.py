from typing import Any

from app.agents.schemas import Constraint, DataDesign


def column_test(constraint: Constraint) -> Any:
    """TODO: map a single-column constraint to a dbt data_test entry (with `arguments:`)."""
    raise NotImplementedError


def model_test(constraint: Constraint) -> Any:
    """TODO: map composite-unique / expression constraints to dataforge_* generic tests."""
    raise NotImplementedError


def schema_yml(design: DataDesign) -> dict[str, str]:
    """TODO: return {models/<layer>/_schema.yml: yaml} built ONLY from approved constraints
    (FR-08).
    """
    raise NotImplementedError
