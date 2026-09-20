"""admin created accounts change their password

An account an administrator creates has a password the administrator knows.
This is what makes that a one-time fact rather than a standing one: until the
person sets their own, the only request their session may make is the one that
changes it.

Revision ID: cf18b2e8c28b
Revises: 0c1730c5fb3a
Create Date: 2026-09-20 08:44:21.124848+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "cf18b2e8c28b"
down_revision: str | None = "0c1730c5fb3a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "must_change_password", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "must_change_password")
