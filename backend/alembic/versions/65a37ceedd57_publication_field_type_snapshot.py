"""publication field type snapshot

A published field freezes its type here. The definition lives in a pipeline
document, documents are superseded, and an entry published in March must go on
asking for exactly what it asked for in March -- which is also how a saved
value keeps its meaning. Nullable, because a field for a plain string has no
type to freeze.

Revision ID: 65a37ceedd57
Revises: a32a7287592f
Create Date: 2026-09-19 20:24:42.695238+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "65a37ceedd57"
down_revision: str | None = "a32a7287592f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "publication_fields",
        sa.Column(
            "type_schema", postgresql.JSONB(none_as_null=True, astext_type=sa.Text()), nullable=True
        ),
    )


def downgrade() -> None:
    op.drop_column("publication_fields", "type_schema")
