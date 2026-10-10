"""Generate TPC-H raw CSV files with the DuckDB tpch extension.

Writes one CSV per table into eval/golden/tpch_sf<N>/raw and a generation manifest
with the DuckDB version, extension version, scale factor, row counts and SHA-256 of
every file. The reference answers of the 22 queries are exported to answers.csv
for each query so that later checks can compare against them.

Usage:
    python eval/golden/tools/generate_tpch.py --sf 0.1
    python eval/golden/tools/generate_tpch.py --sf 1
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import duckdb

TABLES = ["region", "nation", "supplier", "customer", "part", "partsupp", "orders", "lineitem"]


def sha256_of(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--sf", type=float, required=True)
    parser.add_argument("--base", type=Path, default=Path("eval/golden"))
    args = parser.parse_args(argv)

    label = f"{args.sf:g}".replace(".", "_")
    base = args.base / f"tpch_sf{label}"
    raw = base / "raw"
    meta = base / "metadata"
    raw.mkdir(parents=True, exist_ok=True)
    meta.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(":memory:")
    con.execute("INSTALL tpch")
    con.execute("LOAD tpch")
    ext_version = con.execute(
        "SELECT extension_version FROM duckdb_extensions() WHERE extension_name = 'tpch'"
    ).fetchone()
    con.execute(f"CALL dbgen(sf = {args.sf})")

    manifest = {
        "generator": "duckdb tpch extension",
        "duckdb_version": duckdb.__version__,
        "tpch_extension_version": ext_version[0] if ext_version else None,
        "scale_factor": args.sf,
        "tables": {},
        "answers": {},
    }

    for table in TABLES:
        path = raw / f"{table}.csv"
        con.execute(f"COPY {table} TO '{path.as_posix()}' (HEADER, DELIMITER ',')")
        rows = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        manifest["tables"][table] = {
            "file": path.name,
            "rows": rows,
            "bytes": path.stat().st_size,
            "sha256": sha256_of(path),
        }
        print(f"{table}: rows={rows} bytes={path.stat().st_size}")

    answers_dir = meta / "answers"
    answers_dir.mkdir(parents=True, exist_ok=True)
    for number in range(1, 23):
        path = answers_dir / f"q{number:02d}.csv"
        con.execute(
            f"COPY (SELECT * FROM tpch_answers() WHERE query_nr = {number} AND scale_factor = {args.sf}) "
            f"TO '{path.as_posix()}' (HEADER, DELIMITER ',')"
        )
        manifest["answers"][f"q{number:02d}"] = {
            "file": path.name,
            "sha256": sha256_of(path),
        }

    with (meta / "generation_manifest.json").open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, ensure_ascii=True)
        handle.write("\n")
    print(f"wrote {meta / 'generation_manifest.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
