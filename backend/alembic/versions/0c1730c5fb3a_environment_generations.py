"""environment generations

`environment_snapshots` is replaced rather than renamed. It held the design
ADR 0028 rejected -- a per-run clone of a virtualenv -- and nothing has ever
written a row to it, so there is nothing to carry across. A generation is
built once and never mutated, and a run pins one; that is what makes an
install unable to disturb work already running.

Revision ID: 0c1730c5fb3a
Revises: 65a37ceedd57
Create Date: 2026-09-19 20:52:53.161473+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0c1730c5fb3a"
down_revision: str | None = "65a37ceedd57"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "environment_generations",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("environment_id", sa.UUID(), nullable=False),
        sa.Column("digest", sa.String(length=80), nullable=False),
        sa.Column("generation_path", sa.String(length=1024), nullable=False),
        sa.Column(
            "packages",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("python_version", sa.String(length=32), nullable=True),
        sa.Column("editable", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "status", sa.String(length=32), server_default=sa.text("'building'"), nullable=False
        ),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("reference_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("built_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "digest ~ '^sha256:[0-9a-f]{64}$'",
            name=op.f("ck_environment_generations_digest_format"),
        ),
        sa.CheckConstraint(
            "status IN ('building', 'ready', 'failed')",
            name=op.f("ck_environment_generations_generation_status_valid"),
        ),
        sa.CheckConstraint(
            "reference_count >= 0",
            name=op.f("ck_environment_generations_reference_count_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["environment_id"],
            ["runtime_environments.id"],
            name=op.f("fk_environment_generations_environment_id_runtime_environments"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_environment_generations")),
        sa.UniqueConstraint(
            "environment_id", "digest", name="uq_environment_generations_environment_id_digest"
        ),
    )
    op.create_index(
        op.f("ix_environment_generations_environment_id"),
        "environment_generations",
        ["environment_id"],
        unique=False,
    )
    op.create_index(
        "ix_environment_generations_unreferenced",
        "environment_generations",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("reference_count = 0"),
    )
    # The `runs` constraint has to go before the table it depends on.
    op.add_column("runs", sa.Column("environment_generation_id", sa.UUID(), nullable=True))
    op.drop_constraint(
        op.f("fk_runs_environment_snapshot_id_environment_snapshots"), "runs", type_="foreignkey"
    )
    op.drop_column("runs", "environment_snapshot_id")
    op.drop_index(
        op.f("ix_environment_snapshots_environment_id"), table_name="environment_snapshots"
    )
    op.drop_index(
        op.f("ix_environment_snapshots_unreferenced"),
        table_name="environment_snapshots",
        postgresql_where="(reference_count = 0)",
    )
    op.drop_table("environment_snapshots")
    op.add_column("package_operations", sa.Column("generation_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_package_operations_generation_id_environment_generations"),
        "package_operations",
        "environment_generations",
        ["generation_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        op.f("fk_runs_environment_generation_id_environment_generations"),
        "runs",
        "environment_generations",
        ["environment_generation_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.add_column(
        "runtime_environments", sa.Column("current_generation_id", sa.UUID(), nullable=True)
    )
    op.create_foreign_key(
        op.f("fk_runtime_environments_current_generation_id_environment_generations"),
        "runtime_environments",
        "environment_generations",
        ["current_generation_id"],
        ["id"],
        ondelete="RESTRICT",
        use_alter=True,
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_runtime_environments_current_generation_id_environment_generations"),
        "runtime_environments",
        type_="foreignkey",
    )
    op.drop_column("runtime_environments", "current_generation_id")
    op.add_column(
        "runs", sa.Column("environment_snapshot_id", sa.UUID(), autoincrement=False, nullable=True)
    )
    op.drop_constraint(
        op.f("fk_runs_environment_generation_id_environment_generations"),
        "runs",
        type_="foreignkey",
    )
    op.create_foreign_key(
        op.f("fk_runs_environment_snapshot_id_environment_snapshots"),
        "runs",
        "environment_snapshots",
        ["environment_snapshot_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_column("runs", "environment_generation_id")
    op.drop_constraint(
        op.f("fk_package_operations_generation_id_environment_generations"),
        "package_operations",
        type_="foreignkey",
    )
    op.drop_column("package_operations", "generation_id")
    op.create_table(
        "environment_snapshots",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column("environment_id", sa.UUID(), autoincrement=False, nullable=False),
        sa.Column("digest", sa.VARCHAR(length=80), autoincrement=False, nullable=False),
        sa.Column("snapshot_path", sa.VARCHAR(length=1024), autoincrement=False, nullable=False),
        sa.Column(
            "packages",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            "reference_count",
            sa.INTEGER(),
            server_default=sa.text("0"),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            autoincrement=False,
            nullable=False,
        ),
        sa.CheckConstraint(
            "digest::text ~ '^sha256:[0-9a-f]{64}$'::text",
            name=op.f("ck_environment_snapshots_digest_format"),
        ),
        sa.CheckConstraint(
            "reference_count >= 0",
            name=op.f("ck_environment_snapshots_reference_count_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["environment_id"],
            ["runtime_environments.id"],
            name=op.f("fk_environment_snapshots_environment_id_runtime_environments"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_environment_snapshots")),
        sa.UniqueConstraint(
            "environment_id",
            "digest",
            name=op.f("uq_environment_snapshots_environment_id_digest"),
            postgresql_include=[],
            postgresql_nulls_not_distinct=False,
        ),
    )
    op.create_index(
        op.f("ix_environment_snapshots_unreferenced"),
        "environment_snapshots",
        ["created_at"],
        unique=False,
        postgresql_where="(reference_count = 0)",
    )
    op.create_index(
        op.f("ix_environment_snapshots_environment_id"),
        "environment_snapshots",
        ["environment_id"],
        unique=False,
    )
    op.drop_index(
        "ix_environment_generations_unreferenced",
        table_name="environment_generations",
        postgresql_where=sa.text("reference_count = 0"),
    )
    op.drop_index(
        op.f("ix_environment_generations_environment_id"), table_name="environment_generations"
    )
    op.drop_table("environment_generations")
