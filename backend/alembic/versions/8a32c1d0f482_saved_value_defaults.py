"""Add one personal default per user, type, and value shape."""

import sqlalchemy as sa

from alembic import op

revision = "8a32c1d0f482"
down_revision = "f40a7161b2ec"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "saved_values",
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_index(
        "uq_saved_values_personal_default",
        "saved_values",
        ["user_id", "type_key", "container"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )


def downgrade() -> None:
    op.drop_index("uq_saved_values_personal_default", table_name="saved_values")
    op.drop_column("saved_values", "is_default")
