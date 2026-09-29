from pathlib import Path

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
        """TODO: render a DuckDB read_csv(...) expression from this config.

        all_varchar=True is used by bronze so source representation (e.g. 00123) is kept.
        """
        raise NotImplementedError


class SniffResult(BaseModel):
    config: CsvReadConfig
    columns: list[str]
    preview: list[list[str | None]]
    warnings: list[str] = Field(default_factory=list)


def detect_encoding(path: Path) -> tuple[str, list[str]]:
    """TODO: detect utf-8 / utf-16 (BOM) / latin-1 fallback and return warnings."""
    raise NotImplementedError


def detect_null_tokens(path: Path, config: CsvReadConfig) -> list[str]:
    """TODO: find which common null tokens (NULL, NA, N/A, ?, ...) appear in the file."""
    raise NotImplementedError


def sniff_csv(path: Path, preview_rows: int = 10) -> SniffResult:
    """TODO: use DuckDB sniff_csv for delimiter, header, date formats; return a preview (FR-01)."""
    raise NotImplementedError
