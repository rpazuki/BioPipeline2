"""Persist bounded background ZIP requests and their progress."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "f40a7161b2ec"
down_revision = "7a29b1c504df"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "artifact_bundles",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "requested_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("request_key", sa.String(64), nullable=False),
        sa.Column("source_ids", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'pending'")),
        sa.Column(
            "artifact_id", UUID(as_uuid=True), sa.ForeignKey("artifacts.id", ondelete="RESTRICT")
        ),
        sa.Column("total_bytes", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("completed_bytes", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("message", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'working', 'ready', 'failed')", name="status_valid"
        ),
        sa.UniqueConstraint("run_id", "request_key", name="uq_artifact_bundles_run_id_request_key"),
        sa.CheckConstraint(
            "status <> 'ready' OR artifact_id IS NOT NULL", name="ready_has_artifact"
        ),
        sa.CheckConstraint(
            "total_bytes >= 0 AND completed_bytes >= 0", name="progress_nonnegative"
        ),
    )
    op.create_index("ix_artifact_bundles_run_id", "artifact_bundles", ["run_id"])


def downgrade() -> None:
    op.drop_table("artifact_bundles")
