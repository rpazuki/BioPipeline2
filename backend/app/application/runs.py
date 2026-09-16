"""Run submission and inspection.

Submitting a run is the one use case that must be atomic across several
tables: the run, its field values, every task, and every dependency edge. A
partial write here would leave a run that can never complete, so the whole
thing happens in one transaction and the caller commits it.

Two behaviours are load-bearing:

* **Idempotent submission.** A repeated submit returns the existing run rather
  than starting a second one. On shared compute that is the difference between
  a double-clicked button costing nothing and costing a day of alignment.
* **Correct initial task state.** A task with no unmet dependency starts
  ``queued``; everything else starts ``created`` and is released by the
  orchestrator. Getting this wrong either strands a run or starts work whose
  inputs do not exist.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.application.pipelines import default_project_id, load_compiled
from app.domain.enums import RunStatus, RunTrigger, TaskStatus
from app.domain.errors import DomainError, ValidationFailed
from app.domain.ir import CompiledPipeline, Diagnostic
from app.domain.lifecycle import RUN_MACHINE, Actor, run_status_for_tasks
from app.domain.materialise import (
    FanOutEnumerator,
    MaterialisationResult,
    ResourceRequest,
    TaskPlan,
    materialise,
)
from app.infrastructure.db.models import (
    PipelineRevision,
    Run,
    RunFieldValue,
    RunTask,
    RunTaskDependency,
)


class SubmissionRejected(DomainError):
    """The submitted values cannot produce a runnable plan."""

    code = "run.submission_rejected"

    def __init__(self, diagnostics: list[Diagnostic]) -> None:
        errors = [d for d in diagnostics if d.severity == "error"]
        super().__init__(
            f"Run submission rejected with {len(errors)} error(s).",
            details={"errors": [d.model_dump(mode="json") for d in errors]},
        )
        self.diagnostics = diagnostics


@dataclass(frozen=True, slots=True)
class RunSubmitted:
    run_id: uuid.UUID
    task_count: int
    reused: bool
    """True when an idempotency key matched an existing run."""
    warnings: list[Diagnostic]


def submit_run(
    session: Session,
    *,
    pipeline_revision_id: uuid.UUID,
    requested_by: uuid.UUID,
    values: Mapping[str, Any],
    enumerate_fanout: FanOutEnumerator | None = None,
    idempotency_key: str | None = None,
    trigger: RunTrigger = RunTrigger.MANUAL,
    publication_revision_id: uuid.UUID | None = None,
    environment_snapshot_id: uuid.UUID | None = None,
    resources: Mapping[str, ResourceRequest] | None = None,
    compiled: CompiledPipeline | None = None,
    recorded_values: Mapping[str, Any] | None = None,
) -> RunSubmitted:
    """Materialise a plan and persist it as a run and its tasks.

    ``compiled`` lets a caller supply an IR it has already derived — a catalog
    submission applies its publication's bindings first, producing a plan that
    is *not* the stored revision (ADR 0031). It is passed in rather than
    re-derived here so there is one submission path: idempotency, the run row
    and the task graph are written the same way however the plan was reached.

    ``recorded_values`` is what gets written to ``runs.input_values``. For a
    catalog submission those are the publication's field keys — what the
    researcher actually filled in — while ``values`` carries the pipeline's own
    input keys, which is what materialisation needs. Recording the translation
    rather than the original would make an old run unreadable to the person who
    submitted it.
    """
    if idempotency_key is not None:
        existing = session.execute(
            select(Run).where(
                Run.requested_by == requested_by,
                Run.idempotency_key == idempotency_key,
            )
        ).scalar_one_or_none()
        if existing is not None:
            count = session.execute(select(RunTask.id).where(RunTask.run_id == existing.id)).all()
            return RunSubmitted(existing.id, len(count), reused=True, warnings=[])

    revision = session.get(PipelineRevision, pipeline_revision_id)
    if revision is None:
        raise ValidationFailed(f"Pipeline revision {pipeline_revision_id} does not exist.")

    compiled = compiled if compiled is not None else load_compiled(session, pipeline_revision_id)
    plan: MaterialisationResult = materialise(
        compiled, values, enumerate_fanout=enumerate_fanout, resources=resources
    )
    if not plan.ok:
        raise SubmissionRejected(plan.diagnostics)
    if not plan.tasks:
        raise SubmissionRejected(
            [
                Diagnostic(
                    severity="error",
                    code="run.no_tasks",
                    message="The plan produced no tasks, so the run would do nothing.",
                )
            ]
        )

    run = Run(
        project_id=default_project_id(session),
        pipeline_revision_id=pipeline_revision_id,
        publication_revision_id=publication_revision_id,
        requested_by=requested_by,
        requested_from=trigger,
        idempotency_key=idempotency_key,
        status=RunStatus.QUEUED,
        input_values=dict(recorded_values if recorded_values is not None else values),
        compiled_run_spec={"graph_hash": compiled.graph_hash},
        environment_snapshot_id=environment_snapshot_id,
    )
    session.add(run)
    try:
        # A savepoint, because a duplicate key aborts the enclosing
        # transaction in PostgreSQL and the caller may have more to do.
        with session.begin_nested():
            session.flush()
    except IntegrityError as error:
        if idempotency_key is None or "idempotency_key" not in str(error.orig):
            raise
        # Lost a race with a concurrent submission of the same key.
        session.expunge(run)
        winner = session.execute(
            select(Run).where(
                Run.requested_by == requested_by,
                Run.idempotency_key == idempotency_key,
            )
        ).scalar_one()
        count = session.execute(select(RunTask.id).where(RunTask.run_id == winner.id)).all()
        return RunSubmitted(winner.id, len(count), reused=True, warnings=[])

    for key, value in values.items():
        session.add(
            RunFieldValue(
                run_id=run.id,
                field_key=key,
                value=value,
                value_source="researcher",
            )
        )

    _persist_tasks(session, run_id=run.id, tasks=plan.tasks)
    session.flush()

    return RunSubmitted(
        run_id=run.id,
        task_count=len(plan.tasks),
        reused=False,
        warnings=[d for d in plan.diagnostics if d.severity == "warning"],
    )


def _persist_tasks(session: Session, *, run_id: uuid.UUID, tasks: list[TaskPlan]) -> None:
    """Insert tasks and their dependency edges.

    Tasks are inserted first so every edge can reference a real row; the plan's
    task keys are mapped to identifiers as they are created.
    """
    identifiers: dict[str, uuid.UUID] = {}
    for plan in tasks:
        ready = not plan.needs
        row = RunTask(
            run_id=run_id,
            stage_key=plan.stage_key,
            task_key=plan.task_key,
            # A task with nothing to wait for is immediately claimable.
            # Everything else waits for the orchestrator to release it.
            status=TaskStatus.QUEUED if ready else TaskStatus.CREATED,
            dependencies_satisfied=ready,
            task_spec={
                "stage": plan.stage_name,
                "variant": plan.variant,
                "item": plan.item,
                "steps": plan.steps,
                "inputs": plan.inputs,
                "outputs": plan.outputs,
            },
            task_class=plan.resources.task_class,
            cpu_request_millicores=plan.resources.cpu_millicores,
            memory_request_bytes=plan.resources.memory_bytes,
            wall_time_limit_seconds=plan.resources.wall_time_seconds,
            exclusive=plan.resources.exclusive,
        )
        session.add(row)
        session.flush()
        identifiers[plan.task_key] = row.id

    for plan in tasks:
        for needed in plan.needs:
            depends_on = identifiers.get(needed)
            if depends_on is None:
                raise ValidationFailed(
                    f"Task '{plan.task_key}' depends on '{needed}', which the plan "
                    "does not contain."
                )
            session.add(
                RunTaskDependency(task_id=identifiers[plan.task_key], depends_on_task_id=depends_on)
            )
    session.flush()


@dataclass(frozen=True, slots=True)
class RunView:
    """A run and the shape of its work, for display."""

    run_id: uuid.UUID
    status: str
    task_counts: dict[str, int]
    total_tasks: int

    @property
    def is_finished(self) -> bool:
        return self.status in {
            RunStatus.SUCCEEDED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        }


def get_run(session: Session, run_id: uuid.UUID) -> RunView:
    """Summarise a run and the state of its tasks."""
    run = session.get(Run, run_id)
    if run is None:
        raise ValidationFailed(f"Run {run_id} does not exist.")
    rows = session.execute(select(RunTask.status).where(RunTask.run_id == run_id)).scalars()
    counts: dict[str, int] = {}
    total = 0
    for status in rows:
        counts[status] = counts.get(status, 0) + 1
        total += 1
    return RunView(run_id=run.id, status=run.status, task_counts=counts, total_tasks=total)


def advance_run(session: Session, run_id: uuid.UUID) -> str:
    """Recompute a run's status from its tasks, and return it.

    Called after every task transition. The aggregation rule lives in the
    domain layer so it can be reasoned about without a database; this only
    reads the task statuses and writes the answer.

    Terminal states are absorbing, so a run that already finished is left
    alone -- a late-arriving task update must not reopen it.
    """
    run = session.get(Run, run_id)
    if run is None:
        raise ValidationFailed(f"Run {run_id} does not exist.")
    if RUN_MACHINE.is_terminal(run.status):
        return run.status

    statuses = list(
        session.execute(select(RunTask.status).where(RunTask.run_id == run_id)).scalars()
    )
    target = run_status_for_tasks(statuses, cancel_requested=run.cancel_requested_at is not None)
    if target == run.status:
        return run.status

    if not RUN_MACHINE.can(run.status, target, Actor.ORCHESTRATOR):
        # Not an error: a run can reach the same conclusion by more than one
        # path, and a transition the machine forbids means the aggregate
        # disagrees with the recorded state rather than that work was lost.
        return run.status

    run.status = target
    if target == RunStatus.RUNNING and run.started_at is None:
        run.started_at = datetime.now(UTC)
    if RUN_MACHINE.is_terminal(target):
        run.finished_at = datetime.now(UTC)
    session.flush()
    return target


def request_cancel(session: Session, run_id: uuid.UUID, *, requested_by: uuid.UUID) -> str:
    """Ask a run to stop.

    Returns immediately: this records the request, and workers observe it on
    their next heartbeat. The reaper owns the final transition to `cancelled`,
    because the worker holding a running task may already be gone.
    """
    run = session.get(Run, run_id)
    if run is None:
        raise ValidationFailed(f"Run {run_id} does not exist.")
    if RUN_MACHINE.is_terminal(run.status):
        return run.status
    if run.cancel_requested_at is None:
        run.cancel_requested_at = datetime.now(UTC)
        run.cancel_requested_by = requested_by
    if RUN_MACHINE.can(run.status, RunStatus.CANCEL_REQUESTED, Actor.API):
        run.status = RunStatus.CANCEL_REQUESTED
    # Queued tasks can stop now; running ones are stopped by their worker.
    session.execute(
        text(
            "UPDATE run_tasks SET status = 'cancelled', "
            "status_reason = 'the run was cancelled', finished_at = now(), "
            "updated_at = now() "
            "WHERE run_id = :r AND status IN ('created', 'queued', 'retry_wait')"
        ),
        {"r": run_id},
    )
    session.execute(
        text(
            "UPDATE run_tasks SET cancel_requested_at = now(), updated_at = now() "
            "WHERE run_id = :r AND status IN ('claimed', 'running')"
        ),
        {"r": run_id},
    )
    session.flush()
    return run.status


def release_ready_tasks(session: Session, run_id: uuid.UUID) -> list[uuid.UUID]:
    """Move tasks whose dependencies have all succeeded to ``queued``.

    Owned by the orchestrator. Written as one statement so it is atomic and
    cannot half-release a fan-in.
    """
    from sqlalchemy import text

    rows = session.execute(
        text(
            """
            UPDATE run_tasks t
            SET status = 'queued',
                dependencies_satisfied = true,
                updated_at = now()
            WHERE t.run_id = :run_id
              AND t.status = 'created'
              AND NOT EXISTS (
                  SELECT 1
                  FROM run_task_dependencies d
                  JOIN run_tasks u ON u.id = d.depends_on_task_id
                  WHERE d.task_id = t.id
                    AND u.status <> 'succeeded'
              )
            RETURNING t.id
            """
        ),
        {"run_id": run_id},
    ).scalars()
    return list(rows)
