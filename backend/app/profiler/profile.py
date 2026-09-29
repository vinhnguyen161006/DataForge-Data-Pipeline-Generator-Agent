from pathlib import Path

from app.ingest.sniff import CsvReadConfig
from app.profiler.schemas import (
    ColumnProfile,
    DataProfile,
    KeyCandidate,
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


def profile_files(files: list[tuple[Path, CsvReadConfig]], *, threads: int = 2) -> DataProfile:
    """TODO: load each CSV into DuckDB and build the full DataProfile (FR-02).

    Runs inside the sandbox worker (job kind "profile"), never in the API process.
    """
    raise NotImplementedError
