"""Artifacts, workspaces, chunked uploads, and output delivery."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, Index, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.enums import (
    ArtifactKind,
    DeliveryMode,
    DeliveryStatus,
    RetentionClass,
    StorageBackend,
    UploadStatus,
    Visibility,
    WorkspaceStatus,
)
from app.infrastructure.db.base import (
    Base,
    bytes_column,
    created_at,
    enum_check,
    jsonb,
    required_timestamp,
    status_column,
    timestamp,
    updated_at,
    uuid_fk,
    uuid_pk,
)


class Artifact(Base):
    __tablename__ = "artifacts"
    __table_args__ = (
        enum_check("kind", ArtifactKind),
        enum_check("storage_backend", StorageBackend),
        enum_check("visibility", Visibility),
        enum_check("retention_class", RetentionClass),
        # Two live rows over the same bytes let the janitor delete data another
        # row still claims (G31). Scoped to live rows so a purged key can be
        # reused.
        Index(
            "uq_artifacts_storage_backend_storage_key",
            "storage_backend",
            "storage_key",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_artifacts_run_id_kind_created_at", "run_id", "kind", "created_at"),
        # The janitor's sweep (G38).
        Index(
            "ix_artifacts_expires_at",
            "expires_at",
            postgresql_where=text("deleted_at IS NULL AND expires_at IS NOT NULL"),
        ),
        CheckConstraint("size_bytes >= 0", name="size_non_negative"),
        CheckConstraint(
            "checksum_sha256 IS NULL OR checksum_sha256 ~ '^[0-9a-f]{64}$'",
            name="checksum_format",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = uuid_fk("projects.id")
    run_id: Mapped[uuid.UUID | None] = uuid_fk("runs.id", nullable=True)
    task_id: Mapped[uuid.UUID | None] = uuid_fk("run_tasks.id", nullable=True)
    # A retry produces a second set of outputs; without this, which attempt
    # produced which bytes is unanswerable (G31).
    task_attempt_id: Mapped[uuid.UUID | None] = uuid_fk("run_task_attempts.id", nullable=True)
    owner_id: Mapped[uuid.UUID | None] = uuid_fk("users.id", nullable=True)
    kind: Mapped[str] = status_column(ArtifactKind)
    storage_backend: Mapped[str] = status_column(StorageBackend, StorageBackend.POSIX)
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(256))
    size_bytes: Mapped[int] = bytes_column(default=0)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64))
    visibility: Mapped[str] = status_column(Visibility, Visibility.PRIVATE)
    # Policy input for the janitor beyond a bare timestamp (G31).
    retention_class: Mapped[str] = status_column(RetentionClass, RetentionClass.STANDARD)
    created_at: Mapped[datetime] = created_at()
    expires_at: Mapped[datetime | None] = timestamp()
    deleted_at: Mapped[datetime | None] = timestamp()
    # Set once the bytes are actually gone, which is what makes deletion
    # verifiable rather than merely recorded (G36).
    purged_at: Mapped[datetime | None] = timestamp()


class Workspace(Base):
    """Execution scratch space. Never the source of truth."""

    __tablename__ = "workspaces"
    __table_args__ = (
        # One workspace per run: the direction doc 04 left circular (G30).
        # runs.workspace_id was dropped; this is the single owning reference.
        UniqueConstraint("run_id", name="uq_workspaces_run_id"),
        enum_check("status", WorkspaceStatus),
        CheckConstraint("quota_bytes > 0", name="quota_positive"),
        CheckConstraint("used_bytes >= 0", name="used_non_negative"),
        Index(
            "ix_workspaces_expires_at",
            "expires_at",
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = uuid_fk("runs.id", ondelete="CASCADE")
    root_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    status: Mapped[str] = status_column(WorkspaceStatus, WorkspaceStatus.ACTIVE)
    quota_bytes: Mapped[int] = bytes_column()
    used_bytes: Mapped[int] = bytes_column(default=0)
    created_at: Mapped[datetime] = created_at()
    expires_at: Mapped[datetime | None] = timestamp()
    deleted_at: Mapped[datetime | None] = timestamp()


class Upload(Base):
    """A chunked, resumable upload in progress (G14).

    A single artifact row cannot represent a partial upload, which is why the
    plan's single-POST upload could not express what the current system
    already does.
    """

    __tablename__ = "uploads"
    __table_args__ = (
        enum_check("status", UploadStatus),
        CheckConstraint("received_bytes >= 0", name="received_non_negative"),
        CheckConstraint(
            "declared_size_bytes IS NULL OR received_bytes <= declared_size_bytes",
            name="not_over_declared_size",
        ),
        CheckConstraint(
            "status <> 'completed' OR artifact_id IS NOT NULL",
            name="completed_has_artifact",
        ),
        # Abandoned-upload cleanup (G38).
        Index(
            "ix_uploads_status_expires_at",
            "status",
            "expires_at",
            postgresql_where=text("status = 'open'"),
        ),
        Index("ix_uploads_owner_id_created_at", "owner_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = uuid_fk("projects.id")
    owner_id: Mapped[uuid.UUID] = uuid_fk("users.id")
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    declared_size_bytes: Mapped[int | None] = bytes_column(nullable=True)
    received_bytes: Mapped[int] = bytes_column(default=0)
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = status_column(UploadStatus, UploadStatus.OPEN)
    artifact_id: Mapped[uuid.UUID | None] = uuid_fk("artifacts.id", nullable=True)
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()
    completed_at: Mapped[datetime | None] = timestamp()
    expires_at: Mapped[datetime] = required_timestamp()


class RunDelivery(Base):
    """One attempt to place a run output at a destination (G16).

    Delivery can fail after a run succeeds, so it needs its own status and its
    own retry rather than a boolean on the run.
    """

    __tablename__ = "run_deliveries"
    __table_args__ = (
        UniqueConstraint(
            "run_id", "field_key", "mode", name="uq_run_deliveries_run_id_field_key_mode"
        ),
        enum_check("mode", DeliveryMode),
        enum_check("status", DeliveryStatus),
        CheckConstraint("attempts >= 0", name="attempts_non_negative"),
        CheckConstraint(
            "mode <> 'shared' OR target_root_id IS NOT NULL",
            name="shared_has_target_root",
        ),
        Index("ix_run_deliveries_status_run_id", "status", "run_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = uuid_fk("runs.id", ondelete="CASCADE")
    field_key: Mapped[str] = mapped_column(String(128), nullable=False)
    mode: Mapped[str] = status_column(DeliveryMode)
    artifact_id: Mapped[uuid.UUID | None] = uuid_fk("artifacts.id", nullable=True)
    # Allowlisted shared-storage root id, never a raw caller-supplied path.
    target_root_id: Mapped[str | None] = mapped_column(String(128))
    target_path: Mapped[str | None] = mapped_column(String(1024))
    status: Mapped[str] = status_column(DeliveryStatus, DeliveryStatus.PENDING)
    attempts: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))
    message: Mapped[str | None] = mapped_column(Text)
    next_attempt_at: Mapped[datetime | None] = timestamp()
    delivered_at: Mapped[datetime | None] = timestamp()
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class SharedStorageRoot(Base):
    """An allowlisted institutional path the platform may read or write.

    Deployment state rather than user data, but it is referenced by delivery
    rows and by input source policies, so it lives in the database with an id
    that those rows can point at.

    ADR 0013 decided Option C: the platform reads and writes as a service
    account, and a root may be exposed only if **every user who can reach it
    already has equivalent access**. That relocates the boundary rather than
    relaxing it -- separation between labs is preserved, because a root is
    exposed only within the project whose members already share it.

    The attestation is what makes that enforced rather than assumed. A
    service-account root without one is not exposed, by constraint.
    """

    __tablename__ = "shared_storage_roots"
    __table_args__ = (
        CheckConstraint(
            "identity_mode IN ('service_account', 'requesting_user')",
            name="identity_mode_valid",
        ),
        CheckConstraint("readable OR writable", name="some_access"),
        # An unattested service-account root is a privilege-escalation path,
        # so the database refuses to hold one rather than trusting that
        # somebody checked.
        CheckConstraint(
            "identity_mode <> 'service_account' "
            "OR (attested_by IS NOT NULL AND attested_at IS NOT NULL)",
            name="service_account_root_is_attested",
        ),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[uuid.UUID] = uuid_fk("projects.id")
    label: Mapped[str] = mapped_column(String(256), nullable=False)
    root_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    readable: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    writable: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    identity_mode: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'service_account'")
    )
    # Who confirmed that every user reaching this root already has equivalent
    # access to it, and when. A human judgement the platform cannot verify, so
    # it is recorded with an actor and a timestamp to make it accountable, and
    # should be re-checked whenever the root's permissions change.
    attested_by: Mapped[uuid.UUID | None] = uuid_fk("users.id", nullable=True)
    attested_at: Mapped[datetime | None] = timestamp()
    attestation_note: Mapped[str | None] = mapped_column(String(512))
    metadata_: Mapped[dict[str, Any]] = jsonb()
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()
