"""Schedules and their firing history.

The correctness of "one run per due window" rests on a unique constraint, not
on the scheduler being careful (G25). ``schedule_fires`` is that constraint:
two schedulers, or one scheduler restarting at the wrong moment, cannot create
two runs for the same window because the second insert fails.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, Index, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.enums import CatchupPolicy, FireOutcome, OverlapPolicy, ScheduleStatus
from app.infrastructure.db.base import (
    Base,
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


class Schedule(Base):
    __tablename__ = "schedules"
    __table_args__ = (
        enum_check("status", ScheduleStatus),
        enum_check("catchup_policy", CatchupPolicy),
        enum_check("overlap_policy", OverlapPolicy),
        # The scheduler's claim query.
        Index(
            "ix_schedules_status_next_fire_at",
            "status",
            "next_fire_at",
            postgresql_where=text("status = 'active'"),
        ),
        Index("ix_schedules_owner_id", "owner_id"),
        CheckConstraint("max_concurrent_runs > 0", name="max_concurrent_runs_positive"),
        CheckConstraint("end_at IS NULL OR end_at > created_at", name="end_after_start"),
        # Exactly one recurrence representation. ADR 0015 is open: the current
        # system is interval-based and the plan proposes RRULE, so both are
        # supported and a schedule must pick one.
        CheckConstraint(
            "num_nonnulls(rrule, interval_seconds) = 1",
            name="exactly_one_recurrence",
        ),
        CheckConstraint(
            "interval_seconds IS NULL OR interval_seconds >= 60",
            name="interval_at_least_a_minute",
        ),
        CheckConstraint(
            "dst_policy IN ('skip_nonexistent', 'shift_forward', 'utc_only')",
            name="dst_policy_valid",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = uuid_fk("projects.id")
    publication_revision_id: Mapped[uuid.UUID] = uuid_fk("publication_revisions.id", index=True)
    owner_id: Mapped[uuid.UUID] = uuid_fk("users.id")
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[str] = status_column(ScheduleStatus, ScheduleStatus.ACTIVE)
    rrule: Mapped[str | None] = mapped_column(String(512))
    # The current system's model, kept so imported schedules survive without a
    # lossy conversion (G17).
    interval_seconds: Mapped[int | None] = mapped_column(nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, server_default=text("'UTC'"))
    # An RRULE in a local zone has ambiguous and non-existent times twice a
    # year; the resolution rule is per schedule, not global (G55).
    dst_policy: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'skip_nonexistent'")
    )
    catchup_policy: Mapped[str] = status_column(CatchupPolicy, CatchupPolicy.SKIP_MISSED)
    overlap_policy: Mapped[str] = status_column(OverlapPolicy, OverlapPolicy.SKIP)
    max_concurrent_runs: Mapped[int] = mapped_column(nullable=False, server_default=text("1"))
    input_values: Mapped[dict[str, Any]] = jsonb()
    next_fire_at: Mapped[datetime | None] = timestamp()
    last_fire_at: Mapped[datetime | None] = timestamp()
    last_run_id: Mapped[uuid.UUID | None] = uuid_fk("runs.id", nullable=True)
    end_at: Mapped[datetime | None] = timestamp()
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class ScheduleFire(Base):
    """One due window, fired at most once.

    ``uq_schedule_fires_schedule_id_fire_at`` is the guarantee behind document
    09's "once and only once" acceptance criterion (G25). Note that ``fire_at``
    is the *scheduled* window, not the wall-clock time the scheduler woke up.
    """

    __tablename__ = "schedule_fires"
    __table_args__ = (
        UniqueConstraint("schedule_id", "fire_at", name="uq_schedule_fires_schedule_id_fire_at"),
        enum_check("outcome", FireOutcome),
        Index("ix_schedule_fires_schedule_id_fire_at", "schedule_id", text("fire_at DESC")),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    schedule_id: Mapped[uuid.UUID] = uuid_fk("schedules.id", ondelete="CASCADE")
    fire_at: Mapped[datetime] = required_timestamp()
    run_id: Mapped[uuid.UUID | None] = uuid_fk("runs.id", nullable=True)
    outcome: Mapped[str] = status_column(FireOutcome)
    message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()


class ScheduleEvent(Base):
    """Human-readable history, separate from the correctness constraint."""

    __tablename__ = "schedule_events"
    __table_args__ = (
        Index("ix_schedule_events_schedule_id_created_at", "schedule_id", text("created_at DESC")),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    schedule_id: Mapped[uuid.UUID] = uuid_fk("schedules.id", ondelete="CASCADE")
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    run_id: Mapped[uuid.UUID | None] = uuid_fk("runs.id", nullable=True)
    actor_id: Mapped[uuid.UUID | None] = uuid_fk("users.id", nullable=True)
    message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()
