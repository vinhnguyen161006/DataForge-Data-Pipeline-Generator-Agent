from pathlib import Path

from app.ingest.sniff import CsvReadConfig


def bronze_model_sql(filename: str, config: CsvReadConfig) -> str:
    """Render a bronze model: read_csv(all_varchar) from var('raw_dir') plus lineage columns."""
    sql = f"""
SELECT
    *,
    '{{{{ var("batch_id") }}}}' AS _batch_id,
    '{filename}' AS _source_file,
    row_number() OVER () AS _row_number,
    '{{{{ var("loaded_at") }}}}' AS _loaded_at
FROM read_csv(
    '{{{{ var("raw_dir") }}}}/{filename}',
    all_varchar=true
)
"""
    return sql.strip()


def bronze_models(files: dict[str, CsvReadConfig]) -> dict[str, str]:
    """Return {{models/bronze/bronze_<table>.sql: sql}} for every source file."""
    models = {}
    for filename, config in files.items():
        table_name = Path(filename).stem
        safe_name = "".join(c if c.isalnum() else "_" for c in table_name)
        model_path = f"models/bronze/bronze_{safe_name}.sql"
        models[model_path] = bronze_model_sql(filename, config)

    return models
