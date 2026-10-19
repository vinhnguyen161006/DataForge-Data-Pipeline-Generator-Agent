"""Persist batch declarations and snapshot digests without guessing legacy file sets."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "25810a2b5deb"
down_revision: str | None = "e41abe5a02f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    duplicate = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT batch_id, filename FROM source_files "
                "GROUP BY batch_id, filename HAVING count(*) > 1 LIMIT 1"
            )
        )
        .first()
    )
    if duplicate is not None:
        raise RuntimeError("Duplicate source filenames need review before adding the constraint")
    op.add_column(
        "batches",
        sa.Column(
            "required_files",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=True,
        ),
    )
    op.add_column("batches", sa.Column("manifest_sha256", sa.String(length=64), nullable=True))
    op.create_unique_constraint(
        op.f("uq_source_files_batch_id_filename"), "source_files", ["batch_id", "filename"]
    )


def downgrade() -> None:
    op.drop_constraint(op.f("uq_source_files_batch_id_filename"), "source_files", type_="unique")
    op.drop_column("batches", "manifest_sha256")
    op.drop_column("batches", "required_files")
