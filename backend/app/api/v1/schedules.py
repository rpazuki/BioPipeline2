"""Schedules: a catalog entry, some values, and a recurrence.

Open to any signed-in user, because a schedule grants nobody a power they did
not already have: it repeats a submission they could make by hand, against an
entry they can already see, as themselves. What it does add is that nobody is
watching, so the defaults matter — `overlap_policy = skip` with
`max_concurrent_runs = 1` means a schedule can never have two runs of its own
going at once, whatever happens to the first.

Somebody else's schedule is a 404, not a 403, for the same reason a run is.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, Db
from app.api.schemas import (
    CreateScheduleRequest,
    Page,
    PublicationFieldResponse,
    ScheduleDetail,
    ScheduleEventResponse,
    ScheduleFireResponse,
    ScheduleSummary,
)
from app.application.publications import catalog_entry, entry_for_revision
from app.application.schedules import (
    ScheduleHistory,
    ScheduleView,
    archive,
    create_schedule,
    list_schedules,
    pause,
    resume,
    schedule_history,
)
from app.domain.enums import (
    CatchupPolicy,
    DstPolicy,
    FieldVisibility,
    OverlapPolicy,
    PrimitiveType,
    ScheduleStatus,
)

router = APIRouter(prefix="/schedules", tags=["schedules"])


def _summary(view: ScheduleView) -> ScheduleSummary:
    schedule = view.schedule
    return ScheduleSummary(
        id=schedule.id,
        title=schedule.title,
        status=ScheduleStatus(schedule.status),
        owner_id=schedule.owner_id,
        slug=view.slug,
        entry_title=view.entry_title,
        version=view.version,
        revision_is_current=view.revision_is_current,
        rrule=schedule.rrule,
        interval_seconds=schedule.interval_seconds,
        timezone=schedule.timezone,
        # Coerced, not cast: each column carries a CHECK constraint from the
        # same enum, so a value outside it cannot be in the database.
        dst_policy=DstPolicy(schedule.dst_policy),
        catchup_policy=CatchupPolicy(schedule.catchup_policy),
        overlap_policy=OverlapPolicy(schedule.overlap_policy),
        max_concurrent_runs=schedule.max_concurrent_runs,
        next_fire_at=schedule.next_fire_at,
        last_fire_at=schedule.last_fire_at,
        last_run_id=schedule.last_run_id,
        end_at=schedule.end_at,
        created_at=schedule.created_at,
    )


def _history_or_404(db: Db, schedule_id: uuid.UUID, principal: CurrentUser) -> ScheduleHistory:
    history = schedule_history(db, schedule_id)
    if history is None or (
        not principal.is_admin and history.view.schedule.owner_id != principal.user_id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "schedule.not_found", "message": "No such schedule."},
        )
    return history


@router.get("", response_model=Page[ScheduleSummary])
def list_own(db: Db, principal: CurrentUser, limit: int = 50) -> Page[ScheduleSummary]:
    """Soonest first, with the ones that will never fire again last."""
    views = list_schedules(
        db, owner_id=None if principal.is_admin else principal.user_id, limit=limit
    )
    return Page[ScheduleSummary](items=[_summary(view) for view in views], total=len(views))


@router.post("", response_model=ScheduleDetail, status_code=status.HTTP_201_CREATED)
def create(payload: CreateScheduleRequest, db: Db, principal: CurrentUser) -> ScheduleDetail:
    """Store a schedule, having proved it can actually produce a run.

    Both halves are checked here rather than at 3am: the recurrence must yield
    a window, and the values must satisfy the published contract they will be
    submitted against. The application service raises for either, and the
    domain-error handler turns that into a 422 naming the field.
    """
    entry = catalog_entry(db, slug=payload.slug)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "catalog.not_found", "message": "No such catalog entry."},
        )
    schedule = create_schedule(
        db,
        publication_revision_id=entry.revision_id,
        owner_id=principal.user_id,
        title=payload.title,
        input_values=payload.values,
        rrule=payload.rrule,
        interval_seconds=payload.interval_seconds,
        timezone=payload.timezone,
        dst_policy=payload.dst_policy,
        catchup_policy=payload.catchup_policy,
        overlap_policy=payload.overlap_policy,
        max_concurrent_runs=payload.max_concurrent_runs,
        start_at=payload.start_at,
        end_at=payload.end_at,
    )
    return _detail(_history_or_404(db, schedule.id, principal))


def _detail(history: ScheduleHistory) -> ScheduleDetail:
    schedule = history.view.schedule
    return ScheduleDetail(
        **_summary(history.view).model_dump(),
        values=dict(schedule.input_values or {}),
        fires=[ScheduleFireResponse.model_validate(row) for row in history.fires],
        events=[ScheduleEventResponse.model_validate(row) for row in history.events],
    )


@router.get("/{schedule_id}", response_model=ScheduleDetail)
def read(schedule_id: uuid.UUID, db: Db, principal: CurrentUser) -> ScheduleDetail:
    """The schedule, its stored values, and what has happened to it.

    The fields come from the revision this schedule *pins*, not from whatever
    the entry points at now. Otherwise a re-published entry would relabel a
    schedule's stored values with words that were never used to collect them,
    and a renamed field would render as a raw key. `published_only=False`
    because a withdrawn entry's schedule still has to be readable.
    """
    history = _history_or_404(db, schedule_id, principal)
    detail = _detail(history)
    entry = entry_for_revision(
        db,
        revision_id=history.view.schedule.publication_revision_id,
        published_only=False,
    )
    if entry is not None:
        detail.fields = [
            PublicationFieldResponse(
                key=field.key,
                label=field.label,
                field_type=PrimitiveType(field.field_type),
                required=field.required,
                help_text=field.help_text,
                placeholder=field.placeholder,
                ui_group=field.ui_group,
                default_value=field.default_value,
                type_ref=field.type_ref,
                source_policy=field.source_policy,
                order_index=field.order_index,
            )
            for field in entry.fields
            if field.visibility != FieldVisibility.HIDDEN
        ]
    return detail


@router.post("/{schedule_id}/pause", response_model=ScheduleSummary)
def pause_schedule(schedule_id: uuid.UUID, db: Db, principal: CurrentUser) -> ScheduleSummary:
    history = _history_or_404(db, schedule_id, principal)
    pause(db, schedule_id, actor_id=principal.user_id)
    return _summary(history.view)


@router.post("/{schedule_id}/resume", response_model=ScheduleSummary)
def resume_schedule(schedule_id: uuid.UUID, db: Db, principal: CurrentUser) -> ScheduleSummary:
    """Start again from the next window, not from the backlog.

    Everything owed while it was paused is dropped. A schedule somebody paused
    for a fortnight must not answer with a fortnight of runs, whatever its
    catchup policy says — that policy is about a scheduler that was down, not
    about a decision somebody made.
    """
    history = _history_or_404(db, schedule_id, principal)
    resume(db, schedule_id, actor_id=principal.user_id)
    return _summary(history.view)


@router.post("/{schedule_id}/archive", response_model=ScheduleSummary)
def archive_schedule(schedule_id: uuid.UUID, db: Db, principal: CurrentUser) -> ScheduleSummary:
    """Retire a schedule. Its firing history and its runs stay."""
    history = _history_or_404(db, schedule_id, principal)
    archive(db, schedule_id, actor_id=principal.user_id)
    return _summary(history.view)
