"""Executing one claimed task, and recording what happened.

Sits between the claiming logic and the container adapter. Its job is the part
that is easy to get wrong: deciding whether a task actually succeeded, and
making sure the database says so exactly once.

The rule that matters: **the worker verifies declared outputs itself.** A task
reporting success while failing to produce what it declared has failed. Only a
stat of the workspace settles that, and the task's own report is advisory.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.application.artifacts import promote_outputs
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

    @property
    def succeeded(self) -> bool:
        return self.status == TaskStatus.SUCCEEDED


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
    inputs = [
        InputBinding(
            key=key,
            kind="file" if isinstance(value, str) else "value",
            path=value.lstrip("/") if isinstance(value, str) else None,
            value=None if isinstance(value, str) else value,
        )
        for key, value in (task_spec.get("inputs") or {}).items()
    ]
    outputs = [
        OutputDeclaration(
            key=str(declared["key"]),
            kind="directory",
            path=str(declared["path"]).lstrip("/"),
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
    store: PosixArtifactStore | None = None,
) -> TaskOutcome:
    """Run every step of a task, then decide whether it succeeded."""
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
            status=TaskStatus.FAILED,
            attempt_status=AttemptStatus.FAILED,
            reason="The task has no steps to run.",
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
    # Named and recorded before launch: a container whose name is not in the
    # database cannot be reconciled if this worker dies mid-task, and it would
    # hold resources admission control believes are free.
    container_name = make_container_name(str(task_id))
    session.execute(
        text("UPDATE run_task_attempts SET container_id = :c WHERE id = :i"),
        {"c": container_name, "i": attempt_id},
    )
    session.commit()

    log_path = workspace.logs / f"attempt-{attempt}.log"
    outcome = adapter.run(spec, workspace.root, log_path=log_path, container_name=container_name)

    if not outcome.succeeded:
        return _record(
            session,
            attempt_id=attempt_id,
            task_id=task_id,
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


def _record(
    session: Session,
    *,
    attempt_id: uuid.UUID,
    task_id: uuid.UUID,
    status: str,
    attempt_status: str,
    reason: str | None,
    exit_code: int | None,
    outputs: list[dict[str, Any]],
    promoted: list[dict[str, Any]] | None = None,
) -> TaskOutcome:
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
    session.execute(
        text(
            "UPDATE run_tasks SET status = :s, status_reason = :reason, "
            "finished_at = now(), claimed_by = NULL, lease_expires_at = NULL, "
            "updated_at = now() WHERE id = :i"
        ),
        {"s": status, "reason": reason, "i": task_id},
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
