"""a schedule event is timed by the clock, not the transaction

`now()` in PostgreSQL is the transaction timestamp, so every row a transaction
writes shares it. One scheduler tick can record a dropped backlog, a run
created and a schedule paused; with one timestamp between them, a history view
ordering by time shows those three in whatever order the index returns, which
is a story that did not happen.

`clock_timestamp()` advances within the transaction, so the order events were
written in is the order they can be read back in.

Revision ID: e75d64f9bb6b
Revises: b6a624ace67e
Create Date: 2026-09-17 10:07:49.803417+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "e75d64f9bb6b"
down_revision: str | None = "b6a624ace67e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "schedule_events",
        "created_at",
        existing_type=postgresql.TIMESTAMP(timezone=True),
        server_default=sa.text("clock_timestamp()"),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "schedule_events",
        "created_at",
        existing_type=postgresql.TIMESTAMP(timezone=True),
        server_default=sa.text("now()"),
        existing_nullable=False,
    )
