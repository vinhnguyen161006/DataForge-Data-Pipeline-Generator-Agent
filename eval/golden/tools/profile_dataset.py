"""Profile a set of CSV files described by a JSON config.

Writes source_manifest.json and profile_report.json. Every column is read as VARCHAR
so that no raw value is altered or coerced.

Usage:
    python eval/golden/tools/profile_dataset.py --config eval/golden/tools/configs/olist.json
Smoke test on the first N rows of each file:
    python eval/golden/tools/profile_dataset.py --config eval/golden/tools/configs/olist.json --max-rows 1000

Config keys:
    dataset            short name; default raw dir is eval/golden/<dataset>/raw
    files              table name -> csv file name
    expected_columns   optional, table name -> ordered column list
    candidate_keys     table name -> list of candidate key column lists
    relationships      list of [name, child, child_columns, parent, parent_columns]
    custom_checks      name -> SQL text (string or list of lines)
    null_tokens        optional list of strings treated as missing
"""

import argparse
import codecs
import hashlib
import json
import sys
from pathlib import Path

import duckdb

DEFAULT_NULL_TOKENS = ["", "?", "NA", "N/A", "NULL", "null", "NaN"]
NO_NULL = "__DATAFORGE_NO_NULL__"
NON_ASCII = bytes(range(128, 256))
REQUIRED_KEYS = ("dataset", "files", "candidate_keys", "relationships", "custom_checks")


def q(name):
    return '"' + name.replace('"', '""') + '"'


def lit(value):
    return "'" + value.replace("'", "''") + "'"


def null_sql(column, tokens):
    in_list = ", ".join(lit(token) for token in tokens)
    return f"({q(column)} IS NULL OR {q(column)} IN ({in_list}))"


def as_sql(value):
    return "\n".join(value) if isinstance(value, list) else value


def load_config(path):
    config = json.loads(path.read_text(encoding="utf-8"))
    for key in REQUIRED_KEYS:
        if key not in config:
            raise SystemExit(f"config is missing key: {key}")
    config.setdefault("expected_columns", {})
    config.setdefault("null_tokens", DEFAULT_NULL_TOKENS)
    config["custom_checks"] = {name: as_sql(sql) for name, sql in config["custom_checks"].items()}
    return config


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


def profile_column(con, table, column, top_limit, tokens):
    c = q(column)
    t = q(table)
    row = con.execute(
        f"""SELECT count(*),
                   sum(CASE WHEN {null_sql(column, tokens)} THEN 1 ELSE 0 END),
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
    token_rows = con.execute(
        f"""SELECT {c}, count(*) FROM {t}
            WHERE {null_sql(column, tokens)} GROUP BY 1 ORDER BY 2 DESC"""
    ).fetchall()
    result = {
        "rows": rows,
        "null_like_rows": null_like,
        "null_like_rate_pct": round(100.0 * null_like / rows, 4) if rows else None,
        "null_like_tokens": {("<SQL_NULL>" if k is None else k): v for k, v in token_rows},
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


def profile_key(con, table, key_columns, tokens):
    t = q(table)
    cols = ", ".join(q(c) for c in key_columns)
    null_cond = " OR ".join(null_sql(c, tokens) for c in key_columns)
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


def write_json(path, payload):
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=True, default=str)
        handle.write("\n")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--raw-dir", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--max-rows", type=int, default=0)
    parser.add_argument("--top-values-limit", type=int, default=40)
    args = parser.parse_args(argv)

    config = load_config(args.config)
    base = Path("eval/golden") / config["dataset"]
    raw_dir = args.raw_dir or base / "raw"
    out_dir = args.out_dir or base / "metadata"
    files = config["files"]
    tokens = config["null_tokens"]

    missing = [name for name in files.values() if not (raw_dir / name).is_file()]
    if missing:
        print("missing files: " + ", ".join(missing), file=sys.stderr)
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(":memory:")
    manifest = {}
    tables = {}
    columns_by_table = {}

    for table, filename in files.items():
        path = raw_dir / filename
        entry = {"file": path.name, "bytes": path.stat().st_size, "sha256": sha256_of(path)}
        entry.update(inspect_bytes(path))
        entry.update(read_header(path))
        load_table(con, table, path, args.max_rows)
        columns = [r[0] for r in con.execute(f"DESCRIBE {q(table)}").fetchall()]
        columns_by_table[table] = columns
        expected = config["expected_columns"].get(table)
        entry["columns"] = columns
        entry["expected_columns"] = expected
        entry["header_matches_expected"] = (columns == expected) if expected is not None else None
        entry["rows"] = con.execute(f"SELECT count(*) FROM {q(table)}").fetchone()[0]
        manifest[table] = entry

        duplicate_full_rows = con.execute(
            f"SELECT count(*) - (SELECT count(*) FROM (SELECT DISTINCT * FROM {q(table)})) FROM {q(table)}"
        ).fetchone()[0]
        key_profiles = []
        for key_columns in config["candidate_keys"].get(table, []):
            if has_columns(columns_by_table, table, key_columns):
                key_profiles.append(profile_key(con, table, key_columns, tokens))
            else:
                key_profiles.append({"key_columns": key_columns, "error": "key columns missing from header"})
        tables[table] = {
            "rows": entry["rows"],
            "duplicate_full_rows": duplicate_full_rows,
            "candidate_keys": key_profiles,
            "columns": {c: profile_column(con, table, c, args.top_values_limit, tokens) for c in columns},
        }
        print(f"{table}: rows={entry['rows']} duplicate_full_rows={duplicate_full_rows}")
        for key in key_profiles:
            if "error" in key:
                print(f"  key {key['key_columns']}: {key['error']}")
            else:
                print(f"  key {key['key_columns']}: uniqueness_pct={key['uniqueness_pct']}")

    relationships = []
    for name, child, child_cols, parent, parent_cols in config["relationships"]:
        if has_columns(columns_by_table, child, child_cols) and has_columns(columns_by_table, parent, parent_cols):
            relationships.append(profile_relationship(con, name, child, child_cols, parent, parent_cols))
        else:
            relationships.append({"relationship": name, "error": "columns missing from header"})

    custom = {name: run_check(con, sql) for name, sql in config["custom_checks"].items()}

    report = {
        "dataset": config["dataset"],
        "duckdb_version": duckdb.__version__,
        "max_rows_per_file": args.max_rows or None,
        "null_like_tokens_checked": tokens,
        "tables": tables,
        "relationships": relationships,
        "custom_checks": custom,
    }
    write_json(out_dir / "source_manifest.json", manifest)
    write_json(out_dir / "profile_report.json", report)

    for rel in relationships:
        if "error" in rel:
            print(f"{rel['relationship']}: {rel['error']}")
        else:
            print(f"{rel['relationship']}: orphan_rows={rel['orphan_rows']} match_rate_pct={rel['match_rate_pct']}")
    failed = [name for name, result in custom.items() if "error" in result]
    print(f"custom checks: {len(custom)} run, {len(failed)} failed")
    for name in failed:
        print(f"  failed: {name}: {custom[name]['error']}")
    print(f"wrote {out_dir / 'source_manifest.json'}")
    print(f"wrote {out_dir / 'profile_report.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
