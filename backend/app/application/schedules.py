"""Schedules: the same runs, started by a clock instead of a person.

A schedule does not have its own execution path. It fills in a catalog entry's
form from a stored set of values and submits it, so a scheduled run is an
ordinary run in every respect -- same bindings, same materialisation, same
tasks, same everything a researcher sees. The only difference is the trigger
recorded on it.

**Firing exactly once is the property that matters**, and it does not rest on
this module being careful. Every window inserts a ``schedule_fires`` row before
it creates anything, keyed ``(schedule_id, fire_at)``; a second scheduler, or
one scheduler restarting at precisely the wrong moment, loses at the unique
constraint and creates nothing (G25). That is why several schedulers may run at
once with no leader election, exactly as document 06 concluded.

Two guarantees, not one: the run also carries the idempotency key
``schedule:<id>:<window>``, so even a ``schedule_fires`` row deleted by hand
cannot produce a second run for a window.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.application.pipelines import default_project_id
from app.application.publications import (
    SubmissionRefused,
    bind_submission,
    entry_for_revision,
)
from app.application.runs import SubmissionRejected, submit_run
from app.domain.enums import (
    CatchupPolicy,
    FireOutcome,
    OverlapPolicy,
    RunTrigger,
    ScheduleStatus,
)
from app.domain.errors import DomainError, ValidationFailed
from app.domain.materialise import FanOutEnumerator
from app.domain.recurrence import FirePlan, InvalidRecurrence, Recurrence, plan_fires
from app.infrastructure.db.models import (
    Publication,
    PublicationRevision,
    Schedule,
    ScheduleEvent,
    ScheduleFire,
)

# How many consecutive failures before a schedule stops trying. A publication
# that was archived, or a pipeline whose inputs no longer validate, otherwise
# fails on every window forever and tells nobody: the failures scroll past in
# a log while the schedule still calls itself active. Pausing is the loud
# version, and document 06 lists `paused` among the outcomes to record.
FAILURES_BEFORE_PAUSE = 3


@dataclass(slots=True)
class FireReport:
    """What one tick did to one schedule."""

    schedule_id: uuid.UUID
    created: list[uuid.UUID] = field(default_factory=list)
    skipped_catchup: int = 0
    skipped_overlap: int = 0
    deferred: int = 0
    """Windows held back by ``overlap_policy = queue``; they stay due."""
    failed: int = 0
    paused: str | None = None
    exhausted: bool = False
    more_due: bool = False

    @property
    def changed(self) -> bool:
        return bool(
            self.created
            or self.skipped_catchup
            or self.skipped_overlap
            or self.failed
            or self.paused
            or self.exhausted
        )

    def summary(self) -> str:
        parts = []
        if self.created:
            parts.append(f"{len(self.created)} run(s) created")
        if self.skipped_catchup:
            parts.append("a missed backlog dropped")
        if self.skipped_overlap:
            parts.append(f"{self.skipped_overlap} window(s) skipped as overlapping")
        if self.deferred:
            parts.append(f"{self.deferred} window(s) waiting for the previous run")
        if self.failed:
            parts.append(f"{self.failed} window(s) failed")
        if self.paused:
            parts.append(f"paused: {self.paused}")
        if self.exhausted:
            parts.append("no further windows")
        return ", ".join(parts) or "nothing to do"


# --- reading a schedule ----------------------------------------------------


def recurrence_of(schedule: Schedule) -> Recurrence:
    """The recurrence a stored schedule describes.

    An interval schedule keeps its phase in ``next_fire_at``: the grid is
    that window plus whole multiples of the interval, so an admin who asked
    for 02:00 keeps 02:00 and a late scheduler never drifts the grid forward.

    A rule keeps its phase in itself. ``create_schedule`` writes the DTSTART
    into the stored rule for exactly this reason: if the anchor moved with
    ``next_fire_at``, a bare ``FREQ=DAILY`` shifted an hour by a
    ``shift_forward`` spring-forward would stay shifted for ever.
    """
    return Recurrence(
        start=schedule.next_fire_at or schedule.created_at,
        rrule=schedule.rrule,
        interval_seconds=schedule.interval_seconds,
        timezone=schedule.timezone,
        dst_policy=schedule.dst_policy,
        end_at=schedule.end_at,
    )


def due_schedule_ids(session: Session, *, now: datetime, limit: int = 100) -> list[uuid.UUID]:
    """Active schedules whose next window has arrived, oldest first.

    A plain read: the row is locked, and the window claimed, one schedule at a
    time in :func:`fire_due`, so that one slow schedule does not hold a lock
    over every other.
    """
    rows = session.execute(
        text(
            """
            SELECT id FROM schedules
            WHERE status = 'active'
              AND next_fire_at IS NOT NULL
              AND next_fire_at <= :now
            ORDER BY next_fire_at
            LIMIT :limit
            """
        ),
        {"now": now, "limit": limit},
    ).scalars()
    return list(rows)


def _active_run_count(session: Session, schedule_id: uuid.UUID) -> int:
    """Runs this schedule started that have not finished.

    Derived from ``schedule_fires`` rather than a column on the run, so it
    cannot disagree with the firing history.
    """
    return int(
        session.execute(
            text(
                """
                SELECT count(*) FROM runs r
                JOIN schedule_fires f ON f.run_id = r.id
                WHERE f.schedule_id = :s
                  AND r.status NOT IN ('succeeded', 'failed', 'cancelled')
                """
            ),
            {"s": schedule_id},
        ).scalar_one()
    )


def _recent_failures(session: Session, schedule_id: uuid.UUID, *, limit: int) -> int:
    """How many of the most recent windows failed, counting back from the last."""
    outcomes = session.execute(
        text(
            "SELECT outcome FROM schedule_fires WHERE schedule_id = :s "
            "ORDER BY fire_at DESC LIMIT :n"
        ),
        {"s": schedule_id, "n": limit},
    ).scalars()
    consecutive = 0
    for outcome in outcomes:
        if outcome != FireOutcome.FAILED:
            break
        consecutive += 1
    return consecutive


# --- writing history -------------------------------------------------------


def record_event(
    session: Session,
    schedule_id: uuid.UUID,
    *,
    event_type: str,
    message: str | None = None,
    run_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
) -> None:
    session.execute(
        text(
            "INSERT INTO schedule_events (schedule_id, event_type, run_id, actor_id, message) "
            "VALUES (:s, :t, :r, :a, :m)"
        ),
        {"s": schedule_id, "t": event_type, "r": run_id, "a": actor_id, "m": message},
    )


def _claim_window(
    session: Session, schedule_id: uuid.UUID, window: datetime, *, outcome: str, message: str | None
) -> uuid.UUID | None:
    """Stake this window, or find out somebody else already has it.

    The insert happens *before* any work, so a race is settled by the database
    rather than by two schedulers each discovering afterwards that they both
    started a run.
    """
    try:
        with session.begin_nested():
            return session.execute(
                text(
                    "INSERT INTO schedule_fires (schedule_id, fire_at, outcome, message) "
                    "VALUES (:s, :f, :o, :m) RETURNING id"
                ),
                {"s": schedule_id, "f": window, "o": outcome, "m": message},
            ).scalar_one()
    except IntegrityError:
        return None


# --- firing ----------------------------------------------------------------


def fire_due(
    session: Session,
    schedule_id: uuid.UUID,
    *,
    now: datetime | None = None,
    enumerate_fanout: FanOutEnumerator | None = None,
    grace_seconds: int = 60,
    limit: int = 50,
) -> FireReport:
    """Bring one schedule up to date.

    The schedule row is locked for the duration, so a second scheduler working
    the same list moves on to the next one rather than waiting. Correctness
    does not depend on that -- the unique constraint does -- but it keeps two
    schedulers from doing the same work twice and discarding half of it.
    """
    now = now or datetime.now(UTC)
    report = FireReport(schedule_id=schedule_id)

    schedule = session.execute(
        select(Schedule)
        .where(Schedule.id == schedule_id, Schedule.status == ScheduleStatus.ACTIVE)
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()
    if schedule is None:
        return report

    try:
        plan = plan_fires(
            recurrence_of(schedule),
            due_at=schedule.next_fire_at,
            now=now,
            catchup=schedule.catchup_policy,
            grace_seconds=grace_seconds,
            limit=limit,
        )
    except InvalidRecurrence as error:
        # No window can be computed, so there is nothing to advance past and
        # the schedule would be retried on every tick forever.
        _pause(session, schedule, reason=str(error))
        report.paused = str(error)
        return report

    if plan.skipped_through is not None:
        _record_backlog(session, schedule, plan, report)

    for window in plan.fire:
        if not _fire_one(
            session,
            schedule,
            window,
            report,
            enumerate_fanout=enumerate_fanout,
        ):
            # `queue` overlap: the window is still owed, so the grid must not
            # move past it.
            schedule.next_fire_at = window
            session.flush()
            return report

    schedule.next_fire_at = plan.next_fire_at
    if plan.next_fire_at is None:
        report.exhausted = True
        record_event(
            session,
            schedule.id,
            event_type="exhausted",
            message="The recurrence has no further windows.",
        )
    report.more_due = plan.more_due

    if (
        report.failed
        and _recent_failures(session, schedule.id, limit=FAILURES_BEFORE_PAUSE)
        >= FAILURES_BEFORE_PAUSE
    ):
        reason = f"{FAILURES_BEFORE_PAUSE} consecutive windows failed."
        _pause(session, schedule, reason=reason)
        report.paused = reason

    session.flush()
    return report


def _record_backlog(
    session: Session, schedule: Schedule, plan: FirePlan, report: FireReport
) -> None:
    """Consume the windows the catchup policy dropped, in one row.

    Keyed at the most recent of them, so the window cannot later be fired by
    something that disagrees about the policy.
    """
    assert plan.skipped_through is not None
    message = (
        "Missed while nothing was scheduling: windows through "
        f"{plan.skipped_through.isoformat()} were dropped by "
        f"catchup_policy = {schedule.catchup_policy}."
    )
    if _claim_window(
        session,
        schedule.id,
        plan.skipped_through,
        outcome=FireOutcome.SKIPPED_CATCHUP,
        message=message,
    ):
        report.skipped_catchup += 1
        record_event(session, schedule.id, event_type="skipped_catchup", message=message)


def _fire_one(
    session: Session,
    schedule: Schedule,
    window: datetime,
    report: FireReport,
    *,
    enumerate_fanout: FanOutEnumerator | None,
) -> bool:
    """One window. Returns False when the window should stay due."""
    if schedule.overlap_policy != OverlapPolicy.ALLOW:
        active = _active_run_count(session, schedule.id)
        if active >= schedule.max_concurrent_runs:
            if schedule.overlap_policy == OverlapPolicy.QUEUE:
                # Deferred, not dropped: the window keeps its place and fires
                # when the previous run finishes. This is the whole difference
                # between `queue` and `skip`.
                report.deferred += 1
                return False
            message = f"{active} run(s) from this schedule are still going."
            if _claim_window(
                session,
                schedule.id,
                window,
                outcome=FireOutcome.SKIPPED_OVERLAP,
                message=message,
            ):
                report.skipped_overlap += 1
                record_event(session, schedule.id, event_type="skipped_overlap", message=message)
            return True

    fire_id = _claim_window(session, schedule.id, window, outcome=FireOutcome.CREATED, message=None)
    if fire_id is None:
        # Somebody else has this window. Nothing to do and nothing to say.
        return True

    try:
        with session.begin_nested():
            run_id = _submit(session, schedule, window, enumerate_fanout=enumerate_fanout)
    except (ValidationFailed, SubmissionRefused, SubmissionRejected, SQLAlchemyError) as error:
        message = _why(error)
        session.execute(
            text("UPDATE schedule_fires SET outcome = :o, message = :m WHERE id = :i"),
            {"o": FireOutcome.FAILED, "m": message, "i": fire_id},
        )
        record_event(session, schedule.id, event_type="failed", message=message)
        report.failed += 1
        return True

    session.execute(
        text("UPDATE schedule_fires SET run_id = :r WHERE id = :i"),
        {"r": run_id, "i": fire_id},
    )
    schedule.last_fire_at = window
    schedule.last_run_id = run_id
    record_event(session, schedule.id, event_type="fired", run_id=run_id)
    report.created.append(run_id)
    return True


def _why(error: Exception) -> str:
    """Why a window produced nothing, in terms somebody can act on.

    A domain error's headline counts its problems rather than naming them --
    "rejected with 2 error(s)" -- and this message is the only place an owner
    will look to find out why their schedule stopped producing results. So the
    problems themselves are carried through, not the fact that there were some.
    """
    if not isinstance(error, DomainError):
        return f"{type(error).__name__}: {error}"[:2000]

    problems: list[str] = []
    listed = error.details.get("errors")
    for item in listed if isinstance(listed, list) else []:
        if not isinstance(item, dict):
            continue
        where = item.get("location") or item.get("path")
        text_of = str(item.get("message", "")).strip()
        problems.append(f"{where}: {text_of}" if where else text_of)

    if not problems:
        return error.message[:2000]
    shown = problems[:5]
    if len(problems) > len(shown):
        shown.append(f"…and {len(problems) - len(shown)} more.")
    return f"{error.message} {' '.join(shown)}"[:2000]


def _submit(
    session: Session,
    schedule: Schedule,
    window: datetime,
    *,
    enumerate_fanout: FanOutEnumerator | None,
) -> uuid.UUID:
    """Fill in the published form from the schedule's stored values.

    The schedule pins a publication *revision*, not a publication, so
    re-publishing a catalog entry never silently changes what a schedule runs.
    """
    entry = entry_for_revision(session, revision_id=schedule.publication_revision_id)
    if entry is None:
        raise ValidationFailed(
            "The catalog entry behind this schedule is no longer published, so it "
            "cannot be started."
        )
    plan = bind_submission(session, entry=entry, submitted=dict(schedule.input_values or {}))
    submitted = submit_run(
        session,
        pipeline_revision_id=entry.pipeline_revision_id,
        publication_revision_id=entry.revision_id,
        requested_by=schedule.owner_id,
        values=plan.values,
        recorded_values=plan.submitted,
        compiled=plan.pipeline,
        # The second guarantee. `fire_at` is the window, never the wall clock,
        # so a late fire and an on-time one are the same run.
        idempotency_key=f"schedule:{schedule.id}:{window.isoformat()}"[:128],
        trigger=RunTrigger.SCHEDULE,
        enumerate_fanout=enumerate_fanout,
    )
    return submitted.run_id


# --- administration --------------------------------------------------------


def _pause(session: Session, schedule: Schedule, *, reason: str) -> None:
    schedule.status = ScheduleStatus.PAUSED
    record_event(session, schedule.id, event_type="paused", message=reason)
    session.flush()


def _with_dtstart(
    rrule: str | None, *, anchor: datetime, timezone: str, dst_policy: str
) -> str | None:
    """Fix a rule's phase into the rule itself.

    A stored rule has to mean the same thing on every tick for ever. Left to a
    separate anchor column -- or worse, to the schedule's own ``next_fire_at``
    -- a bare ``FREQ=DAILY`` would shift to whatever time the last window
    happened to land on.
    """
    if rrule is None or "DTSTART" in rrule.upper():
        return rrule
    zone = ZoneInfo("UTC") if dst_policy == "utc_only" else ZoneInfo(timezone)
    local = anchor.astimezone(zone).strftime("%Y%m%dT%H%M%S")
    return f"DTSTART:{local}\nRRULE:{rrule}"


def create_schedule(
    session: Session,
    *,
    publication_revision_id: uuid.UUID,
    owner_id: uuid.UUID,
    title: str,
    input_values: dict[str, Any],
    rrule: str | None = None,
    interval_seconds: int | None = None,
    timezone: str = "UTC",
    dst_policy: str = "skip_nonexistent",
    catchup_policy: str = CatchupPolicy.SKIP_MISSED,
    overlap_policy: str = OverlapPolicy.SKIP,
    max_concurrent_runs: int = 1,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> Schedule:
    """Store a schedule, having proved it can actually produce a run.

    Both halves are checked here rather than at 3am: the recurrence must yield
    a window, and the stored values must satisfy the published contract they
    will be submitted against. A schedule that could only ever fail is refused
    at the moment somebody can still do something about it.
    """
    entry = entry_for_revision(session, revision_id=publication_revision_id)
    if entry is None:
        raise ValidationFailed(
            "A schedule can only be attached to a published catalog entry revision."
        )
    # A dry run of exactly what firing will do, minus the submission.
    bind_submission(session, entry=entry, submitted=dict(input_values))

    anchor = start_at or datetime.now(UTC)
    rrule = _with_dtstart(rrule, anchor=anchor, timezone=timezone, dst_policy=dst_policy)
    recurrence = Recurrence(
        start=anchor,
        rrule=rrule,
        interval_seconds=interval_seconds,
        timezone=timezone,
        dst_policy=dst_policy,
        end_at=end_at,
    )
    first = recurrence.first()
    if first is None:
        raise ValidationFailed(
            "That recurrence produces no window at all, so the schedule would never run."
        )

    schedule = Schedule(
        project_id=default_project_id(session),
        publication_revision_id=publication_revision_id,
        owner_id=owner_id,
        title=title,
        rrule=rrule,
        interval_seconds=interval_seconds,
        timezone=timezone,
        dst_policy=dst_policy,
        catchup_policy=catchup_policy,
        overlap_policy=overlap_policy,
        max_concurrent_runs=max_concurrent_runs,
        input_values=dict(input_values),
        next_fire_at=first,
        end_at=end_at,
    )
    session.add(schedule)
    session.flush()
    record_event(
        session,
        schedule.id,
        event_type="created",
        actor_id=owner_id,
        message=f"First window {first.isoformat()}.",
    )
    return schedule


def pause(session: Session, schedule_id: uuid.UUID, *, actor_id: uuid.UUID) -> None:
    schedule = session.get(Schedule, schedule_id)
    if schedule is None:
        raise ValidationFailed(f"Schedule {schedule_id} does not exist.")
    schedule.status = ScheduleStatus.PAUSED
    record_event(session, schedule.id, event_type="paused", actor_id=actor_id)
    session.flush()


def resume(session: Session, schedule_id: uuid.UUID, *, actor_id: uuid.UUID) -> None:
    """Start again from the next window, not from the backlog.

    Everything owed while the schedule was paused is dropped. A schedule
    somebody paused for a fortnight must not answer with a fortnight of runs,
    whatever its catchup policy says -- that policy is about a scheduler that
    was down, not about a decision somebody made.
    """
    schedule = session.get(Schedule, schedule_id)
    if schedule is None:
        raise ValidationFailed(f"Schedule {schedule_id} does not exist.")
    schedule.status = ScheduleStatus.ACTIVE
    recurrence = recurrence_of(schedule)
    schedule.next_fire_at = recurrence.next_after(datetime.now(UTC))
    record_event(
        session,
        schedule.id,
        event_type="resumed",
        actor_id=actor_id,
        message=(
            f"Next window {schedule.next_fire_at.isoformat()}."
            if schedule.next_fire_at
            else "No further windows."
        ),
    )
    session.flush()


def archive(session: Session, schedule_id: uuid.UUID, *, actor_id: uuid.UUID) -> None:
    """Retire a schedule.

    The firing history stays, and so do the runs it started: this removes a
    schedule from the things that will happen, not from the record of what
    did.
    """
    schedule = session.get(Schedule, schedule_id)
    if schedule is None:
        raise ValidationFailed(f"Schedule {schedule_id} does not exist.")
    schedule.status = ScheduleStatus.ARCHIVED
    schedule.next_fire_at = None
    record_event(session, schedule.id, event_type="archived", actor_id=actor_id)
    session.flush()


# --- reading, for display --------------------------------------------------


@dataclass(frozen=True, slots=True)
class ScheduleView:
    """A schedule with the catalog entry it runs, for display."""

    schedule: Schedule
    slug: str
    entry_title: str
    version: int
    revision_is_current: bool
    """False when the entry has been re-published since this schedule was made.

    A schedule pins its revision deliberately, so re-publishing never changes
    what it runs. The consequence is that it can quietly fall behind, and an
    owner who is not told would have no way to know.
    """


@dataclass(frozen=True, slots=True)
class ScheduleHistory:
    view: ScheduleView
    fires: list[ScheduleFire]
    events: list[ScheduleEvent]


def _views(session: Session, schedules: list[Schedule]) -> list[ScheduleView]:
    """Attach each schedule's catalog entry, in one query rather than N."""
    if not schedules:
        return []
    rows = session.execute(
        select(PublicationRevision, Publication)
        .join(Publication, Publication.id == PublicationRevision.publication_id)
        .where(PublicationRevision.id.in_({s.publication_revision_id for s in schedules}))
    ).all()
    entries = {revision.id: (revision, publication) for revision, publication in rows}
    views = []
    for schedule in schedules:
        # The foreign key guarantees this, so a missing row is a bug rather
        # than a state to render.
        revision, publication = entries[schedule.publication_revision_id]
        views.append(
            ScheduleView(
                schedule=schedule,
                slug=publication.slug,
                entry_title=revision.title,
                version=revision.version,
                revision_is_current=publication.current_revision_id == revision.id,
            )
        )
    return views


def list_schedules(
    session: Session, *, owner_id: uuid.UUID | None = None, limit: int = 50
) -> list[ScheduleView]:
    """Schedules, soonest first, with the ones that will never fire last."""
    query = (
        select(Schedule)
        .where(Schedule.status != ScheduleStatus.ARCHIVED)
        .order_by(Schedule.next_fire_at.asc().nulls_last(), Schedule.created_at.desc())
        .limit(min(limit, 200))
    )
    if owner_id is not None:
        query = query.where(Schedule.owner_id == owner_id)
    return _views(session, list(session.execute(query).scalars()))


def schedule_history(
    session: Session, schedule_id: uuid.UUID, *, limit: int = 20
) -> ScheduleHistory | None:
    schedule = session.get(Schedule, schedule_id)
    if schedule is None:
        return None
    fires = list(
        session.execute(
            select(ScheduleFire)
            .where(ScheduleFire.schedule_id == schedule_id)
            .order_by(ScheduleFire.fire_at.desc())
            .limit(limit)
        ).scalars()
    )
    events = list(
        session.execute(
            select(ScheduleEvent)
            .where(ScheduleEvent.schedule_id == schedule_id)
            .order_by(ScheduleEvent.created_at.desc())
            .limit(limit)
        ).scalars()
    )
    return ScheduleHistory(view=_views(session, [schedule])[0], fires=fires, events=events)
