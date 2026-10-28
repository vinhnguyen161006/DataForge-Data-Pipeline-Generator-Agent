"""Versioned immutable batch snapshots and canonical serialization."""

import hashlib
import json
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.ingest.filenames import csv_filename, required_filenames
from app.ingest.sniff import CsvReadConfig


class BatchManifestFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    file_id: uuid.UUID
    filename: str
    relative_path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    read_config: CsvReadConfig
    read_config_confirmed: Literal[True]

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str) -> str:
        return csv_filename(value)

    @model_validator(mode="after")
    def validate_path(self) -> "BatchManifestFile":
        if self.relative_path != f"raw/{self.filename}":
            raise ValueError("Manifest paths must identify the declared file inside raw/")
        return self


class BatchManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest_version: Literal[1] = 1
    project_id: uuid.UUID
    batch_id: uuid.UUID
    required_files: list[str]
    files: list[BatchManifestFile]

    @field_validator("required_files")
    @classmethod
    def validate_required(cls, values: list[str]) -> list[str]:
        return required_filenames(values)

    @model_validator(mode="after")
    def validate_files(self) -> "BatchManifest":
        names = [file.filename for file in self.files]
        if sorted(names) != self.required_files:
            raise ValueError("Manifest must contain each required file exactly once")
        return self

    def canonical_bytes(self) -> bytes:
        content = self.model_dump(mode="json")
        content["files"] = sorted(content["files"], key=lambda file: file["filename"])
        return json.dumps(
            content, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")

    def digest(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()
