from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from duckdb import DuckDBPyConnection

    from app.profiler.schemas import (
        ColumnProfile,
        DataProfile,
        KeyCandidate,
        LoadedTable,
        RelationshipCandidate,
        TableProfile,
    )


def quote_identifier(identifier: str) -> str:
    """TODO: double-quote a DuckDB identifier, escaping embedded quotes."""
    raise NotImplementedError


def table_name_for(filename: str) -> str:
    """TODO: derive a safe snake_case table name from a CSV filename."""
    raise NotImplementedError


def profile_column(table: str, column: str, column_type: str, row_count: int) -> ColumnProfile:
    """TODO: null ratio, distinct count, min/max, top sample values, leading-zero detection."""
    raise NotImplementedError


def find_key_candidates(table: TableProfile) -> list[KeyCandidate]:
    """TODO: single-column keys first; fall back to two-column composite keys."""
    raise NotImplementedError


def find_relationship_candidates(tables: list[TableProfile]) -> list[RelationshipCandidate]:
    """TODO: match ratio, orphan count and fan-out warning for each candidate join (FR-03)."""
    raise NotImplementedError


def profile_files(tables: Sequence[LoadedTable], *, connection: DuckDBPyConnection) -> DataProfile:
    """TODO: build DataProfile from materialized tables on the caller's locked connection.

    Runs inside the sandbox worker, never in the API process. The worker owns
    confirmed CSV loading, resource settings, lockdown and connection cleanup.
    Do not open another database, read source files or close this connection.
    """
    raise NotImplementedError
