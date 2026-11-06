"""Add durable resource deletion requests and run lifecycle auditing."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "c918fe2735ab"
down_revision = "8a32c1d0f482"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "resource_deletions",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("target_type", sa.String(64), nullable=False),
        sa.Column("target_key", sa.String(512), nullable=False),
        sa.Column(
            "requested_by",
            sa.UUID(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column(
            "details", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("error", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "target_type", "target_key", name="uq_resource_deletions_target_type_target_key"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'failed', 'complete')",
            name=op.f("ck_resource_deletions_status_valid"),
        ),
    )
    op.execute("""
        CREATE FUNCTION bp_audit_run_lifecycle() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'INSERT' OR NEW.status IS DISTINCT FROM OLD.status THEN
                INSERT INTO audit_events (project_id, actor_id, action, target_type, target_id, metadata)
                VALUES (NEW.project_id,
                    CASE WHEN TG_OP = 'INSERT' THEN NEW.requested_by
                         WHEN NEW.status = 'cancel_requested' THEN NEW.cancel_requested_by ELSE NULL END,
                    CASE WHEN TG_OP = 'INSERT' THEN 'run.submitted' ELSE 'run.status_changed' END,
                    'run', NEW.id,
                    jsonb_build_object('status', NEW.status, 'requested_by', NEW.requested_by,
                        'pipeline_revision_id', NEW.pipeline_revision_id,
                        'publication_revision_id', NEW.publication_revision_id,
                        'requested_from', NEW.requested_from, 'reason', NEW.status_reason,
                        'started_at', NEW.started_at, 'finished_at', NEW.finished_at));
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER trg_runs_audit AFTER INSERT OR UPDATE OF status ON runs
        FOR EACH ROW EXECUTE FUNCTION bp_audit_run_lifecycle();
        INSERT INTO audit_events (project_id, actor_id, action, target_type, target_id, metadata, created_at)
        SELECT project_id, requested_by, 'run.imported_history', 'run', id,
            jsonb_build_object('status', status, 'submitted_at', created_at,
                'finished_at', finished_at, 'backfilled', true), now() FROM runs;
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_runs_audit ON runs")
    op.execute("DROP FUNCTION bp_audit_run_lifecycle()")
    op.drop_table("resource_deletions")
