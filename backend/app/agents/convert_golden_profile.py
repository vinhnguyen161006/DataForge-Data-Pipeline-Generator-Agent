import json
from pathlib import Path

from app.profiler.schemas import (
    ColumnProfile,
    DataProfile,
    KeyCandidate,
    RelationshipCandidate,
    TableProfile,
)


def main() -> None:
    project_root = Path(__file__).resolve().parents[3]
    report_path = project_root / "eval" / "golden" / "oulad" / "metadata" / "profile_report.json"

    report = json.loads(report_path.read_text(encoding="utf-8"))

    tables: list[TableProfile] = []

    for table_name, table in report["tables"].items():
        columns: list[ColumnProfile] = []

        for column_name, column in table["columns"].items():
            inferred_type = {
                "text": "string",
                "numeric": "float",
            }.get(column["inferred_type"], column["inferred_type"])

            numeric = inferred_type in {"integer", "float"}
            minimum = column["numeric_min"] if numeric else column["min_text"]
            maximum = column["numeric_max"] if numeric else column["max_text"]

            columns.append(
                ColumnProfile(
                    name=column_name,
                    inferred_type=inferred_type,
                    row_count=column["rows"],
                    null_ratio=(
                        column["null_like_rows"] / column["rows"] if column["rows"] else 0.0
                    ),
                    distinct_count=column["distinct_values"],
                    min_value=str(minimum) if minimum is not None else None,
                    max_value=str(maximum) if maximum is not None else None,
                    has_leading_zeros=column["rows_with_leading_zero"] > 0,
                )
            )

        tables.append(
            TableProfile(
                name=table_name,
                source_file=f"{table_name}.csv",
                row_count=table["rows"],
                columns=columns,
            )
        )

    key_candidates: list[KeyCandidate] = []

    for table_name, table in report["tables"].items():
        candidate = table.get("candidate_key")
        if candidate is None:
            continue

        key_candidates.append(
            KeyCandidate(
                table=table_name,
                columns=candidate["key_columns"],
                is_unique_in_batch=(candidate["distinct_keys"] == candidate["rows"]),
                null_count=candidate["rows_with_null_like_key_part"],
            )
        )

    relationships: list[RelationshipCandidate] = []
    notes = [
        "Converted from the OULAD golden statistical report.",
        "Null ratios include these null-like tokens: "
        + json.dumps(report["null_like_tokens_checked"]),
        "Keys and relationships are batch observations, not approved constraints.",
    ]

    for relation in report["relationships"]:
        if not relation["parent_key_unique"]:
            notes.append(
                f"Relationship {relation['relationship']}: "
                f"{relation['child']} {relation['child_columns']} -> "
                f"{relation['parent']} {relation['parent_columns']}. "
                "Parent key is NOT unique; joining may multiply rows. "
                f"Match rate: {relation['match_rate_pct']}%; "
                f"orphan rows: {relation['orphan_rows']}. "
                "Not included in relationship_candidates because the report "
                "does not provide max_parent_matches. "
                "Reconsider the join key and grain before using this relationship."
            )
            continue

        has_matches = relation["child_rows"] > relation["orphan_rows"]

        relationships.append(
            RelationshipCandidate(
                child_table=relation["child"],
                child_columns=relation["child_columns"],
                parent_table=relation["parent"],
                parent_columns=relation["parent_columns"],
                match_ratio=relation["match_rate_pct"] / 100,
                orphan_count=relation["orphan_rows"],
                parent_key_unique=True,
                fanout_warning=False,
                max_parent_matches=1 if has_matches else 0,
            )
        )

    profile = DataProfile(
        tables=tables,
        key_candidates=key_candidates,
        relationship_candidates=relationships,
        notes=notes,
    )

    output_path = report_path.with_name("modeler_profile.json")
    output_path.write_text(
        profile.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"Saved: {output_path}")
    print(f"Tables: {len(profile.tables)}")
    print(f"Keys: {len(profile.key_candidates)}")
    print(f"Relationships: {len(profile.relationship_candidates)}")
    print("Review notes for relationships with non-unique parent keys.")


if __name__ == "__main__":
    main()
