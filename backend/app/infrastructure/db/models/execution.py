"""Runs, tasks, attempts, and the worker registry.

This module carries most of the corrections from the review, because this is
where work gets lost:

* Tasks are held by a **lease**, not a claim flag (G24). A worker renews it;
  the reaper reclaims anything whose lease has expired.
* Cancellation is **data**, not just a status (G27), so a worker can observe it.
* Run submission is **idempotent** (G26).
* Workers are **registered and heartbeating** (G24), so "which worker had this
  and is it alive" is answerable.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.enums import (
    AttemptStatus,
    RunStatus,
    RunTrigger,
    TaskStatus,
    WorkerStatus,
)
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


class Worker(Base):
    """Live worker registry (G24).

    Document 06 promised a heartbeat table and document 04 never defined one,
    which left "a worker died" undetectable.
    """

    __tablename__ = "workers"
    __table_args__ = (
        enum_check("status", WorkerStatus),
        Index("ix_workers_status_last_heartbeat_at", "status", "last_heartbeat_at"),
    )

    # Stable identity across a restart: host + pid + boot id.
    id: Mapped[str] = mapped_column(String(256), primary_key=True)
    hostname: Mapped[str] = mapped_column(String(256), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    runtime_environment_id: Mapped[uuid.UUID | None] = uuid_fk(
        "runtime_environments.id", nullable=True
    )
    capacity: Mapped[int] = mapped_column(nullable=False, server_default=text("1"))
    status: Mapped[str] = status_column(WorkerStatus, WorkerStatus.STARTING)
    started_at: Mapped[datetime] = created_at()
    last_heartbeat_at: Mapped[datetime] = created_at()


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (
        enum_check("status", RunStatus),
        enum_check("requested_from", RunTrigger),
        # A repeated submit returns the existing run instead of creating a
        # second one on shared compute (G26). Partial: only non-null keys.
        Index(
            "uq_runs_requested_by_idempotency_key",
            "requested_by",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        Index("ix_runs_requested_by_created_at", "requested_by", text("created_at DESC")),
        Index("ix_runs_status_updated_at", "status", "updated_at"),
        Index("ix_runs_project_id_created_at", "project_id", text("created_at DESC")),
        # The reaper's work queue: cancels that have not converged yet.
        Index(
            "ix_runs_cancel_requested_at",
            "cancel_requested_at",
            postgresql_where=text("status = 'cancel_requested'"),
        ),
        CheckConstraint(
            "(cancel_requested_at IS NULL) = (cancel_requested_by IS NULL)",
            name="cancel_fields_together",
        ),
        CheckConstraint(
            "finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at",
            name="finished_after_started",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = uuid_fk("projects.id")
    publication_revision_id: Mapped[uuid.UUID | None] = uuid_fk(
        "publication_revisions.id", nullable=True, index=True
    )
    pipeline_revision_id: Mapped[uuid.UUID] = uuid_fk("pipeline_revisions.id", index=True)
    requested_by: Mapped[uuid.UUID] = uuid_fk("users.id")
    requested_from: Mapped[str] = status_column(RunTrigger, RunTrigger.MANUAL)
    # Bound at submission. Every task of this run executes against this exact
    # snapshot, so a package installed mid-run cannot change behaviour under
    # work already in flight, and the run records what it actually used.
    environment_snapshot_id: Mapped[uuid.UUID | None] = uuid_fk(
        "environment_snapshots.id", nullable=True
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = status_column(RunStatus, RunStatus.QUEUED)
    status_reason: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))
    input_values: Mapped[dict[str, Any]] = jsonb()
    compiled_run_spec: Mapped[dict[str, Any]] = jsonb()
    # Cancellation as data, so a worker can see it without an event bus (G27).
    cancel_requested_at: Mapped[datetime | None] = timestamp()
    cancel_requested_by: Mapped[uuid.UUID | None] = uuid_fk("users.id", nullable=True)
    created_at: Mapped[datetime] = created_at()
    queued_at: Mapped[datetime | None] = timestamp()
    started_at: Mapped[datetime | None] = timestamp()
    finished_at: Mapped[datetime | None] = timestamp()
    updated_at: Mapped[datetime] = updated_at()
    # Soft delete. ADR 0012 open; this build keeps rows and lets a purge job
    # remove bytes, so an audit trail survives a user deletion (G36).
    deleted_at: Mapped[datetime | None] = timestamp()


class RunFieldValue(Base):
    """One submitted value, attributed to its source.

    Separate from ``runs.input_values`` because "which values did the
    researcher supply versus which were defaulted by the admin" is a question
    document 01 says the current system cannot answer.
    """

    __tablename__ = "run_field_values"
    __table_args__ = (
        UniqueConstraint("run_id", "field_key", name="uq_run_field_values_run_id_field_key"),
        CheckConstraint(
            "value_source IN ('researcher', 'default', 'fixed', 'schedule', 'import')",
            name="value_source_valid",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = uuid_fk("runs.id", ondelete="CASCADE", index=True)
    field_key: Mapped[str] = mapped_column(String(128), nullable=False)
    value: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)
    value_source: Mapped[str] = mapped_column(String(32), nullable=False)
    artifact_id: Mapped[uuid.UUID | None] = uuid_fk("artifacts.id", nullable=True)
    created_at: Mapped[datetime] = created_at()


class RunTask(Base):
    __tablename__ = "run_tasks"
    __table_args__ = (
        UniqueConstraint("run_id", "task_key", name="uq_run_tasks_run_id_task_key"),
        enum_check("status", TaskStatus),
        # The worker's claim query.
        Index(
            "ix_run_tasks_claimable",
            text("priority DESC"),
            "created_at",
            postgresql_where=text("status = 'queued'"),
        ),
        # The reaper's reclaim query: anything whose lease has run out (G24).
        Index(
            "ix_run_tasks_lease_expires_at",
            "lease_expires_at",
            postgresql_where=text("status IN ('claimed', 'running')"),
        ),
        # Retry pickup (G38).
        Index(
            "ix_run_tasks_next_retry_at",
            "next_retry_at",
            postgresql_where=text("status = 'retry_wait'"),
        ),
        Index("ix_run_tasks_run_id_status", "run_id", "status"),
        CheckConstraint("retry_count >= 0", name="retry_count_non_negative"),
        CheckConstraint("max_retries >= 0", name="max_retries_non_negative"),
        CheckConstraint("attempt_count >= 0", name="attempt_count_non_negative"),
        # A held task must say who holds it and until when.
        CheckConstraint(
            "status NOT IN ('claimed', 'running') "
            "OR (claimed_by IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="held_task_has_lease",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = uuid_fk("runs.id", ondelete="CASCADE")
    stage_key: Mapped[str] = mapped_column(String(128), nullable=False)
    task_key: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[str] = status_column(TaskStatus, TaskStatus.CREATED)
    status_reason: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))
    dependencies_satisfied: Mapped[bool] = mapped_column(
        nullable=False, server_default=text("false")
    )
    task_spec: Mapped[dict[str, Any]] = jsonb()

    # --- lease, not a claim (G24) ---
    claimed_by: Mapped[str | None] = mapped_column(
        String(256), ForeignKey("workers.id", ondelete="SET NULL")
    )
    claimed_at: Mapped[datetime | None] = timestamp()
    lease_expires_at: Mapped[datetime | None] = timestamp()
    heartbeat_at: Mapped[datetime | None] = timestamp()
    # Set by the reaper when a run-level cancel needs to reach this task.
    cancel_requested_at: Mapped[datetime | None] = timestamp()

    started_at: Mapped[datetime | None] = timestamp()
    finished_at: Mapped[datetime | None] = timestamp()
    retry_count: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))
    max_retries: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))
    next_retry_at: Mapped[datetime | None] = timestamp()
    # Counts every attempt including lost leases, so the poison-task limit can
    # stop a task that never reports back rather than looping forever (G51).
    attempt_count: Mapped[int] = mapped_column(nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class RunTaskDependency(Base):
    __tablename__ = "run_task_dependencies"
    __table_args__ = (
        # A task depending on itself is the degenerate cycle; the compiler
        # rejects real cycles, this catches the trivial one at write time.
        CheckConstraint("task_id <> depends_on_task_id", name="no_self_dependency"),
        Index("ix_run_task_dependencies_depends_on_task_id", "depends_on_task_id"),
    )

    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("run_tasks.id", ondelete="CASCADE"),
        primary_key=True,
    )
    depends_on_task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("run_tasks.id", ondelete="CASCADE"),
        primary_key=True,
    )


class RunTaskAttempt(Base):
    __tablename__ = "run_task_attempts"
    __table_args__ = (
        UniqueConstraint(
            "task_id", "attempt_number", name="uq_run_task_attempts_task_id_attempt_number"
        ),
        enum_check("status", AttemptStatus),
        CheckConstraint("attempt_number > 0", name="attempt_number_positive"),
        # Reconciling orphaned containers on worker start needs this (G53).
        Index(
            "ix_run_task_attempts_container_id",
            "container_id",
            postgresql_where=text("container_id IS NOT NULL AND status = 'running'"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    task_id: Mapped[uuid.UUID] = uuid_fk("run_tasks.id", ondelete="CASCADE", index=True)
    attempt_number: Mapped[int] = mapped_column(nullable=False)
    worker_id: Mapped[str | None] = mapped_column(
        String(256), ForeignKey("workers.id", ondelete="SET NULL")
    )
    container_id: Mapped[str | None] = mapped_column(String(128))
    # The digest actually used, not a floating tag: provenance depends on it.
    image_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    exit_code: Mapped[int | None] = mapped_column(nullable=True)
    status: Mapped[str] = status_column(AttemptStatus, AttemptStatus.RUNNING)
    # artifacts.task_attempt_id points back here, so one side of the cycle
    # must be added after both tables exist.
    log_artifact_id: Mapped[uuid.UUID | None] = uuid_fk(
        "artifacts.id", nullable=True, use_alter=True
    )
    started_at: Mapped[datetime] = created_at()
    finished_at: Mapped[datetime | None] = timestamp()
    # The TaskResult document the container wrote, verbatim.
    result: Mapped[dict[str, Any]] = jsonb()
