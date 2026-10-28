import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.agents.schemas import DataDesign
from app.db.models import (
    ApprovalDecision,
    CodeOrigin,
    Gate,
    JobStatus,
    ProjectRole,
    ReviewMode,
    RunStatus,
)
from app.ingest.filenames import required_filenames
from app.ingest.sniff import CsvReadConfig
from app.jobs.reports import ExecutionReportData


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

    @field_validator("request_text")
    @classmethod
    def validate_request_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("The analytical requirement cannot be empty")
        return value


class RunOut(BaseModel):
    id: uuid.UUID
    status: RunStatus
    current_step: str | None
    pending: dict[str, Any] | None
    error: str | None
    updated_at: datetime
    interrupt_id: str | None = None


class BuildAttemptOut(BaseModel):
    """One generated code version and its sandbox build, if one was queued (FR-11)."""

    code_version_id: uuid.UUID
    version: int
    origin: CodeOrigin
    generated_at: datetime
    job_status: JobStatus | None
    queued_at: datetime | None
    finished_at: datetime | None
    report: ExecutionReportData | None


class RunBuildsOut(BaseModel):
    attempts: list[BuildAttemptOut]


class ClarificationAnswerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)

    @field_validator("question", "answer")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("The value cannot be blank")
        return value

    @field_validator("answer")
    @classmethod
    def trim_answer(cls, value: str) -> str:
        return value.strip()


class ClarificationAnswers(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interrupt_id: str = Field(min_length=1, max_length=128)
    answers: list[ClarificationAnswerIn] = Field(min_length=1)


class DesignDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interrupt_id: str = Field(min_length=1, max_length=128)
    design_version_id: uuid.UUID
    decision: Literal["approve", "return"]
    edited_design: DataDesign | None = None
    comment: str | None = None

    @field_validator("comment")
    @classmethod
    def normalize_comment(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @model_validator(mode="after")
    def validate_decision(self) -> "DesignDecision":
        if self.decision == "return":
            if self.edited_design is not None:
                raise ValueError("A returned design cannot carry edits")
            if self.comment is None:
                raise ValueError("Returning a design requires feedback")
        return self


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
