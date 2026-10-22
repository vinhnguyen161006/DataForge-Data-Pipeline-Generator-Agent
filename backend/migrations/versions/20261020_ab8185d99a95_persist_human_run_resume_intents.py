"""persist human run resume intents

Revision ID: ab8185d99a95
Revises: 25810a2b5deb
Create Date: 2026-10-20 14:42:00.584847
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "ab8185d99a95"
down_revision: str | None = "25810a2b5deb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "run_resume_intents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("interrupt_id", sa.String(length=128), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column(
            "payload",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("delivered", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name=op.f("fk_run_resume_intents_actor_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["pipeline_runs.id"],
            name=op.f("fk_run_resume_intents_run_id_pipeline_runs"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_run_resume_intents")),
        sa.UniqueConstraint(
            "run_id", "interrupt_id", name=op.f("uq_run_resume_intents_run_id_interrupt_id")
        ),
    )
    op.create_index(
        op.f("ix_run_resume_intents_delivered"), "run_resume_intents", ["delivered"], unique=False
    )
    op.add_column("pipeline_runs", sa.Column("interrupt_id", sa.String(length=128), nullable=True))


def downgrade() -> None:
    op.drop_column("pipeline_runs", "interrupt_id")
    op.drop_index(op.f("ix_run_resume_intents_delivered"), table_name="run_resume_intents")
    op.drop_table("run_resume_intents")
