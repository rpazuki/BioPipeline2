"""Runs: submit, inspect, cancel, and retrieve results."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Header, HTTPException, Response, status
from sqlalchemy import select

from app.api.deps import Config, CurrentUser, Db
from app.api.schemas import (
    ArtifactSummary,
    AttemptSummary,
    DeliverySummary,
    DiagnosticResponse,
    Page,
    RunDetail,
    RunSummary,
    SubmitRunRequest,
    SubmitRunResponse,
    TaskLogResponse,
    TaskSummary,
)
from app.application.artifacts import artifacts_for_run
from app.application.deliveries import retry_delivery
from app.application.runs import SubmissionRejected, get_run, request_cancel, submit_run
from app.application.task_logs import DEFAULT_TAIL_BYTES, attempts_for_task, read_log
from app.domain.enums import AttemptStatus, RunStatus, RunTrigger, TaskStatus
from app.infrastructure.artifacts import PosixArtifactStore
from app.infrastructure.db.models import Run, RunDelivery, RunTask
from app.infrastructure.fanout import DirectoryFanOut
from app.infrastructure.mounts import readable_roots

router = APIRouter(prefix="/runs", tags=["runs"])


def _visible_or_404(db: Db, run_id: uuid.UUID, principal: CurrentUser) -> Run:
    """Fetch a run the caller may see.

    A run somebody else owns returns 404 rather than 403: telling a caller
    that a resource exists but is not theirs leaks which runs exist.
    """
    run = db.get(Run, run_id)
    if run is None or run.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "run.not_found", "message": "No such run."},
        )
    if not principal.is_admin and run.requested_by != principal.user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "run.not_found", "message": "No such run."},
        )
    return run


@router.post("", response_model=SubmitRunResponse, status_code=status.HTTP_201_CREATED)
def submit(
    payload: SubmitRunRequest,
    db: Db,
    principal: CurrentUser,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> SubmitRunResponse:
    """Submit a run.

    ``Idempotency-Key`` makes a retry safe. Without it a double-clicked submit
    button starts a second run, which on shared compute can cost a day of
    alignment rather than nothing.
    """
    try:
        submitted = submit_run(
            db,
            pipeline_revision_id=payload.pipeline_revision_id,
            requested_by=principal.user_id,
            values=payload.values,
            idempotency_key=idempotency_key,
            # A stage that fans out cannot be materialised without this, and
            # one task per plate-reader export is the ordinary shape of the
            # work rather than an edge case. Confined to the roots a task
            # container will actually be able to see.
            enumerate_fanout=DirectoryFanOut(readable_roots(db)),
        )
    except SubmissionRejected as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": error.code,
                "message": error.message,
                "details": error.details,
            },
        ) from error
    if submitted.reused:
        # Not a new resource: the caller is holding the one they already made.
        response.status_code = status.HTTP_200_OK
    return SubmitRunResponse(
        run_id=submitted.run_id,
        task_count=submitted.task_count,
        reused=submitted.reused,
        warnings=[
            DiagnosticResponse(
                severity=d.severity, code=d.code, message=d.message, location=d.location
            )
            for d in submitted.warnings
        ],
    )


@router.get("", response_model=Page[RunSummary])
def list_runs(
    db: Db, principal: CurrentUser, limit: int = 50, status_filter: str | None = None
) -> Page[RunSummary]:
    """List runs. Researchers see their own; admins see everything."""
    query = select(Run).where(Run.deleted_at.is_(None))
    if not principal.is_admin:
        query = query.where(Run.requested_by == principal.user_id)
    if status_filter:
        query = query.where(Run.status == status_filter)
    rows = list(db.execute(query.order_by(Run.created_at.desc()).limit(min(limit, 200))).scalars())
    return Page[RunSummary](items=[RunSummary.model_validate(row) for row in rows])


@router.get("/{run_id}", response_model=RunDetail)
def read_run(run_id: uuid.UUID, db: Db, principal: CurrentUser) -> RunDetail:
    run = _visible_or_404(db, run_id, principal)
    view = get_run(db, run_id)
    # Coerced, not cast: a status outside the vocabulary would be a bug the
    # database's CHECK constraint already forbids, and this fails loudly
    # rather than serving a value no client can render.
    return RunDetail(
        id=run.id,
        status=RunStatus(run.status),
        pipeline_revision_id=run.pipeline_revision_id,
        requested_by=run.requested_by,
        requested_from=RunTrigger(run.requested_from),
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        task_counts={TaskStatus(key): value for key, value in view.task_counts.items()},
        total_tasks=view.total_tasks,
        input_values=run.input_values,
        cancel_requested_at=run.cancel_requested_at,
    )


@router.get("/{run_id}/tasks", response_model=Page[TaskSummary])
def list_tasks(run_id: uuid.UUID, db: Db, principal: CurrentUser) -> Page[TaskSummary]:
    _visible_or_404(db, run_id, principal)
    rows = list(
        db.execute(
            select(RunTask).where(RunTask.run_id == run_id).order_by(RunTask.task_key)
        ).scalars()
    )
    return Page[TaskSummary](
        items=[TaskSummary.model_validate(row) for row in rows], total=len(rows)
    )


@router.get("/{run_id}/artifacts", response_model=Page[ArtifactSummary])
def list_artifacts(
    run_id: uuid.UUID, db: Db, principal: CurrentUser, settings: Config
) -> Page[ArtifactSummary]:
    """A run's outputs, with what can be done with each.

    `is_directory` costs one stat per row and saves the client a request per
    row: a tree of results is retrieved a file at a time, so a list that
    cannot tell the two apart can only offer a control that sometimes fails.
    """
    _visible_or_404(db, run_id, principal)
    store = PosixArtifactStore(settings.artifact_root)
    items = []
    for row in artifacts_for_run(db, run_id):
        summary = ArtifactSummary.model_validate(row)
        summary.is_directory = store.path_for(row.storage_key).is_dir()
        items.append(summary)
    return Page[ArtifactSummary](items=items, total=len(items))


def _task_or_404(db: Db, run_id: uuid.UUID, task_id: uuid.UUID) -> RunTask:
    task = db.get(RunTask, task_id)
    if task is None or task.run_id != run_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "task.not_found", "message": "No such task in this run."},
        )
    return task


@router.get("/{run_id}/tasks/{task_id}/attempts", response_model=Page[AttemptSummary])
def list_attempts(
    run_id: uuid.UUID, task_id: uuid.UUID, db: Db, principal: CurrentUser
) -> Page[AttemptSummary]:
    """Every attempt at one task, newest first."""
    _visible_or_404(db, run_id, principal)
    _task_or_404(db, run_id, task_id)
    rows = attempts_for_task(db, task_id)
    return Page[AttemptSummary](
        items=[
            AttemptSummary(
                id=row.id,
                attempt_number=row.attempt_number,
                status=AttemptStatus(row.status),
                exit_code=row.exit_code,
                worker_id=row.worker_id,
                image_ref=row.image_ref,
                started_at=row.started_at,
                finished_at=row.finished_at,
                log_artifact_id=row.log_artifact_id,
            )
            for row in rows
        ],
        total=len(rows),
    )


@router.get("/{run_id}/tasks/{task_id}/log", response_model=TaskLogResponse)
def read_task_log(
    run_id: uuid.UUID,
    task_id: uuid.UUID,
    db: Db,
    principal: CurrentUser,
    settings: Config,
    attempt: int | None = None,
    tail_bytes: int = DEFAULT_TAIL_BYTES,
) -> TaskLogResponse:
    """What a task printed, latest attempt by default.

    The tail, not the whole thing: an aligner prints for hours and the end is
    where the error is. The whole log is an artifact, downloadable by its id.

    A running attempt is read from the workspace the container is writing
    into, so a long task can be watched rather than only examined afterwards.
    """
    _visible_or_404(db, run_id, principal)
    _task_or_404(db, run_id, task_id)
    view = read_log(
        db,
        task_id=task_id,
        run_id=run_id,
        store=PosixArtifactStore(settings.artifact_root),
        workspace_root=settings.workspace_root,
        attempt_number=attempt,
        # Bounded whatever is asked for: this runs in the process that answers
        # every other request.
        tail_bytes=max(1024, min(tail_bytes, 4 * 1024 * 1024)),
    )
    if view is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "task.no_attempt",
                "message": "This task has not been attempted yet, so there is no log.",
            },
        )
    return TaskLogResponse(
        attempt_number=view.attempt_number,
        text=view.text,
        bytes_read=view.bytes_read,
        bytes_total=view.bytes_total,
        truncated=view.truncated,
        live=view.live,
        artifact_id=view.artifact_id,
        message=view.message,
    )


@router.get("/{run_id}/deliveries", response_model=Page[DeliverySummary])
def list_deliveries(run_id: uuid.UUID, db: Db, principal: CurrentUser) -> Page[DeliverySummary]:
    """Where a run's outputs were sent.

    Separate from artifacts because a delivery can fail after the run has
    already succeeded, and a researcher needs to see that rather than wonder
    why a file never appeared on the share.
    """
    _visible_or_404(db, run_id, principal)
    # Outer-joined to the task, so a delivery planned before its task existed
    # still appears rather than vanishing from the list.
    rows = list(
        db.execute(
            select(RunDelivery, RunTask.task_key)
            .outerjoin(RunTask, RunDelivery.task_id == RunTask.id)
            .where(RunDelivery.run_id == run_id)
            .order_by(RunTask.task_key, RunDelivery.field_key)
        )
    )
    return Page[DeliverySummary](
        items=[
            DeliverySummary.model_validate(delivery).model_copy(update={"task_key": task_key})
            for delivery, task_key in rows
        ],
        total=len(rows),
    )


@router.post("/{run_id}/deliveries/{delivery_id}/retry", response_model=DeliverySummary)
def retry_run_delivery(
    run_id: uuid.UUID, delivery_id: uuid.UUID, db: Db, principal: CurrentUser
) -> DeliverySummary:
    """Attempt a failed delivery again, now.

    For the case the failure message describes: an administrator has mounted
    the share or made the root writable, and waiting out a backoff nobody can
    see serves nobody. The courier picks it up on its next round.
    """
    _visible_or_404(db, run_id, principal)
    delivery = db.execute(
        select(RunDelivery).where(RunDelivery.id == delivery_id, RunDelivery.run_id == run_id)
    ).scalar_one_or_none()
    if delivery is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "delivery.not_found", "message": "No such delivery on this run."},
        )
    retry_delivery(db, delivery)
    task = db.get(RunTask, delivery.task_id) if delivery.task_id else None
    return DeliverySummary.model_validate(delivery).model_copy(
        update={"task_key": task.task_key if task else None}
    )


@router.post("/{run_id}/cancel", response_model=RunSummary)
def cancel(run_id: uuid.UUID, db: Db, principal: CurrentUser) -> RunSummary:
    """Ask a run to stop.

    An acknowledgement, not a completion: queued tasks stop immediately, and
    running ones are flagged for their worker. The reaper converges the run,
    because the worker holding the last task may already be gone.
    """
    run = _visible_or_404(db, run_id, principal)
    request_cancel(db, run_id, requested_by=principal.user_id)
    db.refresh(run)
    return RunSummary.model_validate(run)
