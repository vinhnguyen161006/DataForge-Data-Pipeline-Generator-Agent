import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.agents.schemas import DataDesign
from app.db.models import (
    ApprovalDecision,
    Gate,
    ProjectRole,
    ReviewMode,
    RunStatus,
)
from app.ingest.filenames import required_filenames
from app.ingest.sniff import CsvReadConfig


class ApprovalHistoryOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    run_id: uuid.UUID
    gate: Gate
    decision: ApprovalDecision
    approver_id: uuid.UUID
    independent_review: bool
    fingerprint: str
    comment: str | None
    created_at: datetime
    review_note: str | None


def normalize_email(email: str) -> str:
    """Normalize account email addresses consistently."""
    return email.strip().lower()


class RegisterRequest(BaseModel):
    email: str = Field(
        min_length=3,
        max_length=320,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    )
    password: str = Field(min_length=15, max_length=1024)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email_input(cls, value: Any) -> Any:
        if isinstance(value, str):
            return normalize_email(value)
        return value


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(
        min_length=1,
        max_length=63,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    )
    review_mode: ReviewMode = ReviewMode.TEAM

    @field_validator("name", "slug", mode="before")
    @classmethod
    def trim_input(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()
        return value


class ProjectOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    review_mode: ReviewMode
    roles: list[ProjectRole]


class MemberAdd(BaseModel):
    email: str = Field(
        min_length=3,
        max_length=320,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    )
    role: ProjectRole

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email_input(cls, value: Any) -> Any:
        if isinstance(value, str):
            return normalize_email(value)
        return value


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


class BatchCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required_files: list[str] = Field(min_length=1)

    @field_validator("required_files")
    @classmethod
    def validate_required_files(cls, values: list[str]) -> list[str]:
        return required_filenames(values)


class BatchOut(BaseModel):
    id: uuid.UUID
    status: str
    files: list[SourceFileOut]
    required_files: list[str] | None = None


class ReadConfigConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")

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
