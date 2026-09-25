"""Executing one claimed task, and recording what happened.

Sits between the claiming logic and the container adapter. Its job is the part
that is easy to get wrong: deciding whether a task actually succeeded, and
making sure the database says so exactly once.

The rule that matters: **the worker verifies declared outputs itself.** A task
reporting success while failing to produce what it declared has failed. Only a
stat of the workspace settles that, and the task's own report is advisory.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.application.artifacts import promote_log, promote_outputs
from app.application.environments import runtime_mount
from app.application.uploads import UploadRejected, stage_inputs, staged_inputs_for_run
from app.domain.enums import AttemptStatus, TaskStatus
from app.domain.task_contract import (
    CallableRef,
    InputBinding,
    OutputDeclaration,
    ResourceLimits,
    StepSpec,
    TaskSpec,
)
from app.infrastructure.artifacts import PosixArtifactStore
from app.infrastructure.execution.docker import (
    DockerAdapter,
    ExecutionOutcome,
    make_container_name,
)
from app.infrastructure.workspace import Workspace, collect_outputs
from app.workers.stopping import StopSignal

logger = logging.getLogger("biopipeline2.executor")


@dataclass(frozen=True, slots=True)
class TaskOutcome:
    """The worker's verdict, which is not always the container's."""

    task_id: uuid.UUID
    status: str
    attempt_status: str
    reason: str | None
    exit_code: int | None
    outputs: list[dict[str, Any]]
    artifacts: list[dict[str, Any]]
    # False when this worker no longer owns the task: the lease was lost and
    # somebody else has it. The other fields then describe *this attempt*,
    # which is over, and say nothing about the task, which is not ours to
    # speak for. A caller must not release dependants or advance the run.
    owned: bool = True

    @property
    def succeeded(self) -> bool:
        return self.owned and self.status == TaskStatus.SUCCEEDED


def build_spec(
    *,
    task_id: uuid.UUID,
    run_id: uuid.UUID,
    attempt: int,
    stage_key: str,
    task_key: str,
    task_spec: dict[str, Any],
    limits: ResourceLimits,
    environment: dict[str, str] | None = None,
) -> TaskSpec:
    """Turn a stored task spec into one container specification.

    One container per **task**, not per step. A stage's steps pass live Python
    objects to one another, so they have to share a process; splitting them
    would hand the next step the string ``"df_parsed"`` where it expected a
    DataFrame (contract 2.0).
    """
    # Passed through as written. Stripping the leading slash to make an
    # absolute path satisfy a relative-path type is how `/mnt/lab/plate.csv`
    # became a lookup under the workspace -- silently, with the container
    # reporting a file nobody had named.
    inputs = [
        InputBinding(
            key=key,
            kind="file" if isinstance(value, str) else "value",
            path=value if isinstance(value, str) else None,
            value=None if isinstance(value, str) else value,
        )
        for key, value in (task_spec.get("inputs") or {}).items()
    ]
    # Outputs stay workspace-relative, and an absolute one fails here rather
    # than being coerced: a task writes only where the platform can verify it
    # and deliver from, and shared roots are mounted read-only anyway.
    outputs = [
        OutputDeclaration(
            key=str(declared["key"]),
            kind="directory",
            path=str(declared["path"]),
            required=not declared.get("optional", False),
        )
        for declared in (task_spec.get("outputs") or [])
    ]
    steps = [
        StepSpec(
            name=step["name"],
            callable_ref=CallableRef(
                kind="python_callable",
                module=step["package"],
                attribute=step["method"],
            ),
            parameters=step.get("parameters") or {},
            retain=step.get("retain") or [],
        )
        for step in (task_spec.get("steps") or [])
    ]

    return TaskSpec(
        task_id=str(task_id),
        run_id=str(run_id),
        attempt=attempt,
        stage_key=stage_key,
        task_key=task_key,
        steps=steps,
        inputs=inputs,
        outputs=outputs,
        environment=environment or {},
        limits=limits,
    )


def execute_task(
    session: Session,
    *,
    task_id: uuid.UUID,
    run_id: uuid.UUID,
    task_spec: dict[str, Any],
    stage_key: str,
    task_key: str,
    attempt: int,
    workspace: Workspace,
    adapter: DockerAdapter,
    limits: ResourceLimits,
    image_ref: str,
    worker_id: str,
    stop: StopSignal | None = None,
    store: PosixArtifactStore | None = None,
    log_max_bytes: int = 32 * 1024 * 1024,
    log_retention_days: int = 365,
) -> TaskOutcome:
    """Run every step of a task, then decide whether it succeeded."""
    log = LogTarget(
        run_id=run_id,
        task_key=task_key,
        attempt=attempt,
        path=workspace.logs / f"attempt-{attempt}.log",
        store=store,
        max_bytes=log_max_bytes,
        retention_days=log_retention_days,
    )
    attempt_id = session.execute(
        text(
            "INSERT INTO run_task_attempts "
            "(task_id, attempt_number, worker_id, image_ref, status) "
            "VALUES (:t, :n, :w, :i, 'running') RETURNING id"
        ),
        {"t": task_id, "n": attempt, "w": worker_id, "i": image_ref},
    ).scalar_one()

    if not (task_spec.get("steps") or []):
        return _record(
            session,
            attempt_id=attempt_id,
            task_id=task_id,
            worker_id=worker_id,
            attempt=attempt,
            log=log,
            status=TaskStatus.FAILED,
            attempt_status=AttemptStatus.FAILED,
            reason="The task has no steps to run.",
            exit_code=None,
            outputs=[],
        )

    if store is not None:
        # Uploaded inputs are put in the workspace here, not at submission: the
        # workspace belongs to the worker, and a run may sit in the queue for a
        # long time before any host needs the bytes. Hardlinked, so a
        # forty-gigabyte input is not copied once per run, and idempotent, so
        # every task and every retry of this run finds it already there.
        try:
            stage_inputs(
                staged_inputs_for_run(session, run_id),
                session=session,
                root=workspace.root,
                store=store,
            )
        except UploadRejected as error:
            return _record(
                session,
                attempt_id=attempt_id,
                task_id=task_id,
                worker_id=worker_id,
                attempt=attempt,
                log=log,
                status=TaskStatus.FAILED,
                attempt_status=AttemptStatus.FAILED,
                reason=error.message,
                exit_code=None,
                outputs=[],
            )

    spec = build_spec(
        task_id=task_id,
        run_id=run_id,
        attempt=attempt,
        stage_key=stage_key,
        task_key=task_key,
        task_spec=task_spec,
        limits=limits,
    )
    unmounted = adapter.unmounted_inputs(spec)
    if unmounted:
        # Refused before launch. A container that starts and then cannot find
        # its input reports a missing file, which reads like the data is gone
        # rather than like the deployment never exposed the root it lives on.
        return _record(
            session,
            attempt_id=attempt_id,
            task_id=task_id,
            worker_id=worker_id,
            attempt=attempt,
            log=log,
            status=TaskStatus.FAILED,
            attempt_status=AttemptStatus.FAILED,
            reason=(
                "Input is outside every storage root this worker exposes to a "
                f"container: {', '.join(unmounted)}"
            ),
            exit_code=None,
            outputs=[],
        )

    # Named and recorded before launch: a container whose name is not in the
    # database cannot be reconciled if this worker dies mid-task, and it would
    # hold resources admission control believes are free.
    container_name = make_container_name(str(task_id))
    session.execute(
        text("UPDATE run_task_attempts SET container_id = :c WHERE id = :i"),
        {"c": container_name, "i": attempt_id},
    )
    session.commit()

    outcome = adapter.run(
        spec,
        workspace.root,
        log_path=log.path,
        container_name=container_name,
        # The generation this run pinned at submission, not the environment's
        # current one: an install that happened while this task was queued
        # must not change what it imports.
        environment=runtime_mount(session, run_id),
    )

    # Why the container stopped is decided here, before the exit code is read.
    # A cancelled container and a killed-because-we-lost-the-lease container
    # both exit non-zero, and Docker cannot tell them apart from an ordinary
    # crash -- only the worker knows, because the worker is what stopped it.
    if stop is not None and stop.lost:
        # Nothing about the task: another worker owns it and may already be
        # running it. Not its status, not its dependants, and above all not
        # its outputs -- these are the losing attempt's.
        return _abandon(session, attempt_id=attempt_id, task_id=task_id, log=log)

    if stop is not None and stop.cancelled:
        return _record(
            session,
            attempt_id=attempt_id,
            task_id=task_id,
            worker_id=worker_id,
            attempt=attempt,
            log=log,
            status=TaskStatus.CANCELLED,
            attempt_status=AttemptStatus.CANCELLED,
            reason="Stopped at the request of whoever cancelled the run.",
            exit_code=outcome.exit_code,
            outputs=[],
        )

    if not outcome.succeeded:
        return _record(
            session,
            attempt_id=attempt_id,
            task_id=task_id,
            worker_id=worker_id,
            attempt=attempt,
            log=log,
            status=TaskStatus.FAILED,
            attempt_status=(AttemptStatus.TIMED_OUT if outcome.timed_out else AttemptStatus.FAILED),
            reason=_reason(outcome),
            exit_code=outcome.exit_code,
            outputs=[],
        )

    # Every step exited cleanly. The task has still only succeeded if it
    # produced what it declared, which the worker checks itself.
    declared = task_spec.get("outputs") or []
    collected, missing = collect_outputs(workspace, declared)
    if missing:
        return _record(
            session,
            attempt_id=attempt_id,
            task_id=task_id,
            worker_id=worker_id,
            attempt=attempt,
            log=log,
            status=TaskStatus.FAILED,
            attempt_status=AttemptStatus.FAILED,
            reason=(
                "The task exited cleanly but did not produce its declared "
                f"output(s): {', '.join(missing)}."
            ),
            exit_code=outcome.exit_code,
            outputs=[],
        )

    # Bytes into the store before the row exists. An artifact row whose bytes
    # are missing is a broken download and a lie in the audit trail; a
    # promoted file with no row is merely disk the janitor reclaims.
    promoted: list[dict[str, Any]] = []
    if store is not None and collected:
        try:
            result = promote_outputs(
                session,
                run_id=run_id,
                task_id=task_id,
                attempt_id=attempt_id,
                task_key=task_key,
                attempt=attempt,
                workspace=workspace,
                collected=collected,
                store=store,
                declared=declared,
            )
        except SQLAlchemyError as error:
            # One task's promotion must not take the worker down with it. It
            # did: a constraint violation raised straight out of here, out of
            # the claim loop, and every other queued task stopped with it —
            # turning one bad task into an idle machine.
            session.rollback()
            logger.exception("promotion failed for task %s", task_key)
            return _record(
                session,
                attempt_id=attempt_id,
                task_id=task_id,
                worker_id=worker_id,
                attempt=attempt,
                status=TaskStatus.FAILED,
                attempt_status=AttemptStatus.FAILED,
                reason=f"The task produced its outputs but they could not be recorded: {error}",
                exit_code=outcome.exit_code,
                outputs=[],
            )
        promoted = [
            {
                "artifact_id": str(artifact.artifact_id),
                "key": artifact.key,
                "storage_key": artifact.storage_key,
                "size_bytes": artifact.size_bytes,
            }
            for artifact in result.artifacts
        ]

    return _record(
        session,
        attempt_id=attempt_id,
        task_id=task_id,
        worker_id=worker_id,
        attempt=attempt,
        log=log,
        status=TaskStatus.SUCCEEDED,
        attempt_status=AttemptStatus.SUCCEEDED,
        reason=None,
        exit_code=outcome.exit_code,
        promoted=promoted,
        outputs=[
            {
                "key": output.key,
                "path": output.relative_path,
                "size_bytes": output.size_bytes,
                "checksum_sha256": output.checksum_sha256,
                "is_directory": output.is_directory,
            }
            for output in collected
        ],
    )


def _reason(outcome: ExecutionOutcome) -> str:
    if outcome.timed_out:
        return "The task exceeded its wall-time limit and was stopped."
    if outcome.contract_violation:
        violation = _error_message(outcome) or "the image and the platform disagree"
        return f"Task contract violation: {violation}"
    reported = _error_message(outcome)
    if reported:
        return reported
    return f"The task container exited with code {outcome.exit_code}."


def _error_message(outcome: ExecutionOutcome) -> str | None:
    if isinstance(outcome.result, dict):
        error = outcome.result.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or "") or None
    return None


@dataclass(frozen=True, slots=True)
class LogTarget:
    """Everything needed to keep what a task printed.

    Carried to `_record` rather than promoted at the call site, because
    `_record` is the one funnel every outcome passes through and a log is
    wanted for all of them -- most of all the failures.
    """

    run_id: uuid.UUID
    task_key: str
    attempt: int
    path: Path
    store: PosixArtifactStore | None
    max_bytes: int
    retention_days: int


def _keep_log(
    session: Session, target: LogTarget | None, attempt_id: uuid.UUID, task_id: uuid.UUID
) -> None:
    """Promote the log, and never let that be the reason a task failed.

    The opposite call from the artifact read audit, and for a reason: losing a
    log is bad, and losing a run's recorded outcome because the log could not
    be stored is worse. A failure here is logged and swallowed.
    """
    if target is None or target.store is None:
        return
    try:
        with session.begin_nested():
            promote_log(
                session,
                run_id=target.run_id,
                task_id=task_id,
                attempt_id=attempt_id,
                task_key=target.task_key,
                attempt=target.attempt,
                log_path=target.path,
                store=target.store,
                max_bytes=target.max_bytes,
                retention_days=target.retention_days,
            )
    except (SQLAlchemyError, OSError):
        logger.exception("could not keep the log for attempt %s", attempt_id)


def _record(
    session: Session,
    *,
    attempt_id: uuid.UUID,
    task_id: uuid.UUID,
    worker_id: str,
    attempt: int,
    status: str,
    attempt_status: str,
    reason: str | None,
    exit_code: int | None,
    outputs: list[dict[str, Any]],
    promoted: list[dict[str, Any]] | None = None,
    log: LogTarget | None = None,
) -> TaskOutcome:
    """Write the verdict, but only while this worker is still the owner.

    The task update is a compare-and-set, not a write by id. A worker can be
    finishing a container at the very moment the reaper decides its lease
    expired and hands the task to somebody else; without the guard, the old
    worker's verdict lands on the new worker's task, clears the new lease, and
    can mark terminal a task whose replacement container is still running.

    ``attempt_count`` is part of the condition as well as ``claimed_by``: the
    same worker can legitimately re-claim a task it lost, and then it is a
    different attempt, with different outputs.
    """
    _keep_log(session, log, attempt_id, task_id)
    # The attempt row is this worker's own and is always safe to close: it is
    # a record of what this container did, which is true regardless of who
    # owns the task now.
    session.execute(
        text(
            "UPDATE run_task_attempts SET status = :s, exit_code = :c, "
            "finished_at = now(), result = :r WHERE id = :i"
        ),
        {
            "s": attempt_status,
            "c": exit_code,
            "r": _as_json({"reason": reason, "outputs": outputs, "artifacts": promoted or []}),
            "i": attempt_id,
        },
    )
    # RETURNING rather than a row count: the typed result of a textual UPDATE
    # does not carry one, and "which row did I actually change" is the
    # question being asked anyway.
    claimed = session.execute(
        text(
            "UPDATE run_tasks SET status = :s, status_reason = :reason, "
            "finished_at = now(), claimed_by = NULL, lease_expires_at = NULL, "
            "updated_at = now() "
            "WHERE id = :i AND claimed_by = :w AND attempt_count = :n "
            "  AND status IN ('claimed', 'running') "
            "RETURNING id"
        ),
        {"s": status, "reason": reason, "i": task_id, "w": worker_id, "n": attempt},
    ).scalar_one_or_none()
    if claimed is None:
        logger.warning(
            "task no longer owned at finalisation; verdict discarded",
            extra={"task_id": task_id, "worker_id": worker_id},
        )
        return TaskOutcome(
            task_id=task_id,
            status=AttemptStatus.LOST,
            attempt_status=attempt_status,
            reason=reason,
            exit_code=exit_code,
            outputs=outputs,
            artifacts=promoted or [],
            owned=False,
        )
    return TaskOutcome(
        task_id=task_id,
        status=status,
        attempt_status=attempt_status,
        reason=reason,
        exit_code=exit_code,
        outputs=outputs,
        artifacts=promoted or [],
    )


def _abandon(
    session: Session,
    *,
    attempt_id: uuid.UUID,
    task_id: uuid.UUID,
    log: LogTarget | None,
) -> TaskOutcome:
    """Close this attempt and say nothing about the task.

    The lease was lost: the reaper has requeued the task and another worker
    may already be running it. The attempt row is still this worker's to
    close -- it is what this container did -- and the log is still worth
    keeping, because an attempt that was interrupted is often the one somebody
    needs to read.
    """
    _keep_log(session, log, attempt_id, task_id)
    session.execute(
        text(
            "UPDATE run_task_attempts SET status = :s, finished_at = now(), result = :r "
            "WHERE id = :i"
        ),
        {
            "s": AttemptStatus.LOST,
            "r": _as_json({"reason": "The lease was lost while this attempt was running."}),
            "i": attempt_id,
        },
    )
    return TaskOutcome(
        task_id=task_id,
        status=AttemptStatus.LOST,
        attempt_status=AttemptStatus.LOST,
        reason="The lease was lost while this attempt was running.",
        exit_code=None,
        outputs=[],
        artifacts=[],
        owned=False,
    )


def _as_json(payload: dict[str, Any]) -> str:
    import json

    return json.dumps(payload, default=str)


def reconcile_orphans(adapter: DockerAdapter, session: Session) -> list[str]:
    """Stop containers this platform started that no running task owns.

    Called on worker startup. A container still running after the worker that
    launched it has gone holds CPU and memory that admission control believes
    are free, so a nonzero steady-state count is a bug worth alerting on.
    """
    live = adapter.orphans()
    if not live:
        return []
    running = {
        str(row[0])
        for row in session.execute(
            text(
                "SELECT container_id FROM run_task_attempts "
                "WHERE status = 'running' AND container_id IS NOT NULL"
            )
        ).all()
    }
    stopped: list[str] = []
    for name in live:
        if name not in running:
            adapter.stop(name, grace_seconds=5)
            stopped.append(name)
    return stopped


def workspace_for(root: Path | str, run_id: uuid.UUID) -> Workspace:
    """The workspace a run's tasks share."""
    from app.infrastructure.workspace import create_workspace

    return create_workspace(root, run_id)
