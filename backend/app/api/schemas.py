import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from app.agents.schemas import DataDesign
from app.db.models import ProjectRole, ReviewMode, RunStatus
from app.ingest.sniff import CsvReadConfig


class RegisterRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"


class ProjectCreate(BaseModel):
    name: str
    slug: str
    review_mode: ReviewMode = ReviewMode.TEAM


class ProjectOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    review_mode: ReviewMode
    roles: list[ProjectRole]


class MemberAdd(BaseModel):
    email: str
    role: ProjectRole


class SourceFileOut(BaseModel):
    id: uuid.UUID
    filename: str
    sha256: str
    size_bytes: int
    read_config: CsvReadConfig
    read_config_confirmed: bool
    columns: list[str]
    preview: list[list[str | None]]
    warnings: list[str]


class BatchOut(BaseModel):
    id: uuid.UUID
    status: str
    files: list[SourceFileOut]


class ReadConfigConfirm(BaseModel):
    read_config: CsvReadConfig


class RunCreate(BaseModel):
    batch_id: uuid.UUID
    request_text: str


class RunOut(BaseModel):
    id: uuid.UUID
    status: RunStatus
    current_step: str | None
    pending: dict[str, Any] | None
    error: str | None
    updated_at: datetime


class ClarificationAnswers(BaseModel):
    answers: list[dict[str, str]]


class DesignDecision(BaseModel):
    decision: Literal["approve", "return"]
    edited_design: DataDesign | None = None
    comment: str | None = None


class CodeDecision(BaseModel):
    decision: Literal["approve", "return"]
    fingerprint: str
    comment: str | None = None


class FileEdit(BaseModel):
    path: str
    content: str


class PullRequestCreate(BaseModel):
    owner: str
    repo: str
    base_branch: str = "main"
