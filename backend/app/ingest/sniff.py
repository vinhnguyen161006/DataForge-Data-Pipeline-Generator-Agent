import csv
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class CsvReadConfig(BaseModel):
    encoding: str = "utf-8"
    delimiter: str = ","
    quote: str = '"'
    escape: str = '"'
    has_header: bool = True
    skip_rows: int = 0
    null_tokens: list[str] = Field(default_factory=lambda: [""])
    date_format: str | None = None
    timestamp_format: str | None = None

    def duckdb_read_expr(self, path: str, *, all_varchar: bool) -> str:
        """Render a DuckDB read_csv expression from this configuration."""
        options = [
            f"delim={_sql_literal(self.delimiter)}",
            f"quote={_sql_literal(self.quote)}",
            f"escape={_sql_literal(self.escape)}",
            f"header={'true' if self.has_header else 'false'}",
            f"skip={self.skip_rows}",
            f"nullstr={_sql_list(self.null_tokens)}",
            f"encoding={_sql_literal(self.encoding)}",
            f"all_varchar={'true' if all_varchar else 'false'}",
        ]
        if self.date_format is not None:
            options.append(f"dateformat={_sql_literal(self.date_format)}")
        if self.timestamp_format is not None:
            options.append(f"timestampformat={_sql_literal(self.timestamp_format)}")
        return f"read_csv({_sql_literal(path)}, {', '.join(options)})"


class SniffResult(BaseModel):
    config: CsvReadConfig
    columns: list[str]
    preview: list[list[str | None]]
    warnings: list[str] = Field(default_factory=list)


def detect_encoding(path: Path) -> tuple[str, list[str]]:
    """Detect UTF encodings and use latin-1 only as an explicit fallback."""
    data = path.read_bytes()
    if data.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig", []
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return "utf-16", []
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return "latin-1", ["File is not valid UTF-8; latin-1 fallback was selected."]
    return "utf-8", []


def detect_null_tokens(path: Path, config: CsvReadConfig) -> list[str]:
    """Return common null tokens that occur in the CSV sample."""
    candidates = ["", "NULL", "null", "NA", "N/A", "?", "None", "none"]
    found: list[str] = []
    with path.open("r", encoding=config.encoding, newline="") as stream:
        reader = csv.reader(
            stream,
            delimiter=config.delimiter,
            quotechar=config.quote,
            escapechar=config.escape or None,
        )
        for _ in range(config.skip_rows):
            next(reader, None)
        for row_index, row in enumerate(reader):
            if row_index >= 10_000:
                break
            for token in candidates:
                if token in row and token not in found:
                    found.append(token)
    return found or [""]


def sniff_csv(path: Path, preview_rows: int = 10) -> SniffResult:
    """Infer a reusable CSV configuration and return a bounded preview."""
    if preview_rows < 0:
        raise ValueError("preview_rows must be non-negative")
    encoding, warnings = detect_encoding(path)
    sniffed = _duckdb_sniff(path, encoding)
    config = CsvReadConfig(
        encoding=encoding,
        delimiter=_csv_option(sniffed, "Delimiter", ","),
        quote=_csv_option(sniffed, "Quote", '"'),
        escape=_csv_option(sniffed, "Escape", ""),
        has_header=_result_value(sniffed, "HasHeader", True),
        skip_rows=int(_result_value(sniffed, "SkipRows", 0)),
        date_format=_optional_result_value(sniffed, "DateFormat"),
        timestamp_format=_optional_result_value(sniffed, "TimestampFormat"),
    )
    config.null_tokens = detect_null_tokens(path, config)
    columns, preview = _read_preview(path, config, preview_rows)
    return SniffResult(config=config, columns=columns, preview=preview, warnings=warnings)


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _sql_list(values: list[str]) -> str:
    return "[" + ", ".join(_sql_literal(value) for value in values) + "]"


def _duckdb_sniff(path: Path, encoding: str) -> dict[str, Any]:
    import duckdb

    connection = duckdb.connect()
    try:
        result = connection.execute(
            "SELECT * FROM sniff_csv(?, encoding=?)", [str(path), encoding]
        )
        row = result.fetchone()
        if row is None:
            raise ValueError(f"DuckDB could not sniff CSV: {path}")
        return {description[0]: value for description, value in zip(result.description, row)}
    finally:
        connection.close()


def _result_value(result: dict[str, Any], key: str, default: Any) -> Any:
    value = result.get(key)
    return default if value is None else value


def _csv_option(result: dict[str, Any], key: str, default: str) -> str:
    value = result.get(key)
    if value is None or value == "(empty)":
        return default
    return str(value)


def _optional_result_value(result: dict[str, Any], key: str) -> str | None:
    value = result.get(key)
    return value if isinstance(value, str) and value else None


def _read_preview(
    path: Path, config: CsvReadConfig, preview_rows: int
) -> tuple[list[str], list[list[str | None]]]:
    with path.open("r", encoding=config.encoding, newline="") as stream:
        reader = csv.reader(
            stream,
            delimiter=config.delimiter,
            quotechar=config.quote,
            escapechar=config.escape or None,
        )
        for _ in range(config.skip_rows):
            next(reader, None)
        first_row = next(reader, None)
        if first_row is None:
            return [], []
        if config.has_header:
            columns = first_row
        else:
            columns = [f"column_{index + 1}" for index in range(len(first_row))]
        preview: list[list[str | None]] = []
        if not config.has_header and preview_rows > 0:
            preview.append(_normalize_row(first_row, config.null_tokens))
        for row in reader:
            if len(preview) >= preview_rows:
                break
            preview.append(_normalize_row(row, config.null_tokens))
        return columns, preview


def _normalize_row(row: list[str], null_tokens: list[str]) -> list[str | None]:
    return [None if value in null_tokens else value for value in row]
