import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

JsonType = JSON().with_variant(JSONB(), "postgresql")

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _enum(cls: type[enum.Enum], name: str) -> Enum:
    return Enum(cls, name=name, values_callable=lambda members: [m.value for m in members])


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ProjectRole(enum.StrEnum):
    ENGINEER = "engineer"
    REVIEWER = "reviewer"


class ReviewMode(enum.StrEnum):
    TEAM = "team"
    SOLO = "solo"


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)


class Project(TimestampMixin, Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(63), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    review_mode: Mapped[ReviewMode] = mapped_column(
        _enum(ReviewMode, "review_mode"), default=ReviewMode.TEAM, nullable=False
    )
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)


class ProjectMember(Base):
    __tablename__ = "project_members"

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    role: Mapped[ProjectRole] = mapped_column(_enum(ProjectRole, "project_role"), primary_key=True)


class BatchStatus(enum.StrEnum):
    UPLOADING = "uploading"
    READY = "ready"


class Batch(TimestampMixin, Base):
    __tablename__ = "batches"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    status: Mapped[BatchStatus] = mapped_column(
        _enum(BatchStatus, "batch_status"), default=BatchStatus.UPLOADING, nullable=False
    )
    schema_fingerprint: Mapped[str | None] = mapped_column(String(64))


class SourceFile(TimestampMixin, Base):
    __tablename__ = "source_files"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("batches.id"), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    read_config: Mapped[dict[str, Any]] = mapped_column(JsonType, nullable=False)
    read_config_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class RunStatus(enum.StrEnum):
    RUNNING = "running"
    WAITING_CLARIFICATION = "waiting_clarification"
    WAITING_DESIGN_APPROVAL = "waiting_design_approval"
    WAITING_JOB = "waiting_job"
    WAITING_CODE_APPROVAL = "waiting_code_approval"
    PUBLISHED = "published"
    FAILED = "failed"


class PipelineRun(TimestampMixin, Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("batches.id"), nullable=False)
    request_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[RunStatus] = mapped_column(
        _enum(RunStatus, "run_status"), default=RunStatus.RUNNING, nullable=False
    )
    current_step: Mapped[str | None] = mapped_column(String(64))
    pending: Mapped[dict[str, Any] | None] = mapped_column(JsonType)
    error: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class DesignVersion(TimestampMixin, Base):
    __tablename__ = "design_versions"
    __table_args__ = (UniqueConstraint("run_id", "version"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pipeline_runs.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JsonType, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    edited_by_user: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class CodeOrigin(enum.StrEnum):
    CODEGEN = "codegen"
    OPTIMIZER = "optimizer"
    USER_EDIT = "user_edit"


class CodeVersion(TimestampMixin, Base):
    __tablename__ = "code_versions"
    __table_args__ = (UniqueConstraint("run_id", "version"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pipeline_runs.id"), nullable=False)
    design_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("design_versions.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    tests_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    origin: Mapped[CodeOrigin] = mapped_column(_enum(CodeOrigin, "code_origin"), nullable=False)


class ExecutionReport(TimestampMixin, Base):
    __tablename__ = "execution_reports"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    code_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("code_versions.id"), nullable=False
    )
    batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("batches.id"), nullable=False)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id"), nullable=False)
    report: Mapped[dict[str, Any]] = mapped_column(JsonType, nullable=False)
    report_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class RewriteAttempt(TimestampMixin, Base):
    __tablename__ = "rewrite_attempts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pipeline_runs.id"), nullable=False)
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    original_sql: Mapped[str] = mapped_column(Text, nullable=False)
    candidate_sql: Mapped[str] = mapped_column(Text, nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JsonType, nullable=False)


class Gate(enum.StrEnum):
    DESIGN = "design"
    CODE = "code"


class ApprovalDecision(enum.StrEnum):
    APPROVED = "approved"
    RETURNED = "returned"


class Approval(TimestampMixin, Base):
    __tablename__ = "approvals"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pipeline_runs.id"), nullable=False)
    gate: Mapped[Gate] = mapped_column(_enum(Gate, "gate"), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    fingerprint_parts: Mapped[dict[str, Any]] = mapped_column(JsonType, nullable=False)
    decision: Mapped[ApprovalDecision] = mapped_column(
        _enum(ApprovalDecision, "approval_decision"), nullable=False
    )
    approver_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    independent_review: Mapped[bool] = mapped_column(Boolean, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)


class JobQueue(enum.StrEnum):
    SANDBOX = "sandbox"
    PUBLISHER = "publisher"


class JobStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class Job(TimestampMixin, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index(
            "uq_jobs_running_serial_key",
            "serial_key",
            unique=True,
            postgresql_where=text("status = 'running' AND serial_key IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    queue: Mapped[JobQueue] = mapped_column(_enum(JobQueue, "job_queue"), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JsonType, nullable=False)
    serial_key: Mapped[str | None] = mapped_column(String(255), index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), unique=True)
    status: Mapped[JobStatus] = mapped_column(
        _enum(JobStatus, "job_status"), default=JobStatus.QUEUED, nullable=False, index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    run_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    locked_by: Mapped[str | None] = mapped_column(String(128))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict[str, Any] | None] = mapped_column(JsonType)
    last_error: Mapped[str | None] = mapped_column(Text)
    delivered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("pipeline_runs.id"))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PublishedVersion(TimestampMixin, Base):
    __tablename__ = "published_versions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    code_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("code_versions.id"), nullable=False
    )
    approval_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("approvals.id"), nullable=False)
    batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("batches.id"), nullable=False)
    staging_schema: Mapped[str] = mapped_column(String(63), nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reconciliation: Mapped[dict[str, Any]] = mapped_column(JsonType, nullable=False)


class MetabaseObject(TimestampMixin, Base):
    __tablename__ = "metabase_objects"
    __table_args__ = (UniqueConstraint("project_id", "kind", "logical_key"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    logical_key: Mapped[str] = mapped_column(String(255), nullable=False)
    metabase_id: Mapped[int] = mapped_column(Integer, nullable=False)
    spec_hash: Mapped[str] = mapped_column(String(64), nullable=False)
