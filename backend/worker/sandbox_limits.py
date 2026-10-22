"""Validated wire contract shared by the sandbox parent and its trusted launcher."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MEBIBYTE = 1024 * 1024
MAX_RESOURCE_BYTES = (1 << 63) - 1


class Limits(BaseModel):
    """Positive budgets; memory/file fields use MiB and output uses combined raw bytes."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, revalidate_instances="always"
    )

    timeout_seconds: int = Field(gt=0, le=(1 << 31) - 2)
    memory_mb: int = Field(gt=0, le=MAX_RESOURCE_BYTES // MEBIBYTE)
    cpu_seconds: int = Field(gt=0, le=(1 << 31) - 2)
    max_file_mb: int = Field(gt=0, le=MAX_RESOURCE_BYTES // MEBIBYTE)
    max_open_files: int = Field(default=256, ge=16, le=(1 << 31) - 1)
    max_processes: int = Field(default=64, gt=0, le=(1 << 31) - 1)
    max_output_bytes: int = Field(default=MEBIBYTE, gt=0, le=64 * MEBIBYTE)


class SandboxLaunchRequest(BaseModel):
    """Versioned, validated argv/limits; no worker settings or credentials are needed."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[1] = 1
    command: list[str] = Field(min_length=1)
    limits: Limits

    @field_validator("command")
    @classmethod
    def validate_command(cls, command: list[str]) -> list[str]:
        if any(not part or "\x00" in part for part in command):
            raise ValueError("Child argv must contain nonempty strings without NUL")
        executable = Path(command[0])
        if not executable.is_absolute() or not executable.is_file():
            raise ValueError("The child executable must be an absolute file path")
        return command
