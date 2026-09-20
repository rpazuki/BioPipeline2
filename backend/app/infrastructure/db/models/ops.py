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
    # The generation tasks currently run against. Moved atomically when an
    # install succeeds, which is the whole of how an install fails to disturb
    # work already running: nothing mutates a generation, so a run that pinned
    # the previous one goes on seeing exactly what it pinned (ADR 0028).
    current_generation_id: Mapped[uuid.UUID | None] = uuid_fk(
        "environment_generations.id", nullable=True, use_alter=True
    )
    is_default: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    # True while an install or uninstall is running, so snapshots are not
    # taken from a half-written environment.
    locked_at: Mapped[datetime | None] = timestamp()
    locked_reason: Mapped[str | None] = mapped_column(String(256))
    health_checked_at: Mapped[datetime | None] = timestamp()
    health_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class EnvironmentGeneration(Base):
    """One immutable build of an environment.

    Not a per-run clone, which is what the plan proposed and ADR 0028
    rejected: hardlinks are not an isolation boundary when an installer
    rewrites a file in place, copy-on-write needs filesystem support nobody
    guaranteed, and a virtualenv embeds absolute paths that do not survive
    being moved.

    A generation is built **out of place and then never touched again**. An
    install copies the current generation to a new directory, installs into
    the copy, inventories it, and only then moves the environment's
    `current_generation_id`. Isolation comes from immutability rather than
    from filesystem tricks, and a run that pinned an earlier generation keeps
    seeing exactly what it pinned for as long as it runs -- which matters
    when a task can run for days.

    Every generation is mounted into its container at the **same** path. That
    is what makes copying one safe despite a virtualenv's absolute paths:
    the paths inside it always resolve, because the only place it is ever
    used is where it was built.
    """

    __tablename__ = "environment_generations"
    __table_args__ = (
        UniqueConstraint(
            "environment_id", "digest", name="uq_environment_generations_environment_id_digest"
        ),
        CheckConstraint("digest ~ '^sha256:[0-9a-f]{64}$'", name="digest_format"),
        CheckConstraint(
            "status IN ('building', 'ready', 'failed')", name="generation_status_valid"
        ),
        Index(
            "ix_environment_generations_reclaimable",
            "built_at",
            postgresql_where=text("purged_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    environment_id: Mapped[uuid.UUID] = uuid_fk("runtime_environments.id", index=True)
    # Content hash of the resolved package set. Two installs that arrive at
    # the same set are the same generation, which is what stops an
    # install-uninstall-reinstall cycle growing the disk for ever.
    digest: Mapped[str] = mapped_column(String(80), nullable=False)
    generation_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    packages: Mapped[dict[str, Any]] = jsonb(default="'[]'::jsonb")
    python_version: Mapped[str | None] = mapped_column(String(32))
    # True when any distribution is installed from a working tree. Such a
    # generation cannot be reproduced -- it is a link to mutable source, not a
    # set of versions -- so every run pinning it is marked accordingly rather
    # than claiming a provenance it does not have (ADR 0028, G94).
    editable: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'building'")
    )
    message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()
    built_at: Mapped[datetime | None] = timestamp()
    # When the janitor removed the directory. The row stays: a run points at
    # it for ever, and `packages` is the answer to "what did that run import",
    # which survives the bytes it describes. Exactly `artifacts.purged_at`,
    # for exactly the same reason -- deletion that is recorded is not the same
    # as deletion that is verifiable (ADR 0012).
    #
    # There is deliberately no reference counter. A counter has to be
    # decremented by somebody, and the somebody is a process that can die
    # between finishing a run and writing the decrement; the result is a
    # generation nothing will ever reclaim, and nothing that would ever say
    # so. The references are the runs, so the runs are what the janitor asks.
    purged_at: Mapped[datetime | None] = timestamp()


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
    # Which generation the operation produced, when it produced one.
    generation_id: Mapped[uuid.UUID | None] = uuid_fk("environment_generations.id", nullable=True)
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
