"""a storage root can be withdrawn

A root that grants neither read nor write does nothing, which is exactly what
withdrawing one means — so `some_access` has to allow that state, and
`revoked_at` is what says it is deliberate rather than leaving a reader to
infer it from two false flags.

Withdrawal is not deletion: a delivery that went to a root still names it, and
who attested it is part of the record whether or not it is still mounted.

Autogenerate produced only the column. Alembic does not compare CHECK
constraints, so the constraint below is written by hand; without it the first
withdrawal would fail at the database.

Revision ID: a32a7287592f
Revises: e75d64f9bb6b
Create Date: 2026-09-17 14:34:05.922338+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a32a7287592f"
down_revision: str | None = "e75d64f9bb6b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The short suffix, not the full name: the metadata naming convention
# prepends `ck_<table>_`, and passing the whole thing produces
# `ck_shared_storage_roots_ck_shared_storage_roots_some_access`.
CONSTRAINT = "some_access"


def upgrade() -> None:
    op.add_column(
        "shared_storage_roots",
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.drop_constraint(CONSTRAINT, "shared_storage_roots", type_="check")
    op.create_check_constraint(
        "some_access",
        "shared_storage_roots",
        "readable OR writable OR revoked_at IS NOT NULL",
    )


def downgrade() -> None:
    # A withdrawn root cannot be represented without the column, so it goes
    # back to being readable — losing the fact rather than the row.
    op.execute("UPDATE shared_storage_roots SET readable = true WHERE revoked_at IS NOT NULL")
    op.drop_constraint(CONSTRAINT, "shared_storage_roots", type_="check")
    op.create_check_constraint("some_access", "shared_storage_roots", "readable OR writable")
    op.drop_column("shared_storage_roots", "revoked_at")
