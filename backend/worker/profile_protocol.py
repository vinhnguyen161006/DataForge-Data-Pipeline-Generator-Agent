"""Explicit metadata-only protocol between the profile parent and child."""

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ingest.manifest import BatchManifest
from app.jobs.profile import ProfileJobPayload
from app.profiler.schemas import DataProfile
from worker.duckdb_runtime import DuckDBLimits

MAX_PROTOCOL_BYTES = 4 * 1024 * 1024


class ProfileIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: uuid.UUID
    batch_id: uuid.UUID
    run_id: uuid.UUID
    job_id: uuid.UUID
    attempt: int = Field(gt=0, strict=True)


class PreparedProfileJob(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    identity: ProfileIdentity
    payload: ProfileJobPayload
    manifest: BatchManifest

    @model_validator(mode="after")
    def consistent_snapshot(self) -> "PreparedProfileJob":
        if (
            self.identity.project_id != self.payload.project_id
            or self.identity.batch_id != self.payload.batch_id
            or self.manifest.project_id != self.identity.project_id
            or self.manifest.batch_id != self.identity.batch_id
            or self.manifest.digest() != self.payload.manifest_sha256
        ):
            raise ValueError("Profile identity and snapshot must agree")
        return self


class ProfileChildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    job: PreparedProfileJob
    duckdb_limits: DuckDBLimits = Field(default_factory=DuckDBLimits)


class ProfileChildResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    identity: ProfileIdentity
    profile: DataProfile
