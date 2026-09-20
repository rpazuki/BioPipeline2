"""generations are reclaimed, not counted

`reference_count` is removed rather than repaired. It had one writer --
submission incremented it -- and no decrementer, so every generation ever
pinned looked referenced for ever and the janitor this column exists for
could never have run.

A counter was the wrong shape for the question. Decrementing one means a
process writing "this run is over" separately from the run ending, and a
process that dies in between leaves a generation nothing will ever reclaim
and nothing that would ever say so. The references are the runs; the runs are
what the janitor asks.

`purged_at` is the artifact pattern (ADR 0012): the bytes go, the row stays.
A run points at its generation for ever, and `packages` answers what that run
imported long after the directory holding them is gone.

Revision ID: 22803341fc5e
Revises: cf18b2e8c28b
Create Date: 2026-09-20 11:23:35.836395+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "22803341fc5e"
down_revision: str | None = "cf18b2e8c28b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "environment_generations", sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.drop_index(
        op.f("ix_environment_generations_unreferenced"),
        table_name="environment_generations",
        postgresql_where="(reference_count = 0)",
    )
    op.create_index(
        "ix_environment_generations_reclaimable",
        "environment_generations",
        ["built_at"],
        unique=False,
        postgresql_where=sa.text("purged_at IS NULL"),
    )
    # The CHECK on this column goes with it; PostgreSQL drops a constraint
    # when the only column it names is dropped.
    op.drop_column("environment_generations", "reference_count")


def downgrade() -> None:
    op.add_column(
        "environment_generations",
        sa.Column(
            "reference_count",
            sa.INTEGER(),
            server_default=sa.text("0"),
            autoincrement=False,
            nullable=False,
        ),
    )
    op.create_check_constraint(
        op.f("ck_environment_generations_reference_count_non_negative"),
        "environment_generations",
        "reference_count >= 0",
    )
    op.drop_index(
        "ix_environment_generations_reclaimable",
        table_name="environment_generations",
        postgresql_where=sa.text("purged_at IS NULL"),
    )
    op.create_index(
        op.f("ix_environment_generations_unreferenced"),
        "environment_generations",
        ["created_at"],
        unique=False,
        postgresql_where="(reference_count = 0)",
    )
    op.drop_column("environment_generations", "purged_at")
