"""Profile the 7 OULAD CSV files and write source_manifest.json and profile_report.json.

Every column is read as VARCHAR so that no raw value is altered or coerced.
Usage:
    python eval/golden/tools/profile_oulad.py --raw-dir eval/golden/oulad/raw --out-dir eval/golden/oulad/metadata
Smoke test on the first N rows of each file:
    python eval/golden/tools/profile_oulad.py --max-rows 1000
"""

import argparse
import codecs
import hashlib
import json
import sys
from pathlib import Path

import duckdb

MP = ["code_module", "code_presentation"]
MPS = MP + ["id_student"]

EXPECTED_COLUMNS = {
    "courses": ["code_module", "code_presentation", "module_presentation_length"],
    "assessments": [
        "code_module",
        "code_presentation",
        "id_assessment",
        "assessment_type",
        "date",
        "weight",
    ],
    "vle": [
        "id_site",
        "code_module",
        "code_presentation",
        "activity_type",
        "week_from",
        "week_to",
    ],
    "studentInfo": [
        "code_module",
        "code_presentation",
        "id_student",
        "gender",
        "region",
        "highest_education",
        "imd_band",
        "age_band",
        "num_of_prev_attempts",
        "studied_credits",
        "disability",
        "final_result",
    ],
    "studentRegistration": [
        "code_module",
        "code_presentation",
        "id_student",
        "date_registration",
        "date_unregistration",
    ],
    "studentAssessment": [
        "id_assessment",
        "id_student",
        "date_submitted",
        "is_banked",
        "score",
    ],
    "studentVle": [
        "code_module",
        "code_presentation",
        "id_student",
        "id_site",
        "date",
        "sum_click",
    ],
}

CANDIDATE_KEYS = {
    "courses": MP,
    "assessments": ["id_assessment"],
    "vle": ["id_site"],
    "studentInfo": MPS,
    "studentRegistration": MPS,
    "studentAssessment": ["id_assessment", "id_student"],
    "studentVle": MPS + ["id_site", "date"],
}

RELATIONSHIPS = [
    ("assessments_to_courses", "assessments", MP, "courses", MP),
    ("vle_to_courses", "vle", MP, "courses", MP),
    ("student_info_to_courses", "studentInfo", MP, "courses", MP),
    ("student_registration_to_courses", "studentRegistration", MP, "courses", MP),
    ("student_registration_to_student_info", "studentRegistration", MPS, "studentInfo", MPS),
    ("student_assessment_to_assessments", "studentAssessment", ["id_assessment"], "assessments", ["id_assessment"]),
    ("student_assessment_to_student_info_by_student", "studentAssessment", ["id_student"], "studentInfo", ["id_student"]),
    ("student_vle_to_student_info", "studentVle", MPS, "studentInfo", MPS),
    ("student_vle_to_vle_by_site", "studentVle", ["id_site"], "vle", ["id_site"]),
    ("student_vle_to_vle_by_site_and_presentation", "studentVle", MP + ["id_site"], "vle", MP + ["id_site"]),
]

NULL_TOKENS = ["", "?", "NA", "N/A", "NULL", "null", "NaN"]
NO_NULL = "__DATAFORGE_NO_NULL__"
NON_ASCII = bytes(range(128, 256))


def q(name):
    return '"' + name.replace('"', '""') + '"'


def lit(value):
    return "'" + value.replace("'", "''") + "'"


NULL_SQL = ", ".join(lit(token) for token in NULL_TOKENS)


def is_null_sql(column):
    return f"({q(column)} IS NULL OR {q(column)} IN ({NULL_SQL}))"


CUSTOM_CHECKS = {
    "student_info_distinct_students": """
        SELECT count(DISTINCT "id_student") AS distinct_students, count(*) AS rows
        FROM "studentInfo"
    """,
    "student_registration_distinct_students": """
        SELECT count(DISTINCT "id_student") AS distinct_students, count(*) AS rows
        FROM "studentRegistration"
    """,
    "student_info_without_registration": """
        SELECT count(*) AS rows FROM "studentInfo" s
        WHERE NOT EXISTS (
            SELECT 1 FROM "studentRegistration" r
            WHERE r."code_module" = s."code_module"
              AND r."code_presentation" = s."code_presentation"
              AND r."id_student" = s."id_student")
    """,
    "student_registration_without_info": """
        SELECT count(*) AS rows FROM "studentRegistration" r
        WHERE NOT EXISTS (
            SELECT 1 FROM "studentInfo" s
            WHERE r."code_module" = s."code_module"
              AND r."code_presentation" = s."code_presentation"
              AND r."id_student" = s."id_student")
    """,
    "student_assessment_without_registration": """
        SELECT count(*) AS rows
        FROM "studentAssessment" sa
        JOIN "assessments" a ON a."id_assessment" = sa."id_assessment"
        WHERE NOT EXISTS (
            SELECT 1 FROM "studentRegistration" r
            WHERE r."code_module" = a."code_module"
              AND r."code_presentation" = a."code_presentation"
              AND r."id_student" = sa."id_student")
    """,
    "score_outside_0_100": """
        SELECT count(*) AS rows FROM "studentAssessment"
        WHERE TRY_CAST("score" AS DOUBLE) < 0 OR TRY_CAST("score" AS DOUBLE) > 100
    """,
    "unregistered_before_registered": """
        SELECT count(*) AS rows FROM "studentRegistration"
        WHERE TRY_CAST("date_unregistration" AS BIGINT) < TRY_CAST("date_registration" AS BIGINT)
    """,
    "clicks_missing_or_not_positive": """
        SELECT count(*) AS rows FROM "studentVle"
        WHERE TRY_CAST("sum_click" AS BIGINT) IS NULL OR TRY_CAST("sum_click" AS BIGINT) <= 0
    """,
    "vle_week_from_after_week_to": """
        SELECT count(*) AS rows FROM "vle"
        WHERE TRY_CAST("week_from" AS BIGINT) > TRY_CAST("week_to" AS BIGINT)
    """,
    "assessment_date_after_presentation_end": """
        SELECT count(*) AS rows
        FROM "assessments" a
        JOIN "courses" c
          ON c."code_module" = a."code_module" AND c."code_presentation" = a."code_presentation"
        WHERE TRY_CAST(a."date" AS BIGINT) > TRY_CAST(c."module_presentation_length" AS BIGINT)
    """,
    "assessment_weight_sum_by_presentation_and_kind": """
        SELECT "code_module", "code_presentation",
               CASE WHEN "assessment_type" = 'Exam' THEN 'Exam' ELSE 'NonExam' END AS kind,
               sum(TRY_CAST("weight" AS DOUBLE)) AS weight_sum
        FROM "assessments"
        GROUP BY 1, 2, 3
        ORDER BY 1, 2, 3
    """,
    "final_result_vs_unregistration_date": """
        SELECT s."final_result" AS final_result,
               TRY_CAST(r."date_unregistration" AS BIGINT) IS NOT NULL AS has_unregistration_date,
               count(*) AS rows
        FROM "studentInfo" s
        JOIN "studentRegistration" r
          ON r."code_module" = s."code_module"
         AND r."code_presentation" = s."code_presentation"
         AND r."id_student" = s."id_student"
        GROUP BY 1, 2
        ORDER BY 1, 2
    """,
    "assessment_missing_date_by_type": 'SELECT "assessment_type", count(*) AS rows FROM "assessments" WHERE '
    + is_null_sql("date")
    + " GROUP BY 1 ORDER BY 1",
    "vle_week_missing_pattern": "SELECT "
    + is_null_sql("week_from")
    + " AS week_from_missing, "
    + is_null_sql("week_to")
    + ' AS week_to_missing, count(*) AS rows FROM "vle" GROUP BY 1, 2 ORDER BY 1, 2',
    "assessments_without_submissions": """
        SELECT a."assessment_type", a."code_module", a."code_presentation", count(*) AS assessments
        FROM "assessments" a
        WHERE NOT EXISTS (
            SELECT 1 FROM "studentAssessment" sa WHERE sa."id_assessment" = a."id_assessment")
        GROUP BY 1, 2, 3
        ORDER BY 1, 2, 3
    """,
    "submission_after_presentation_end": """
        SELECT count(*) AS rows,
               max(TRY_CAST(sa."date_submitted" AS BIGINT) - TRY_CAST(c."module_presentation_length" AS BIGINT)) AS max_days_after_end
        FROM "studentAssessment" sa
        JOIN "assessments" a ON a."id_assessment" = sa."id_assessment"
        JOIN "courses" c
          ON c."code_module" = a."code_module" AND c."code_presentation" = a."code_presentation"
        WHERE TRY_CAST(sa."date_submitted" AS BIGINT) > TRY_CAST(c."module_presentation_length" AS BIGINT)
    """,
    "submission_before_start": """
        SELECT count(*) AS rows, min(TRY_CAST("date_submitted" AS BIGINT)) AS min_day
        FROM "studentAssessment"
        WHERE TRY_CAST("date_submitted" AS BIGINT) < 0
    """,
    "student_vle_duplicate_breakdown": """
        SELECT count(*) AS duplicate_key_groups,
               sum(n - 1) AS excess_rows,
               sum(CASE WHEN distinct_clicks = 1 THEN n - 1 ELSE 0 END) AS excess_rows_in_groups_with_same_clicks,
               sum(CASE WHEN distinct_clicks > 1 THEN 1 ELSE 0 END) AS groups_with_different_clicks
        FROM (
            SELECT count(*) AS n, count(DISTINCT "sum_click") AS distinct_clicks
            FROM "studentVle"
            GROUP BY "code_module", "code_presentation", "id_student", "id_site", "date"
            HAVING count(*) > 1)
    """,
    "student_vle_duplicate_groups_by_presentation": """
        SELECT "code_module", "code_presentation", count(*) AS duplicate_key_groups
        FROM (
            SELECT "code_module", "code_presentation"
            FROM "studentVle"
            GROUP BY "code_module", "code_presentation", "id_student", "id_site", "date"
            HAVING count(*) > 1)
        GROUP BY 1, 2
        ORDER BY 1, 2
    """,
    "enrollments_per_student": """
        SELECT n AS enrollments, count(*) AS students
        FROM (SELECT "id_student", count(*) AS n FROM "studentInfo" GROUP BY 1)
        GROUP BY 1
        ORDER BY 1
    """,
    "registration_date_missing_by_final_result": """
        SELECT s."final_result", count(*) AS rows
        FROM "studentRegistration" r
        JOIN "studentInfo" s
          ON r."code_module" = s."code_module"
         AND r."code_presentation" = s."code_presentation"
         AND r."id_student" = s."id_student"
        WHERE r."date_registration" IS NULL OR r."date_registration" = ''
        GROUP BY 1
        ORDER BY 1
    """,
    "score_missing_by_is_banked": 'SELECT "is_banked", count(*) AS rows FROM "studentAssessment" WHERE '
    + is_null_sql("score")
    + " GROUP BY 1 ORDER BY 1",
    "imd_band_missing_by_presentation": 'SELECT "code_module", "code_presentation", count(*) AS rows FROM "studentInfo" WHERE '
    + is_null_sql("imd_band")
    + " GROUP BY 1, 2 ORDER BY 1, 2",
    "zero_weight_assessments": """
        SELECT "code_module", "assessment_type", count(*) AS rows
        FROM "assessments"
        WHERE TRY_CAST("weight" AS DOUBLE) = 0
        GROUP BY 1, 2
        ORDER BY 1, 2
    """,
    "student_attribute_consistency": """
        SELECT count(*) AS students_with_multiple_enrollments,
               sum(CASE WHEN g > 1 THEN 1 ELSE 0 END) AS gender_varies,
               sum(CASE WHEN r > 1 THEN 1 ELSE 0 END) AS region_varies,
               sum(CASE WHEN e > 1 THEN 1 ELSE 0 END) AS highest_education_varies,
               sum(CASE WHEN a > 1 THEN 1 ELSE 0 END) AS age_band_varies,
               sum(CASE WHEN d > 1 THEN 1 ELSE 0 END) AS disability_varies,
               sum(CASE WHEN i > 1 THEN 1 ELSE 0 END) AS imd_band_varies
        FROM (
            SELECT "id_student",
                   count(DISTINCT "gender") AS g,
                   count(DISTINCT "region") AS r,
                   count(DISTINCT "highest_education") AS e,
                   count(DISTINCT "age_band") AS a,
                   count(DISTINCT "disability") AS d,
                   count(DISTINCT "imd_band") AS i
            FROM "studentInfo"
            GROUP BY 1
            HAVING count(*) > 1)
    """,
    "reference_metrics": """
        SELECT (SELECT sum(TRY_CAST("sum_click" AS BIGINT)) FROM "studentVle") AS total_clicks,
               (SELECT sum(TRY_CAST("sum_click" AS BIGINT)) FROM "studentVle"
                WHERE TRY_CAST("date" AS BIGINT) < 0) AS clicks_before_start,
               (SELECT count(*) FROM (
                    SELECT DISTINCT "code_module", "code_presentation", "id_student" FROM "studentVle")) AS enrollments_with_clicks,
               (SELECT avg(TRY_CAST("score" AS DOUBLE)) FROM "studentAssessment") AS avg_score_all,
               (SELECT avg(TRY_CAST("score" AS DOUBLE)) FROM "studentAssessment"
                WHERE "is_banked" = '0') AS avg_score_not_banked
    """,
    "score_by_assessment_type": """
        SELECT a."assessment_type", count(*) AS rows,
               sum(CASE WHEN TRY_CAST(sa."score" AS DOUBLE) IS NOT NULL THEN 1 ELSE 0 END) AS rows_with_score,
               avg(TRY_CAST(sa."score" AS DOUBLE)) AS avg_score
        FROM "studentAssessment" sa
        JOIN "assessments" a ON a."id_assessment" = sa."id_assessment"
        GROUP BY 1
        ORDER BY 1
    """,
    "late_submission_counts": """
        SELECT count(*) AS total_rows,
               sum(CASE WHEN TRY_CAST(a."date" AS BIGINT) IS NOT NULL THEN 1 ELSE 0 END) AS rows_with_deadline,
               sum(CASE WHEN TRY_CAST(sa."date_submitted" AS BIGINT) > TRY_CAST(a."date" AS BIGINT) THEN 1 ELSE 0 END) AS late_rows
        FROM "studentAssessment" sa
        JOIN "assessments" a ON a."id_assessment" = sa."id_assessment"
    """,
    "final_result_by_module": """
        SELECT "code_module", "final_result", count(*) AS rows
        FROM "studentInfo"
        GROUP BY 1, 2
        ORDER BY 1, 2
    """,
}


def sha256_of(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def inspect_bytes(path):
    decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
    valid_utf8 = True
    has_bom = False
    first = True
    carry = b""
    crlf = 0
    lf = 0
    non_ascii = 0
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            if first:
                has_bom = block.startswith(codecs.BOM_UTF8)
                first = False
            joined = carry + block
            carry = b"\r" if joined.endswith(b"\r") else b""
            crlf += joined.count(b"\r\n")
            lf += block.count(b"\n")
            non_ascii += len(block) - len(block.translate(None, NON_ASCII))
            if valid_utf8:
                try:
                    decoder.decode(block)
                except UnicodeDecodeError:
                    valid_utf8 = False
    if valid_utf8:
        try:
            decoder.decode(b"", final=True)
        except UnicodeDecodeError:
            valid_utf8 = False
    if lf == 0:
        line_endings = "none"
    elif crlf == 0:
        line_endings = "lf"
    elif crlf == lf:
        line_endings = "crlf"
    else:
        line_endings = "mixed"
    return {
        "valid_utf8": valid_utf8,
        "has_utf8_bom": has_bom,
        "non_ascii_bytes": non_ascii,
        "line_endings": line_endings,
    }


def read_header(path):
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        line = handle.readline().rstrip("\r\n")
    return {
        "raw_header": line,
        "delimiter_counts_in_header": {d: line.count(d) for d in [",", ";", "\t", "|"]},
    }


def load_table(con, table, path, max_rows):
    limit = f" LIMIT {int(max_rows)}" if max_rows else ""
    con.execute(
        f"""CREATE TABLE {q(table)} AS
            SELECT * FROM read_csv({lit(str(path))}, header=true, delim=',', quote='"',
                                   all_varchar=true, nullstr={lit(NO_NULL)}){limit}"""
    )


def profile_column(con, table, column, top_limit):
    c = q(column)
    t = q(table)
    row = con.execute(
        f"""SELECT count(*),
                   sum(CASE WHEN {is_null_sql(column)} THEN 1 ELSE 0 END),
                   count(DISTINCT {c}),
                   min({c}), max({c}),
                   sum(CASE WHEN {c} <> trim({c}) THEN 1 ELSE 0 END),
                   sum(CASE WHEN regexp_matches({c}, '^0[0-9]+$') THEN 1 ELSE 0 END),
                   sum(CASE WHEN regexp_matches({c}, '^-?[0-9]+$') THEN 1 ELSE 0 END),
                   sum(CASE WHEN TRY_CAST({c} AS DOUBLE) IS NOT NULL THEN 1 ELSE 0 END),
                   min(TRY_CAST({c} AS DOUBLE)), max(TRY_CAST({c} AS DOUBLE))
            FROM {t}"""
    ).fetchone()
    rows, null_like, distinct, vmin, vmax, padded, lead0, int_like, num_like, nmin, nmax = row
    null_like = null_like or 0
    non_null = rows - null_like
    if non_null == 0:
        inferred = "all_null"
    elif (int_like or 0) == non_null:
        inferred = "integer"
    elif (num_like or 0) == non_null:
        inferred = "numeric"
    else:
        inferred = "text"
    tokens = con.execute(
        f"""SELECT {c}, count(*) FROM {t}
            WHERE {is_null_sql(column)} GROUP BY 1 ORDER BY 2 DESC"""
    ).fetchall()
    result = {
        "rows": rows,
        "null_like_rows": null_like,
        "null_like_rate_pct": round(100.0 * null_like / rows, 4) if rows else None,
        "null_like_tokens": {("<SQL_NULL>" if k is None else k): v for k, v in tokens},
        "distinct_values": distinct,
        "min_text": vmin,
        "max_text": vmax,
        "inferred_type": inferred,
        "numeric_min": nmin,
        "numeric_max": nmax,
        "rows_with_padding_whitespace": padded or 0,
        "rows_with_leading_zero": lead0 or 0,
    }
    if distinct <= top_limit:
        result["value_counts"] = {
            ("<SQL_NULL>" if k is None else k): v
            for k, v in con.execute(
                f"SELECT {c}, count(*) FROM {t} GROUP BY 1 ORDER BY 2 DESC, 1"
            ).fetchall()
        }
    else:
        result["top5_values"] = [
            [k, v]
            for k, v in con.execute(
                f"SELECT {c}, count(*) FROM {t} GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 5"
            ).fetchall()
        ]
    return result


def profile_key(con, table, key_columns):
    t = q(table)
    cols = ", ".join(q(c) for c in key_columns)
    null_cond = " OR ".join(is_null_sql(c) for c in key_columns)
    total, null_rows = con.execute(
        f"SELECT count(*), sum(CASE WHEN {null_cond} THEN 1 ELSE 0 END) FROM {t}"
    ).fetchone()
    distinct_keys = con.execute(f"SELECT count(*) FROM (SELECT DISTINCT {cols} FROM {t})").fetchone()[0]
    dup_groups, dup_rows, max_group = con.execute(
        f"""SELECT count(*), coalesce(sum(n), 0), coalesce(max(n), 0)
            FROM (SELECT count(*) AS n FROM {t} GROUP BY {cols} HAVING count(*) > 1)"""
    ).fetchone()
    return {
        "key_columns": key_columns,
        "rows": total,
        "rows_with_null_like_key_part": null_rows or 0,
        "distinct_keys": distinct_keys,
        "uniqueness_pct": round(100.0 * distinct_keys / total, 6) if total else None,
        "duplicate_key_groups": dup_groups,
        "rows_in_duplicate_groups": int(dup_rows),
        "max_rows_per_key": max_group,
    }


def profile_relationship(con, name, child, child_cols, parent, parent_cols):
    cond = " AND ".join(f"p.{q(pc)} = c.{q(cc)}" for cc, pc in zip(child_cols, parent_cols))
    ccl = ", ".join(q(c) for c in child_cols)
    pcl = ", ".join(q(c) for c in parent_cols)
    child_rows = con.execute(f"SELECT count(*) FROM {q(child)}").fetchone()[0]
    orphan_rows = con.execute(
        f"""SELECT count(*) FROM {q(child)} c
            WHERE NOT EXISTS (SELECT 1 FROM {q(parent)} p WHERE {cond})"""
    ).fetchone()[0]
    child_keys = con.execute(f"SELECT count(*) FROM (SELECT DISTINCT {ccl} FROM {q(child)})").fetchone()[0]
    orphan_keys = con.execute(
        f"""SELECT count(*) FROM (SELECT DISTINCT {ccl} FROM {q(child)}) c
            WHERE NOT EXISTS (SELECT 1 FROM {q(parent)} p WHERE {cond})"""
    ).fetchone()[0]
    parent_rows = con.execute(f"SELECT count(*) FROM {q(parent)}").fetchone()[0]
    parent_keys = con.execute(f"SELECT count(*) FROM (SELECT DISTINCT {pcl} FROM {q(parent)})").fetchone()[0]
    childless = con.execute(
        f"""SELECT count(*) FROM (SELECT DISTINCT {pcl} FROM {q(parent)}) p
            WHERE NOT EXISTS (SELECT 1 FROM {q(child)} c WHERE {cond})"""
    ).fetchone()[0]
    max_per_key = con.execute(
        f"SELECT coalesce(max(n), 0) FROM (SELECT count(*) AS n FROM {q(child)} GROUP BY {ccl})"
    ).fetchone()[0]
    return {
        "relationship": name,
        "child": child,
        "child_columns": child_cols,
        "parent": parent,
        "parent_columns": parent_cols,
        "child_rows": child_rows,
        "orphan_rows": orphan_rows,
        "match_rate_pct": round(100.0 * (child_rows - orphan_rows) / child_rows, 6) if child_rows else None,
        "distinct_child_keys": child_keys,
        "orphan_distinct_keys": orphan_keys,
        "parent_rows": parent_rows,
        "distinct_parent_keys": parent_keys,
        "parent_key_unique": parent_keys == parent_rows,
        "parent_keys_without_children": childless,
        "max_child_rows_per_key": max_per_key,
    }


def run_check(con, sql):
    try:
        cursor = con.execute(sql)
        names = [d[0] for d in cursor.description]
        return {"columns": names, "rows": [list(r) for r in cursor.fetchmany(200)]}
    except duckdb.Error as error:
        return {"error": str(error)}


def has_columns(columns_by_table, table, needed):
    return all(c in columns_by_table.get(table, []) for c in needed)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", type=Path, default=Path("eval/golden/oulad/raw"))
    parser.add_argument("--out-dir", type=Path, default=Path("eval/golden/oulad/metadata"))
    parser.add_argument("--max-rows", type=int, default=0)
    parser.add_argument("--top-values-limit", type=int, default=40)
    args = parser.parse_args(argv)

    missing = [name for name in EXPECTED_COLUMNS if not (args.raw_dir / f"{name}.csv").is_file()]
    if missing:
        print("missing files: " + ", ".join(f"{m}.csv" for m in missing), file=sys.stderr)
        return 1

    args.out_dir.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(":memory:")
    manifest = {}
    tables = {}
    columns_by_table = {}

    for table in EXPECTED_COLUMNS:
        path = args.raw_dir / f"{table}.csv"
        entry = {"file": path.name, "bytes": path.stat().st_size, "sha256": sha256_of(path)}
        entry.update(inspect_bytes(path))
        entry.update(read_header(path))
        load_table(con, table, path, args.max_rows)
        columns = [r[0] for r in con.execute(f"DESCRIBE {q(table)}").fetchall()]
        columns_by_table[table] = columns
        entry["columns"] = columns
        entry["expected_columns"] = EXPECTED_COLUMNS[table]
        entry["header_matches_expected"] = columns == EXPECTED_COLUMNS[table]
        entry["rows"] = con.execute(f"SELECT count(*) FROM {q(table)}").fetchone()[0]
        manifest[table] = entry

        duplicate_full_rows = con.execute(
            f"SELECT count(*) - (SELECT count(*) FROM (SELECT DISTINCT * FROM {q(table)})) FROM {q(table)}"
        ).fetchone()[0]
        key_columns = CANDIDATE_KEYS[table]
        tables[table] = {
            "rows": entry["rows"],
            "duplicate_full_rows": duplicate_full_rows,
            "candidate_key": (
                profile_key(con, table, key_columns)
                if has_columns(columns_by_table, table, key_columns)
                else {"error": "candidate key columns missing from header"}
            ),
            "columns": {c: profile_column(con, table, c, args.top_values_limit) for c in columns},
        }
        print(f"{table}: rows={entry['rows']} duplicate_full_rows={duplicate_full_rows}")

    relationships = []
    for name, child, child_cols, parent, parent_cols in RELATIONSHIPS:
        if has_columns(columns_by_table, child, child_cols) and has_columns(columns_by_table, parent, parent_cols):
            relationships.append(profile_relationship(con, name, child, child_cols, parent, parent_cols))
        else:
            relationships.append({"relationship": name, "error": "columns missing from header"})

    custom = {name: run_check(con, sql) for name, sql in CUSTOM_CHECKS.items()}

    report = {
        "duckdb_version": duckdb.__version__,
        "max_rows_per_file": args.max_rows or None,
        "null_like_tokens_checked": NULL_TOKENS,
        "tables": tables,
        "relationships": relationships,
        "custom_checks": custom,
    }

    with (args.out_dir / "source_manifest.json").open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, ensure_ascii=True, default=str)
        handle.write("\n")
    with (args.out_dir / "profile_report.json").open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=True, default=str)
        handle.write("\n")

    for rel in relationships:
        if "error" in rel:
            print(f"{rel['relationship']}: {rel['error']}")
        else:
            print(f"{rel['relationship']}: orphan_rows={rel['orphan_rows']} match_rate_pct={rel['match_rate_pct']}")
    print(f"wrote {args.out_dir / 'source_manifest.json'}")
    print(f"wrote {args.out_dir / 'profile_report.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
