from app.ingest.sniff import CsvReadConfig


def bronze_model_sql(filename: str, config: CsvReadConfig) -> str:
    """TODO: render a bronze model: read_csv(all_varchar) from var('raw_dir') plus lineage columns.

    Lineage columns: _batch_id, _source_file, _row_number, _loaded_at (from var, not now()).
    """
    raise NotImplementedError


def bronze_models(files: dict[str, CsvReadConfig]) -> dict[str, str]:
    """TODO: return {models/bronze/bronze_<table>.sql: sql} for every source file."""
    raise NotImplementedError
