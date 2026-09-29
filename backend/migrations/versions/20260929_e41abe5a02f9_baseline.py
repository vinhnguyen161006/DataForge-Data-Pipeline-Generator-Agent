"""baseline

Revision ID: e41abe5a02f9
Revises:
Create Date: 2026-09-29 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e41abe5a02f9"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=63), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("review_mode", sa.Enum("team", "solo", name="review_mode"), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_projects_created_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_projects")),
        sa.UniqueConstraint("slug", name=op.f("uq_projects_slug")),
    )
    op.create_table(
        "batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.Enum("uploading", "ready", name="batch_status"), nullable=False),
        sa.Column("schema_fingerprint", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=op.f("fk_batches_project_id_projects")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_batches")),
    )
    op.create_table(
        "metabase_objects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("logical_key", sa.String(length=255), nullable=False),
        sa.Column("metabase_id", sa.Integer(), nullable=False),
        sa.Column("spec_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=op.f("fk_metabase_objects_project_id_projects")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_metabase_objects")),
        sa.UniqueConstraint(
            "project_id",
            "kind",
            "logical_key",
            name=op.f("uq_metabase_objects_project_id_kind_logical_key"),
        ),
    )
    op.create_table(
        "project_members",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.Enum("engineer", "reviewer", name="project_role"), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=op.f("fk_project_members_project_id_projects")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_project_members_user_id_users")
        ),
        sa.PrimaryKeyConstraint("project_id", "user_id", "role", name=op.f("pk_project_members")),
    )
    op.create_table(
        "pipeline_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("request_text", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "running",
                "waiting_clarification",
                "waiting_design_approval",
                "waiting_job",
                "waiting_code_approval",
                "published",
                "failed",
                name="run_status",
            ),
            nullable=False,
        ),
        sa.Column("current_step", sa.String(length=64), nullable=True),
        sa.Column("pending", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"], ["batches.id"], name=op.f("fk_pipeline_runs_batch_id_batches")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=op.f("fk_pipeline_runs_project_id_projects")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pipeline_runs")),
    )
    op.create_table(
        "source_files",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("read_config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("read_config_confirmed", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"], ["batches.id"], name=op.f("fk_source_files_batch_id_batches")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_files")),
    )
    op.create_table(
        "approvals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("gate", sa.Enum("design", "code", name="gate"), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("fingerprint_parts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "decision", sa.Enum("approved", "returned", name="approval_decision"), nullable=False
        ),
        sa.Column("approver_id", sa.Uuid(), nullable=False),
        sa.Column("independent_review", sa.Boolean(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["approver_id"], ["users.id"], name=op.f("fk_approvals_approver_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=op.f("fk_approvals_project_id_projects")
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["pipeline_runs.id"], name=op.f("fk_approvals_run_id_pipeline_runs")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_approvals")),
    )
    op.create_table(
        "design_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("edited_by_user", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["pipeline_runs.id"], name=op.f("fk_design_versions_run_id_pipeline_runs")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_design_versions")),
        sa.UniqueConstraint("run_id", "version", name=op.f("uq_design_versions_run_id_version")),
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("queue", sa.Enum("sandbox", "publisher", name="job_queue"), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("serial_key", sa.String(length=255), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column(
            "status",
            sa.Enum("queued", "running", "succeeded", "failed", name="job_status"),
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column(
            "run_after", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("locked_by", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("delivered", sa.Boolean(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["pipeline_runs.id"], name=op.f("fk_jobs_run_id_pipeline_runs")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_jobs_idempotency_key")),
    )
    op.create_index(op.f("ix_jobs_serial_key"), "jobs", ["serial_key"], unique=False)
    op.create_index(op.f("ix_jobs_status"), "jobs", ["status"], unique=False)
    op.create_index(
        "uq_jobs_running_serial_key",
        "jobs",
        ["serial_key"],
        unique=True,
        postgresql_where=sa.text("status = 'running' AND serial_key IS NOT NULL"),
    )
    op.create_table(
        "rewrite_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=False),
        sa.Column("original_sql", sa.Text(), nullable=False),
        sa.Column("candidate_sql", sa.Text(), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["pipeline_runs.id"], name=op.f("fk_rewrite_attempts_run_id_pipeline_runs")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rewrite_attempts")),
    )
    op.create_table(
        "code_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("design_version_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("tests_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "origin",
            sa.Enum("codegen", "optimizer", "user_edit", name="code_origin"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["design_version_id"],
            ["design_versions.id"],
            name=op.f("fk_code_versions_design_version_id_design_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["pipeline_runs.id"], name=op.f("fk_code_versions_run_id_pipeline_runs")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_code_versions")),
        sa.UniqueConstraint("run_id", "version", name=op.f("uq_code_versions_run_id_version")),
    )
    op.create_table(
        "execution_reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code_version_id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("report", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("report_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"], ["batches.id"], name=op.f("fk_execution_reports_batch_id_batches")
        ),
        sa.ForeignKeyConstraint(
            ["code_version_id"],
            ["code_versions.id"],
            name=op.f("fk_execution_reports_code_version_id_code_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name=op.f("fk_execution_reports_job_id_jobs")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_execution_reports")),
    )
    op.create_table(
        "published_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("code_version_id", sa.Uuid(), nullable=False),
        sa.Column("approval_id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("staging_schema", sa.String(length=63), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("reconciliation", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["approval_id"],
            ["approvals.id"],
            name=op.f("fk_published_versions_approval_id_approvals"),
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"], ["batches.id"], name=op.f("fk_published_versions_batch_id_batches")
        ),
        sa.ForeignKeyConstraint(
            ["code_version_id"],
            ["code_versions.id"],
            name=op.f("fk_published_versions_code_version_id_code_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=op.f("fk_published_versions_project_id_projects")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_published_versions")),
    )


def downgrade() -> None:
    op.drop_table("published_versions")
    op.drop_table("execution_reports")
    op.drop_table("code_versions")
    op.drop_table("rewrite_attempts")
    op.drop_index(op.f("ix_jobs_serial_key"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_status"), table_name="jobs")
    op.drop_index(
        "uq_jobs_running_serial_key",
        table_name="jobs",
        postgresql_where=sa.text("status = 'running' AND serial_key IS NOT NULL"),
    )
    op.drop_table("jobs")
    op.drop_table("design_versions")
    op.drop_table("approvals")
    op.drop_table("source_files")
    op.drop_table("pipeline_runs")
    op.drop_table("project_members")
    op.drop_table("metabase_objects")
    op.drop_table("batches")
    op.drop_table("projects")
    op.drop_table("users")
    sa.Enum(name="approval_decision").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="batch_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="code_origin").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="gate").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="job_queue").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="job_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="project_role").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="review_mode").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="run_status").drop(op.get_bind(), checkfirst=True)
