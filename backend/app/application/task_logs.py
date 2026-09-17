"""What a task printed, read back.

The first question about a failed task is what it said before it stopped, and
until now the answer was on a worker's disk in a directory nobody could reach,
waiting for retention to delete it.

Two sources, and which one is used says something the reader needs anyway:

* **The artifact**, once the attempt has finished. Durable, checksummed, and
  outliving the outputs.
* **The workspace file**, while the attempt is still running. The same file the
  container is writing into, read from the API process — which shares a
  filesystem with the workers in this deployment, the same assumption storage
  root registration makes.

A log is read as a **tail**. An aligner can print for hours, and the end is
where the error is; the whole thing is an ordinary artifact download for
anybody who wants it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.infrastructure.artifacts import PosixArtifactStore

# Enough to hold a stack trace and the tool output around it, small enough
# that a browser renders it without thinking about it.
DEFAULT_TAIL_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class AttemptView:
    """One attempt at a task, and whether its log can be read."""

    id: uuid.UUID
    attempt_number: int
    status: str
    exit_code: int | None
    worker_id: str | None
    image_ref: str
    started_at: datetime
    finished_at: datetime | None
    log_artifact_id: uuid.UUID | None

    @property
    def finished(self) -> bool:
        return self.finished_at is not None


@dataclass(frozen=True, slots=True)
class LogView:
    """A log, or the reason there is not one yet."""

    attempt_number: int
    text: str
    bytes_read: int
    bytes_total: int
    truncated: bool
    """True when only the tail is shown; the artifact has the rest."""

    live: bool
    """True when this came from a running task's workspace file.

    Worth saying: the same request a minute later returns more, and a client
    that is polling should keep polling.
    """

    artifact_id: uuid.UUID | None
    message: str | None = None


def attempts_for_task(session: Session, task_id: uuid.UUID) -> list[AttemptView]:
    """Every attempt at a task, newest first.

    A retry produces a second attempt with its own log, and "which attempt was
    this" is unanswerable without them.
    """
    rows = session.execute(
        text(
            "SELECT id, attempt_number, status, exit_code, worker_id, image_ref, "
            "       started_at, finished_at, log_artifact_id "
            "FROM run_task_attempts WHERE task_id = :t ORDER BY attempt_number DESC"
        ),
        {"t": task_id},
    ).all()
    return [
        AttemptView(
            id=row.id,
            attempt_number=row.attempt_number,
            status=row.status,
            exit_code=row.exit_code,
            worker_id=row.worker_id,
            image_ref=row.image_ref,
            started_at=row.started_at,
            finished_at=row.finished_at,
            log_artifact_id=row.log_artifact_id,
        )
        for row in rows
    ]


def _tail(path: Path, tail_bytes: int) -> tuple[str, int, int, bool]:
    """The last ``tail_bytes`` of a file, decoded leniently.

    Never read whole: a log can be gigabytes, and this runs in the process
    that also answers every other request. Lenient decoding because a tail
    can start mid-character, and a mojibake byte at the front is a much
    smaller problem than refusing to show a stack trace.
    """
    total = path.stat().st_size
    start = max(0, total - tail_bytes)
    with path.open("rb") as handle:
        handle.seek(start)
        chunk = handle.read()
    return chunk.decode("utf-8", errors="replace"), len(chunk), total, start > 0


def read_log(
    session: Session,
    *,
    task_id: uuid.UUID,
    run_id: uuid.UUID,
    store: PosixArtifactStore,
    workspace_root: Path,
    attempt_number: int | None = None,
    tail_bytes: int = DEFAULT_TAIL_BYTES,
) -> LogView | None:
    """The log of one attempt, latest by default.

    ``None`` when the task has never been attempted -- which is different from
    an attempt that produced no output, and the caller renders them
    differently.
    """
    attempts = attempts_for_task(session, task_id)
    if not attempts:
        return None
    if attempt_number is None:
        chosen = attempts[0]
    else:
        found = [a for a in attempts if a.attempt_number == attempt_number]
        if not found:
            return None
        chosen = found[0]

    def empty(message: str) -> LogView:
        return LogView(
            attempt_number=chosen.attempt_number,
            text="",
            bytes_read=0,
            bytes_total=0,
            truncated=False,
            live=not chosen.finished,
            artifact_id=chosen.log_artifact_id,
            message=message,
        )

    if chosen.log_artifact_id is not None:
        storage_key = session.execute(
            text("SELECT storage_key FROM artifacts WHERE id = :a AND purged_at IS NULL"),
            {"a": chosen.log_artifact_id},
        ).scalar_one_or_none()
        if storage_key is None:
            return empty("This log has been removed; its retention expired.")
        path = store.path_for(storage_key)
        if not path.is_file():
            return empty("The bytes of this log are missing from the store.")
        body, read, total, truncated = _tail(path, tail_bytes)
        return LogView(
            attempt_number=chosen.attempt_number,
            text=body,
            bytes_read=read,
            bytes_total=total,
            truncated=truncated,
            live=False,
            artifact_id=chosen.log_artifact_id,
        )

    # No artifact: either still running, or it finished without one — which a
    # task that printed nothing does, and so does one whose log could not be
    # stored.
    live_path = workspace_root / str(run_id) / "logs" / f"attempt-{chosen.attempt_number}.log"
    if not live_path.is_file():
        return empty(
            "This attempt has not printed anything yet."
            if not chosen.finished
            else "This attempt produced no output."
        )
    body, read, total, truncated = _tail(live_path, tail_bytes)
    return LogView(
        attempt_number=chosen.attempt_number,
        text=body,
        bytes_read=read,
        bytes_total=total,
        truncated=truncated,
        live=not chosen.finished,
        artifact_id=None,
    )
