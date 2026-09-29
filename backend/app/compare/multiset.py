from typing import Literal

import duckdb
from pydantic import BaseModel, Field


class EquivalenceRules(BaseModel):
    float_decimals: int = 9
    timestamp_precision: Literal["microseconds", "milliseconds", "seconds"] = "microseconds"
    check_column_types: bool = True
    sample_limit: int = 5


class ComparisonResult(BaseModel):
    equivalent: bool
    schema_match: bool
    schema_diff: list[str] = Field(default_factory=list)
    left_rows: int = 0
    right_rows: int = 0
    only_in_left: int = 0
    only_in_right: int = 0
    sample_only_in_left: list[list[str | None]] = Field(default_factory=list)
    sample_only_in_right: list[list[str | None]] = Field(default_factory=list)


def describe_schema(con: duckdb.DuckDBPyConnection, sql: str) -> list[tuple[str, str]]:
    """TODO: return [(column name, type)] of a query via DESCRIBE."""
    raise NotImplementedError


def normalized_projection(schema: list[tuple[str, str]], rules: EquivalenceRules) -> str:
    """TODO: round floats/decimals, convert timestamptz to UTC, truncate timestamps."""
    raise NotImplementedError


def compare_queries(
    con: duckdb.DuckDBPyConnection,
    left_sql: str,
    right_sql: str,
    rules: EquivalenceRules | None = None,
) -> ComparisonResult:
    """TODO: schema must match, then compare as multisets with EXCEPT ALL in both directions.

    Row count alone is never enough; NULL equals NULL; include sample differing rows.
    """
    raise NotImplementedError
