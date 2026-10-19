"""Verify canonical manifests, explicit preview config and atomic filesystem failure behavior."""

from __future__ import annotations

import hashlib
import io
import os
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.ingest.manifest import BatchManifest, BatchManifestFile
from app.ingest.sniff import CsvReadConfig, read_csv_preview
from app.ingest.storage import Storage

if TYPE_CHECKING:
    from pathlib import Path


def snapshot() -> BatchManifest:
    return BatchManifest(
        project_id=uuid4(),
        batch_id=uuid4(),
        required_files=["orders.csv", "customers.csv"],
        files=[
            BatchManifestFile(
                file_id=uuid4(),
                filename=name,
                relative_path=f"raw/{name}",
                sha256="a" * 64,
                size_bytes=100,
                read_config=CsvReadConfig(),
                read_config_confirmed=True,
            )
            for name in ("orders.csv", "customers.csv")
        ],
    )


def test_manifest_hash_ignores_only_file_order() -> None:
    original = snapshot()
    reordered = BatchManifest.model_validate(
        {
            **original.model_dump(mode="json"),
            "required_files": list(reversed(original.required_files)),
            "files": [file.model_dump(mode="json") for file in reversed(original.files)],
        }
    )
    assert original.canonical_bytes() == reordered.canonical_bytes()
    assert original.digest() == reordered.digest()
    changed = original.model_dump(mode="json")
    changed["files"][0]["read_config"]["null_tokens"] = ["", "NA"]
    assert BatchManifest.model_validate(changed).digest() != original.digest()
    changed = original.model_dump(mode="json")
    changed["batch_id"] = str(uuid4())
    assert BatchManifest.model_validate(changed).digest() != original.digest()


@pytest.mark.parametrize("damage", ["path", "missing", "duplicate", "version", "unconfirmed"])
def test_manifest_rejects_invalid_snapshot(damage: str) -> None:
    content = snapshot().model_dump(mode="json")
    if damage == "path":
        content["files"][0]["relative_path"] = "../orders.csv"
    elif damage == "missing":
        content["files"].pop()
    elif damage == "duplicate":
        content["files"].append(content["files"][0])
    elif damage == "version":
        content["manifest_version"] = 2
    else:
        content["files"][0]["read_config_confirmed"] = False
    with pytest.raises(ValidationError):
        BatchManifest.model_validate(content)


def test_explicit_preview_handles_standard_doubled_quotes_and_preserves_bytes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "quoted.csv"
    original = b'id;note\n001;"He said ""hello"""\n002;NA\n'
    path.write_bytes(original)
    result = read_csv_preview(path, CsvReadConfig(delimiter=";", null_tokens=["NA"]))
    assert result.preview == [["001", 'He said "hello"'], ["002", None]]
    assert path.read_bytes() == original


def test_failed_manifest_replace_keeps_previous_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = Storage(tmp_path)
    project, batch = uuid4(), uuid4()
    storage.write_manifest(project, batch, b"old")

    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError("Injected atomic replacement failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="Injected"):
        storage.write_manifest(project, batch, b"new")
    assert storage.manifest_path(project, batch).read_bytes() == b"old"
    assert not list(tmp_path.rglob("*.part"))


def test_concurrent_raw_writers_never_replace_each_other(tmp_path: Path) -> None:
    storage = Storage(tmp_path)
    target = tmp_path / "raw" / "source.csv"
    contents = [b"id\n001\n", b"id\n002\n"]

    def write(content: bytes) -> bool:
        try:
            storage.save_raw(target, io.BytesIO(content))
        except FileExistsError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(write, contents))
    assert outcomes.count(True) == 1
    winner = contents[outcomes.index(True)]
    assert target.read_bytes() == winner
    assert hashlib.sha256(target.read_bytes()).digest() == hashlib.sha256(winner).digest()
    assert not list(tmp_path.rglob("*.part"))
