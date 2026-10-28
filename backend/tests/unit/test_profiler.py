"""Statistics are measured from real materialized tables after DuckDB lockdown."""

from __future__ import annotations

import csv
import io
import sys
from typing import TYPE_CHECKING

import duckdb
import pytest

from app.profiler.profile import profile_files, quote_identifier, table_name_for
from worker.duckdb_runtime import CsvTableInput, create_profile_database

if TYPE_CHECKING:
    from pathlib import Path

    from app.profiler.schemas import DataProfile


pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux private DuckDB")


def profile_csv(tmp_path: Path, contents: dict[str, str]) -> DataProfile:
    from app.ingest.sniff import CsvReadConfig

    sources = []
    for name, content in contents.items():
        path = tmp_path / name
        path.write_text(content, encoding="utf-8")
        sources.append(
            CsvTableInput(name=table_name_for(name), path=path, read_config=CsvReadConfig())
        )
    with create_profile_database(tmp_path, sources) as database:
        return profile_files(database.tables, connection=database.connection)


@pytest.mark.parametrize(
    ("values", "kind", "minimum", "maximum"),
    [
        ("10\n2\n30\n", "BIGINT", "2", "30"),
        ("10.5\n2.25\n", "DOUBLE", "2.25", "10.5"),
        ("true\nFALSE\n", "BOOLEAN", "false", "true"),
        ("2026-01-02\n2025-12-31\n", "DATE", "2025-12-31", "2026-01-02"),
        (
            "2026-01-02 12:00:00\n2026-01-02 14:00:00\n",
            "TIMESTAMP",
            "2026-01-02 12:00:00",
            "2026-01-02 14:00:00",
        ),
        ("001\n002\n", "VARCHAR", "001", "002"),
        ("NaN\nInfinity\n", "VARCHAR", "Infinity", "NaN"),
        (
            "9223372036854775808\n9223372036854775809\n",
            "HUGEINT",
            "9223372036854775808",
            "9223372036854775809",
        ),
        ("alice\nbob\n", "VARCHAR", "alice", "bob"),
    ],
)
def test_type_inference_and_typed_bounds(
    tmp_path: Path, values: str, kind: str, minimum: str, maximum: str
) -> None:
    result = profile_csv(tmp_path, {"values.csv": "value\n" + values})
    column = result.tables[0].columns[0]
    assert column.inferred_type == kind
    assert (column.min_value, column.max_value) == (minimum, maximum)
    assert column.has_leading_zeros == (values.startswith("001"))


def test_nulls_distinct_counts_and_deterministic_samples(tmp_path: Path) -> None:
    result = profile_csv(tmp_path, {"items.csv": "id,label\n1,b\n2,a\n3,a\n4,\n"})
    table = result.tables[0]
    assert table.row_count == 4
    column = table.columns[1]
    assert column.null_ratio == 0.25
    assert column.distinct_count == 2
    assert column.sample_values == ["a", "b"]
    assert result.key_candidates[0].columns == ["id"]


def test_empty_table_has_no_keys_and_defined_statistics(tmp_path: Path) -> None:
    result = profile_csv(tmp_path, {"empty.csv": "id,label\n"})
    assert result.tables[0].row_count == 0
    assert result.key_candidates == []
    for column in result.tables[0].columns:
        assert column.null_ratio == 0
        assert column.distinct_count == 0
        assert column.min_value is None
        assert column.sample_values == []


def test_all_null_column_is_not_a_key(tmp_path: Path) -> None:
    result = profile_csv(tmp_path, {"empty.csv": "id,label\n1,\n2,\n"})
    column = result.tables[0].columns[1]
    assert column.null_ratio == 1
    assert column.inferred_type == "VARCHAR"
    assert column.min_value is None
    assert not any(key.columns == ["label"] for key in result.key_candidates)


def test_composite_keys_and_relationships_use_all_components(tmp_path: Path) -> None:
    result = profile_csv(
        tmp_path,
        {
            "pairs.csv": "a_id,b_id,label\n1,1,x\n1,2,x\n2,1,x\n2,2,x\n",
            "events.csv": "event_id,a_id,b_id\n1,1,1\n2,2,2\n3,3,3\n4,,1\n",
        },
    )
    assert any(
        key.table == "pairs" and key.columns == ["a_id", "b_id"] for key in result.key_candidates
    )
    relation = next(
        item
        for item in result.relationship_candidates
        if item.parent_table == "pairs" and item.parent_columns == ["a_id", "b_id"]
    )
    assert relation.match_ratio == pytest.approx(2 / 3)
    assert relation.orphan_count == 1
    assert relation.parent_key_unique
    assert relation.max_parent_matches == 1


def test_nonunique_parent_reports_fanout_without_multiplying_child_count(tmp_path: Path) -> None:
    result = profile_csv(
        tmp_path,
        {
            "customers.csv": "customer_id,name\n001,Alice\n001,Alias\n002,Bob\n",
            "orders.csv": "id,customer_id\n1,001\n2,002\n3,003\n4,\n",
        },
    )
    relation = next(
        item
        for item in result.relationship_candidates
        if item.child_table == "orders" and item.parent_table == "customers"
    )
    assert relation.match_ratio == pytest.approx(2 / 3)
    assert relation.orphan_count == 1
    assert relation.max_parent_matches == 2
    assert relation.fanout_warning
    assert not relation.parent_key_unique


def test_samples_are_bounded_in_count_and_length(tmp_path: Path) -> None:
    values = [str(index) + "x" * 400 for index in range(10)]
    result = profile_csv(tmp_path, {"long.csv": "value\n" + "\n".join(values)})
    samples = result.tables[0].columns[0].sample_values
    assert len(samples) == 5
    assert all(len(sample) <= 160 for sample in samples)


def test_sql_in_column_name_is_quoted_as_data(tmp_path: Path) -> None:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    name = 'value"; DROP TABLE guarded; --'
    writer.writerow([name])
    writer.writerow(["001"])
    result = profile_csv(tmp_path, {"guarded.csv": stream.getvalue()})
    assert result.tables[0].columns[0].name == name
    assert result.tables[0].columns[0].sample_values == ["001"]


@pytest.mark.parametrize("name", ["", "\x00", "a\x00b"])
def test_invalid_identifiers_are_rejected(name: str) -> None:
    with pytest.raises(ValueError, match="identifiers"):
        quote_identifier(name)


def test_identifier_escaping_and_stable_collision_resistant_table_names() -> None:
    assert quote_identifier('a"b') == '"a""b"'
    assert table_name_for("customers.csv") == "customers"
    assert table_name_for("orders-2026.csv") != table_name_for("orders_2026.csv")
    for name in ("123.csv", "\u0111\u01a1n.csv", "long" * 70 + ".csv"):
        if len(name) > 255:
            name = name[:240] + ".csv"
        normalized = table_name_for(name)
        assert normalized[0].isalpha()
        assert len(normalized) <= 63
        assert normalized == table_name_for(name)


def test_unlocked_connection_is_rejected(tmp_path: Path) -> None:
    with (
        duckdb.connect(config={"threads": "1"}) as connection,
        pytest.raises(ValueError, match="locked"),
    ):
        profile_files([], connection=connection)


def test_prefix_id_names_are_relationship_candidates(tmp_path: Path) -> None:
    result = profile_csv(
        tmp_path,
        {
            "students.csv": "id_student,name\n001,Alice\n002,Bob\n",
            "events.csv": "id_event,id_student\n1,001\n2,009\n",
        },
    )
    relation = next(
        item
        for item in result.relationship_candidates
        if item.parent_table == "students" and item.child_columns == ["id_student"]
    )
    assert relation.match_ratio == 0.5
    assert relation.orphan_count == 1
