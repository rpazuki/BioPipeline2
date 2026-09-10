"""Runtime environments, audit, access logging, outbox, and import mapping."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, Index, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.enums import RuntimeEnvironmentStatus
from app.infrastructure.db.base import (
    Base,
    created_at,
    enum_check,
    jsonb,
    status_column,
    timestamp,
    updated_at,
    uuid_fk,
    uuid_pk,
)


class RuntimeEnvironment(Base):
    """An immutable task image.

    This is what replaces UI-driven package installs (G06). Because the
    replacement removes a capability admins use today, the table carries what
    the replacement workflow needs: a pinned digest, a package manifest for
    introspection (G07), and promotion state.
    """

    __tablename__ = "runtime_environments"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "name", "version", name="uq_runtime_environments_project_id_name_version"
        ),
        enum_check("status", RuntimeEnvironmentStatus),
        # A pinned digest, not a floating tag: provenance depends on knowing
        # exactly which bytes ran.
        CheckConstraint(
            "image_digest IS NULL OR image_digest ~ '^sha256:[0-9a-f]{64}$'",
            name="digest_format",
        ),
        CheckConstraint(
            "status <> 'available' OR image_digest IS NOT NULL",
            name="available_is_pinned",
        ),
        Index(
            "uq_runtime_environments_default",
            "project_id",
            unique=True,
            postgresql_where=text("is_default"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = uuid_fk("projects.id")
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[int] = mapped_column(nullable=False, server_default=text("1"))
    image_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    image_digest: Mapped[str | None] = mapped_column(String(80))
    python_version: Mapped[str | None] = mapped_column(String(32))
    # Supports the function/signature browser the current system has (G07).
    package_manifest: Mapped[dict[str, Any]] = jsonb()
    contract_versions: Mapped[dict[str, Any]] = jsonb(default="'[]'::jsonb")
    status: Mapped[str] = status_column(RuntimeEnvironmentStatus, RuntimeEnvironmentStatus.BUILDING)
    is_default: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    health_checked_at: Mapped[datetime | None] = timestamp()
    health_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class AuditEvent(Base):
    """Mutations only. Reads go to ``artifact_access_events``."""

    __tablename__ = "audit_events"
    __table_args__ = (
        Index(
            "ix_audit_events_target_type_target_id_created_at",
            "target_type",
            "target_id",
            text("created_at DESC"),
        ),
        Index("ix_audit_events_actor_id_created_at", "actor_id", text("created_at DESC")),
        Index("ix_audit_events_created_at", text("created_at DESC")),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID | None] = uuid_fk("projects.id", nullable=True)
    actor_id: Mapped[uuid.UUID | None] = uuid_fk("users.id", nullable=True)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    ip_address: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(String(512))
    request_id: Mapped[str | None] = mapped_column(String(64))
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = created_at()


class ArtifactAccessEvent(Base):
    """Read auditing (G34).

    Kept out of ``audit_events`` because downloads are far more frequent than
    admin actions and would otherwise dominate that table. Mandatory once the
    data classification in ADR 0001 says the platform holds identifiable data.
    """

    __tablename__ = "artifact_access_events"
    __table_args__ = (
        Index(
            "ix_artifact_access_events_artifact_id_created_at",
            "artifact_id",
            text("created_at DESC"),
        ),
        Index("ix_artifact_access_events_actor_id_created_at", "actor_id", text("created_at DESC")),
        CheckConstraint(
            "access_type IN ('download', 'range_download', 'metadata', 'denied')",
            name="access_type_valid",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    artifact_id: Mapped[uuid.UUID] = uuid_fk("artifacts.id", ondelete="CASCADE")
    actor_id: Mapped[uuid.UUID | None] = uuid_fk("users.id", nullable=True)
    access_type: Mapped[str] = mapped_column(String(32), nullable=False)
    bytes_served: Mapped[int | None] = mapped_column(nullable=True)
    ip_address: Mapped[str | None] = mapped_column(INET)
    request_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = created_at()


class OutboxEvent(Base):
    """Transactional outbox.

    Doc 04 defined this table with no process to drain it (G28). The relay is
    named in ``docs/architecture/overview.md`` and runs inside the janitor; if
    that decision is reversed, drop this table rather than letting it grow
    unread.
    """

    __tablename__ = "outbox_events"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'processing', 'processed', 'failed')",
            name="status_valid",
        ),
        Index(
            "ix_outbox_events_status_created_at",
            "status",
            "created_at",
            postgresql_where=text("status IN ('pending', 'failed')"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    payload: Mapped[dict[str, Any]] = jsonb()
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'pending'")
    )
    attempts: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()
    processed_at: Mapped[datetime | None] = timestamp()


class LegacyImportMap(Base):
    """Maps a legacy identifier to the entity created from it (G40).

    Without this, no importer can be re-run: a second run duplicates
    everything. The source checksum lets an importer detect that the legacy
    record changed since it was imported.
    """

    __tablename__ = "legacy_import_map"
    __table_args__ = (
        UniqueConstraint(
            "source_system",
            "source_kind",
            "source_id",
            name="uq_legacy_import_map_source_system_source_kind_source_id",
        ),
        Index("ix_legacy_import_map_target_type_target_id", "target_type", "target_id"),
        CheckConstraint(
            "outcome IN ('imported', 'imported_with_warnings', "
            "'needs_manual_review', 'failed', 'skipped')",
            name="outcome_valid",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    source_system: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=text("'biopipeline1'")
    )
    source_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[str] = mapped_column(String(512), nullable=False)
    source_checksum: Mapped[str | None] = mapped_column(String(64))
    target_type: Mapped[str | None] = mapped_column(String(64))
    target_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    warnings: Mapped[dict[str, Any]] = jsonb(default="'[]'::jsonb")
    message: Mapped[str | None] = mapped_column(Text)
    imported_at: Mapped[datetime] = created_at()
    import_run_id: Mapped[str] = mapped_column(String(64), nullable=False)
