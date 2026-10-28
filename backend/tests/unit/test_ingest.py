import hashlib
import io
import uuid
from pathlib import Path

import pytest

from app.ingest.sniff import CsvReadConfig, detect_encoding, sniff_csv
from app.ingest.storage import Storage


def test_sniff_csv_handles_semicolon_quotes_and_nulls(tmp_path: Path) -> None:
    path = tmp_path / "source.csv"
    path.write_text(
        'id;name;note\n00123;"Alice";"line one\nline two"\n00456;NA;?\n',
        encoding="utf-8",
    )

    result = sniff_csv(path, preview_rows=2)

    assert result.config.encoding == "utf-8"
    assert result.config.delimiter == ";"
    assert result.config.has_header is True
    assert result.config.null_tokens == ["NA", "?"]
    assert result.columns == ["id", "name", "note"]
    assert result.preview[0][:2] == ["00123", "Alice"]
    assert isinstance(result.preview[0][2], str)
    assert result.preview[0][2].splitlines() == ["line one", "line two"]
    assert result.preview[1] == ["00456", None, None]


def test_sniff_csv_handles_utf16_bom(tmp_path: Path) -> None:
    path = tmp_path / "source.csv"
    path.write_text("id,name\n1,Alice\n", encoding="utf-16")

    result = sniff_csv(path)

    assert result.config.encoding == "utf-16"
    assert result.columns == ["id", "name"]
    assert result.preview == [["1", "Alice"]]


def test_sniff_csv_warns_on_latin1_fallback(tmp_path: Path) -> None:
    path = tmp_path / "source.csv"
    path.write_bytes("name\nAndr\xe9\n".encode("latin-1"))

    encoding, warnings = detect_encoding(path)

    assert encoding == "latin-1"
    assert warnings


def test_read_expression_preserves_source_text() -> None:
    config = CsvReadConfig(delimiter=";", null_tokens=["", "NA"])

    expression = config.duckdb_read_expr("C:\\data\\source.csv", all_varchar=True)

    assert "all_varchar=true" in expression
    assert "delim=';'" in expression
    assert "nullstr=['', 'NA']" in expression
    assert "C:\\data\\source.csv" in expression


def test_storage_paths_strip_filename_directories(tmp_path: Path) -> None:
    storage = Storage(tmp_path)
    project_id = uuid.uuid4()
    batch_id = uuid.uuid4()

    path = storage.raw_path(project_id, batch_id, "..\\nested/source.csv")

    assert path == storage.batch_dir(project_id, batch_id) / "raw" / "source.csv"
    assert path.is_relative_to(storage.root)


def test_storage_save_raw_is_atomic_and_does_not_overwrite(tmp_path: Path) -> None:
    storage = Storage(tmp_path)
    destination = tmp_path / "projects" / "p" / "b" / "raw" / "source.csv"
    content = b"id,name\n00123,Alice\n"

    digest, size = storage.save_raw(destination, io.BytesIO(content))

    assert digest == hashlib.sha256(content).hexdigest()
    assert size == len(content)
    assert destination.read_bytes() == content
    assert not destination.with_name("source.csv.part").exists()
    with pytest.raises(FileExistsError):
        storage.save_raw(destination, io.BytesIO(b"replacement"))
    assert destination.read_bytes() == content


def test_storage_rejects_destination_outside_root(tmp_path: Path) -> None:
    storage = Storage(tmp_path)

    with pytest.raises(ValueError, match="destination must be inside the storage root"):
        storage.save_raw(tmp_path.parent / "outside.csv", io.BytesIO(b"data"))


def test_storage_marks_non_empty_batch_ready(tmp_path: Path) -> None:
    storage = Storage(tmp_path)
    project_id = uuid.uuid4()
    batch_id = uuid.uuid4()
    destination = storage.raw_path(project_id, batch_id, "source.csv")
    storage.save_raw(destination, io.BytesIO(b"id\n1\n"))

    content = b'{"manifest_version":1}'
    storage.write_manifest(project_id, batch_id, content)
    digest = hashlib.sha256(content).hexdigest()
    storage.mark_ready(project_id, batch_id, digest)
    storage.mark_ready(project_id, batch_id, digest)

    assert (storage.batch_dir(project_id, batch_id) / "_READY").is_file()


def test_storage_does_not_mark_empty_batch_ready(tmp_path: Path) -> None:
    storage = Storage(tmp_path)

    with pytest.raises(ValueError, match="cannot mark an empty batch ready"):
        storage.mark_ready(uuid.uuid4(), uuid.uuid4(), "0" * 64)
