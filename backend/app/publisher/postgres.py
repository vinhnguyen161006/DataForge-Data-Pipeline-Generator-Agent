import uuid
from pathlib import Path

from pydantic import BaseModel


class TableReconciliation(BaseModel):
    table: str
    source_rows: int
    loaded_rows: int
    source_checksum: str
    loaded_checksum: str
    matches: bool


class PublishResult(BaseModel):
    staging_schema: str
    serving_schema: str
    tables: list[TableReconciliation]
    published: bool


def staging_schema_name(project_slug: str, code_version_id: uuid.UUID) -> str:
    """TODO: deterministic, identifier-safe staging schema name (<= 63 chars)."""
    raise NotImplementedError


def serving_schema_name(project_slug: str) -> str:
    """TODO: stable schema that Metabase reads (views over the current staging schema)."""
    raise NotImplementedError


def load_staging(
    warehouse_dsn: str, duckdb_path: Path, staging_schema: str, tables: list[str]
) -> None:
    """TODO: drop and recreate the staging schema, then psycopg COPY each mart table from DuckDB.

    Idempotent: retrying the same version replaces staging, never duplicates rows.
    """
    raise NotImplementedError


def reconcile(
    warehouse_dsn: str, duckdb_path: Path, staging_schema: str, tables: list[str]
) -> list[TableReconciliation]:
    """TODO: compare row counts and order-independent checksums between DuckDB and staging."""
    raise NotImplementedError


def swap_serving_views(
    warehouse_dsn: str, staging_schema: str, serving_schema: str, tables: list[str]
) -> None:
    """TODO: in ONE transaction, repoint serving views to the staging schema.

    If anything fails before commit, dashboards keep serving the previous version (FR-14).
    """
    raise NotImplementedError


def publish_version(
    warehouse_dsn: str,
    *,
    project_slug: str,
    code_version_id: uuid.UUID,
    duckdb_path: Path,
    tables: list[str],
) -> PublishResult:
    """TODO: load_staging -> reconcile -> swap_serving_views; stop before swap on any mismatch."""
    raise NotImplementedError
