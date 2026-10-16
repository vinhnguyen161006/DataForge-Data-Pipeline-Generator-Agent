import itertools
import re
from pathlib import Path

import duckdb

from app.ingest.sniff import CsvReadConfig
from app.profiler.schemas import (
    ColumnProfile,
    DataProfile,
    KeyCandidate,
    RelationshipCandidate,
    TableProfile,
)


def quote_identifier(identifier: str) -> str:
    """Double-quote a DuckDB identifier and escape embedded quotes."""
    return '"' + identifier.replace('"', '""') + '"'


def table_name_for(filename: str) -> str:
    """Derive a stable safe snake_case table name from a CSV filename."""
    stem = Path(filename).stem
    name = re.sub(r"[^0-9A-Za-z]+", "_", stem).strip("_").lower()
    name = re.sub(r"_+", "_", name)
    if not name:
        name = "table"
    if name[0].isdigit():
        name = f"table_{name}"
    return name


def profile_column(
    table: str,
    column: str,
    column_type: str,
    row_count: int,
    *,
    non_null_count: int,
    distinct_count: int,
    min_value: str | None,
    max_value: str | None,
    sample_values: list[str],
    has_leading_zeros: bool,
) -> ColumnProfile:
    """Build a column profile from deterministic aggregate statistics."""
    del table
    return ColumnProfile(
        name=column,
        inferred_type=column_type,
        row_count=row_count,
        null_ratio=(row_count - non_null_count) / row_count if row_count else 0.0,
        distinct_count=distinct_count,
        min_value=min_value,
        max_value=max_value,
        sample_values=sample_values[:5],
        has_leading_zeros=has_leading_zeros,
    )


def find_key_candidates(table: TableProfile) -> list[KeyCandidate]:
    """Return key candidates recorded during profiling and unique single columns."""
    candidates: list[KeyCandidate] = []
    columns = {column.name: column for column in table.columns}
    groups = table.candidate_key_groups or [
        [column.name]
        for column in table.columns
        if column.row_count > 0
        and column.null_ratio == 0
        and column.distinct_count == column.row_count
    ]
    seen: set[tuple[str, ...]] = set()
    for group in groups:
        key = tuple(group)
        if not key or key in seen:
            continue
        seen.add(key)
        null_count = sum(
            round(columns[name].null_ratio * columns[name].row_count) for name in group
        )
        candidates.append(
            KeyCandidate(
                table=table.name,
                columns=list(group),
                is_unique_in_batch=True,
                null_count=null_count,
            )
        )
    return candidates


def find_relationship_candidates(tables: list[TableProfile]) -> list[RelationshipCandidate]:
    """Return relationship candidates based on identically named columns."""
    relationships: list[RelationshipCandidate] = []
    for child, parent in itertools.permutations(tables, 2):
        parent_columns = {column.name: column for column in parent.columns}
        child_columns = {column.name: column for column in child.columns}
        for name in sorted(set(child_columns) & set(parent_columns)):
            parent_column = parent_columns[name]
            child_column = child_columns[name]
            if child_column.row_count == 0 or parent_column.row_count == 0:
                continue
            match_ratio = (
                1.0 if parent_column.distinct_count >= child_column.distinct_count else 0.0
            )
            orphan_count = max(0, child_column.distinct_count - parent_column.distinct_count)
            relationships.append(
                RelationshipCandidate(
                    child_table=child.name,
                    child_columns=[name],
                    parent_table=parent.name,
                    parent_columns=[name],
                    match_ratio=match_ratio,
                    orphan_count=orphan_count,
                    parent_key_unique=parent_column.distinct_count == parent_column.row_count,
                    fanout_warning=parent_column.distinct_count < parent_column.row_count,
                    max_parent_matches=(
                        1 if parent_column.distinct_count == parent_column.row_count else 2
                    ),
                )
            )
    return relationships


def profile_files(files: list[tuple[Path, CsvReadConfig]], *, threads: int = 2) -> DataProfile:
    """Profile CSV files with DuckDB and return bounded statistical metadata.

    Runs inside the sandbox worker (job kind "profile"), never in the API process.
    """
    if threads < 1:
        raise ValueError("threads must be at least 1")
    if not files:
        raise ValueError("at least one CSV file is required")

    connection = duckdb.connect()
    connection.execute(f"PRAGMA threads = {threads}")
    table_specs: list[tuple[str, Path, CsvReadConfig, str]] = []
    used_names: set[str] = set()
    try:
        for path, config in files:
            if not path.is_file():
                raise FileNotFoundError(path)
            base_name = table_name_for(path.name)
            table_name = base_name
            suffix = 2
            while table_name in used_names:
                table_name = f"{base_name}_{suffix}"
                suffix += 1
            used_names.add(table_name)
            view_name = f"source_{len(table_specs)}"
            expression = config.duckdb_read_expr(str(path), all_varchar=False)
            connection.execute(
                f"""
                CREATE OR REPLACE TEMP VIEW {quote_identifier(view_name)}
                AS SELECT * FROM {expression}
                """
            )
            table_specs.append((table_name, path, config, view_name))
        profiles = [
            _profile_table(connection, table_name, path, config, view_name)
            for table_name, path, config, view_name in table_specs
        ]
        for table in profiles:
            table.candidate_key_groups = _find_key_groups(
                connection, table, _view_for(table, table_specs)
            )
        key_candidates = [
            candidate
            for table in profiles
            for candidate in find_key_candidates(table)
        ]
        relationships = _find_relationships_sql(connection, profiles, table_specs)
        return DataProfile(
            tables=profiles,
            key_candidates=key_candidates,
            relationship_candidates=relationships,
        )
    finally:
        connection.close()


def _view_for(table: TableProfile, specs: list[tuple[str, Path, CsvReadConfig, str]]) -> str:
    for name, _, _, view_name in specs:
        if name == table.name:
            return view_name
    raise KeyError(table.name)


def _profile_table(
    connection: duckdb.DuckDBPyConnection,
    table_name: str,
    path: Path,
    config: CsvReadConfig,
    view_name: str,
) -> TableProfile:
    """Compute bounded column statistics for one DuckDB view."""
    description = connection.execute(
        f"DESCRIBE SELECT * FROM {quote_identifier(view_name)}"
    ).fetchall()
    row_count = int(
        connection.execute(f"SELECT count(*) FROM {quote_identifier(view_name)}").fetchone()[0]
    )
    columns: list[ColumnProfile] = []
    numeric_names = [
        name for name, column_type, *_ in description if str(column_type).upper() != "VARCHAR"
    ]
    raw_view_name: str | None = None
    if numeric_names:
        raw_view_name = f"{view_name}_raw"
        raw_expression = config.duckdb_read_expr(str(path), all_varchar=True)
        projected_names = ", ".join(quote_identifier(name) for name in numeric_names)
        connection.execute(
            f"""
            CREATE OR REPLACE TEMP VIEW {quote_identifier(raw_view_name)} AS
            SELECT {projected_names} FROM {raw_expression}
            """
        )
    aggregate_selects = []
    for name, *_ in description:
        identifier = quote_identifier(name)
        aggregate_selects.extend(
            [
                f"count({identifier})",
                f"count(DISTINCT {identifier})",
                f"min(CAST({identifier} AS VARCHAR))",
                f"max(CAST({identifier} AS VARCHAR))",
            ]
        )
    aggregate_values = connection.execute(
        f"SELECT {', '.join(aggregate_selects)} FROM {quote_identifier(view_name)}"
    ).fetchone()
    for index, (name, column_type, *_) in enumerate(description):
        identifier = quote_identifier(name)
        samples = [
            str(row[0])
            for row in connection.execute(
                f"""
                SELECT CAST({identifier} AS VARCHAR)
                FROM {quote_identifier(view_name)}
                WHERE {identifier} IS NOT NULL
                GROUP BY 1
                ORDER BY 1
                LIMIT 5
                """
            ).fetchall()
        ]
        raw_identifier = quote_identifier(name)
        leading_zero = any(re.fullmatch(r"[+-]?0[0-9]+", value) for value in samples)
        if raw_view_name is not None and name in numeric_names:
            leading_zero = bool(
                connection.execute(
                    f"""
                    SELECT EXISTS(
                        SELECT 1
                        FROM {quote_identifier(raw_view_name)}
                        WHERE regexp_matches(CAST({raw_identifier} AS VARCHAR), '^[+-]?0[0-9]+$')
                    )
                    """
                ).fetchone()[0]
            )
        stats = aggregate_values[index * 4 : index * 4 + 4]
        columns.append(
            profile_column(
                table_name,
                name,
                str(column_type),
                row_count,
                non_null_count=int(stats[0]),
                distinct_count=int(stats[1]),
                min_value=stats[2],
                max_value=stats[3],
                sample_values=samples,
                has_leading_zeros=leading_zero,
            )
        )
    return TableProfile(
        name=table_name,
        source_file=str(path),
        row_count=row_count,
        columns=columns,
    )


def _find_key_groups(
    connection: duckdb.DuckDBPyConnection,
    table: TableProfile,
    view_name: str,
) -> list[list[str]]:
    """Find unique non-null single and composite column groups."""
    groups: list[list[str]] = []
    columns = [column for column in table.columns if column.row_count > 0]
    for size in (1, 2):
        for combination in itertools.combinations(columns, size):
            names = [column.name for column in combination]
            expressions = ", ".join(quote_identifier(name) for name in names)
            null_predicate = " OR ".join(
                f"{quote_identifier(name)} IS NULL" for name in names
            )
            result = connection.execute(
                f"""
                SELECT count(*), count(DISTINCT ({expressions}))
                FROM {quote_identifier(view_name)}
                WHERE NOT ({null_predicate})
                """
            ).fetchone()
            non_null_count, distinct_count = int(result[0]), int(result[1])
            if non_null_count == table.row_count and distinct_count == table.row_count:
                groups.append(names)
        if groups:
            break
    return groups


def _find_relationships_sql(
    connection: duckdb.DuckDBPyConnection,
    profiles: list[TableProfile],
    specs: list[tuple[str, Path, CsvReadConfig, str]],
) -> list[RelationshipCandidate]:
    """Measure joins for shared column names and report orphan and fan-out evidence."""
    relationships: list[RelationshipCandidate] = []
    for child, parent in itertools.permutations(profiles, 2):
        child_names = {column.name for column in child.columns}
        parent_names = {column.name for column in parent.columns}
        for name in sorted(child_names & parent_names):
            child_view = _view_for(child, specs)
            parent_view = _view_for(parent, specs)
            identifier = quote_identifier(name)
            result = connection.execute(
                f"""
                WITH parent_counts AS (
                    SELECT {identifier} AS key_value, count(*) AS matches
                    FROM {quote_identifier(parent_view)}
                    WHERE {identifier} IS NOT NULL
                    GROUP BY 1
                ),
                child_values AS (
                    SELECT {identifier} AS key_value
                    FROM {quote_identifier(child_view)}
                    WHERE {identifier} IS NOT NULL
                ),
                parent_stats AS (
                    SELECT count(*) = count(DISTINCT {identifier}) AS parent_unique
                    FROM {quote_identifier(parent_view)}
                    WHERE {identifier} IS NOT NULL
                )
                SELECT
                    count(*) AS child_count,
                    count(parent_counts.key_value) AS matched_count,
                    count(*) - count(parent_counts.key_value) AS orphan_count,
                    coalesce(max(parent_counts.matches), 0) AS max_matches,
                    parent_stats.parent_unique
                FROM child_values
                LEFT JOIN parent_counts USING (key_value)
                CROSS JOIN parent_stats
                GROUP BY parent_stats.parent_unique
                """
            ).fetchone()
            child_count = int(result[0])
            if child_count == 0:
                continue
            relationships.append(
                RelationshipCandidate(
                    child_table=child.name,
                    child_columns=[name],
                    parent_table=parent.name,
                    parent_columns=[name],
                    match_ratio=float(result[1]) / child_count,
                    orphan_count=int(result[2]),
                    parent_key_unique=bool(result[4]),
                    fanout_warning=int(result[3]) > 1,
                    max_parent_matches=int(result[3]),
                )
            )
    return relationships
