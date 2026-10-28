"""Versioned persisted payload for deterministic profiling jobs."""

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ProfileJobPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    project_id: uuid.UUID
    batch_id: uuid.UUID
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
