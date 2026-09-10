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
    """A named Python environment that an admin installs packages into.

    The plan proposed replacing UI-driven package installs with immutable
    pinned images. That is wrong for this system: admins install libraries
    into a shared environment as part of normal work, and a frozen image
    turns every ``pip install`` into an image build.

    So the environment is **mutable**, and reproducibility comes from
    snapshotting instead: a run binds to a snapshot of the environment at
    submission, which is what gives provenance without image builds and what
    stops an install disturbing a task that has been running for two days.
    """

    __tablename__ = "runtime_environments"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_runtime_environments_project_id_name"),
        enum_check("status", RuntimeEnvironmentStatus),
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
    description: Mapped[str | None] = mapped_column(Text)
    # Where the venv lives on the host, mounted into the task container.
    venv_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    python_version: Mapped[str | None] = mapped_column(String(32))
    # The task image is a thin runner; the venv supplies the libraries, so
    # this rarely changes and is not pinned per revision.
    image_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    contract_versions: Mapped[dict[str, Any]] = jsonb(default="'[]'::jsonb")
    status: Mapped[str] = status_column(RuntimeEnvironmentStatus, RuntimeEnvironmentStatus.BUILDING)
    is_default: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    # True while an install or uninstall is running, so snapshots are not
    # taken from a half-written environment.
    locked_at: Mapped[datetime | None] = timestamp()
    locked_reason: Mapped[str | None] = mapped_column(String(256))
    health_checked_at: Mapped[datetime | None] = timestamp()
    health_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class EnvironmentSnapshot(Base):
    """The environment as it stood when a run was submitted.

    A run binds to a snapshot rather than to the live environment. The
    snapshot is a copy-on-write or hardlinked clone of the venv, so an admin
    installing a package cannot change behaviour underneath work already
    running -- which matters because tasks here can run for days.

    ``packages`` is the resolved distribution list, which is what makes a run
    reproducible and answers "what was installed when this ran?" without an
    image registry.
    """

    __tablename__ = "environment_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "environment_id", "digest", name="uq_environment_snapshots_environment_id_digest"
        ),
        CheckConstraint("digest ~ '^sha256:[0-9a-f]{64}$'", name="digest_format"),
        Index(
            "ix_environment_snapshots_unreferenced",
            "created_at",
            postgresql_where=text("reference_count = 0"),
        ),
        CheckConstraint("reference_count >= 0", name="reference_count_non_negative"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    environment_id: Mapped[uuid.UUID] = uuid_fk("runtime_environments.id", index=True)
    # Content hash of the resolved package set: identical package sets share
    # one snapshot rather than cloning the venv for every run.
    digest: Mapped[str] = mapped_column(String(80), nullable=False)
    snapshot_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    packages: Mapped[dict[str, Any]] = jsonb(default="'[]'::jsonb")
    # Reclaimed by the janitor once nothing references it.
    reference_count: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = created_at()


class PackageOperation(Base):
    """Audit of an install or uninstall.

    The current system keeps this in ``installs.sqlite``. It is provenance,
    not bookkeeping: it answers why a pipeline that worked last month fails
    today.
    """

    __tablename__ = "package_operations"
    __table_args__ = (
        CheckConstraint("operation IN ('install', 'uninstall', 'upgrade')", name="operation_valid"),
        CheckConstraint("status IN ('running', 'succeeded', 'failed')", name="status_valid"),
        Index(
            "ix_package_operations_environment_id_created_at",
            "environment_id",
            text("created_at DESC"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    environment_id: Mapped[uuid.UUID] = uuid_fk("runtime_environments.id", ondelete="CASCADE")
    actor_id: Mapped[uuid.UUID | None] = uuid_fk("users.id", nullable=True)
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    specifier: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'running'")
    )
    resulting_digest: Mapped[str | None] = mapped_column(String(80))
    log: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()
    finished_at: Mapped[datetime | None] = timestamp()


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
