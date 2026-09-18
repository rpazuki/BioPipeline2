"""Putting a run's outputs where the lab actually keeps its data.

`_plan_deliveries` has been writing `pending` rows since promotion was
written, and nothing has ever acted on one. This is what acts on them: it
copies a verified artifact into an attested, writable shared root and records
where it went.

Why it is not part of finishing a task. **A delivery can fail after the run has
already succeeded** — the share is unmounted, the disk is full, somebody
changed the permissions — and the run cannot be un-succeeded for it. So
delivery gets its own status, its own attempt count and its own retry, and a
researcher sees "the run worked and the copy did not" rather than a green run
and an empty folder.

Four rules.

**Copy, never link.** Promotion hardlinks because the artifact store is the
platform's own volume; institutional storage is somebody else's, usually on a
different mount, and a hardlink there would tie the lab's copy to the
platform's retention.

**Write to a temporary name and rename.** A researcher watching the share must
never open a file that is still arriving. The rename is atomic within a
filesystem, and the temporary name carries the attempt number so two attempts
cannot write to the same scratch path.

**Never overwrite.** If something is already at the target, a delivery either
recognises it as its own previous attempt — same size, same checksum — or
fails. Silently replacing a file on institutional storage is the one outcome
worth more than any amount of retrying.

**Configuration failures do not retry.** A root that was never attested, or has
been withdrawn, or is not writable, will not become any of those by being tried
again in a minute; that is an administrator's problem and the message says so.
A root that is merely *missing* — an unmounted share — is transient, and is
retried.
"""

from __future__ import annotations

import shutil
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.domain.enums import DeliveryMode, DeliveryStatus
from app.domain.errors import ValidationFailed
from app.infrastructure.artifacts import PosixArtifactStore, safe_segment
from app.infrastructure.db.models import (
    Artifact,
    Pipeline,
    PipelineRevision,
    Run,
    RunDelivery,
    RunTask,
    SharedStorageRoot,
)
from app.infrastructure.workspace import checksum

# The platform writes under a directory of its own making, never at the root
# of somebody's share, so a delivery can never land on top of a file the lab
# put there itself.
LAYOUT = "{pipeline}/{date}/run-{run}/{task}"


class DeliveryRefused(ValidationFailed):
    code = "delivery.refused"


@dataclass(frozen=True, slots=True)
class DeliveryReport:
    """What one attempt at one delivery did."""

    delivery_id: uuid.UUID
    delivered: bool = False
    skipped: bool = False
    """Claimed by another pass, or no longer due."""
    failed: bool = False
    """Permanently. A retryable failure is neither delivered nor failed."""
    message: str | None = None
    target_path: str | None = None

    @property
    def changed(self) -> bool:
        return self.delivered or self.failed or self.message is not None


def due_delivery_ids(session: Session, *, now: datetime, limit: int = 20) -> list[uuid.UUID]:
    """Deliveries waiting to be attempted, oldest first.

    Unlocked: the claim happens per delivery, in its own transaction, so a
    forty-gigabyte copy does not hold a row lock over every other delivery
    behind it.
    """
    rows = session.execute(
        text(
            """
            SELECT id FROM run_deliveries
            WHERE status = 'pending'
              AND mode = 'shared'
              AND artifact_id IS NOT NULL
              AND (next_attempt_at IS NULL OR next_attempt_at <= :now)
            ORDER BY created_at
            LIMIT :limit
            """
        ),
        {"now": now, "limit": limit},
    ).scalars()
    return list(rows)


def _claim(session: Session, delivery_id: uuid.UUID, *, now: datetime, lease_seconds: int):
    """Take a delivery for this pass, or return None if somebody else has it.

    The lease is `next_attempt_at`, pushed into the future and committed
    *before* the copy starts. Holding the row lock for the length of the copy
    would be the same mistake as holding a transaction open across an upload:
    minutes of idle-in-transaction for something that is not a database
    problem. A worker that dies mid-copy leaves the lease to expire, and the
    next pass picks the delivery up.
    """
    delivery = session.execute(
        select(RunDelivery).where(RunDelivery.id == delivery_id).with_for_update(skip_locked=True)
    ).scalar_one_or_none()
    if delivery is None:
        return None
    if delivery.status != DeliveryStatus.PENDING.value:
        return None
    if delivery.mode != DeliveryMode.SHARED.value:
        return None
    if delivery.next_attempt_at is not None and delivery.next_attempt_at > now:
        return None
    delivery.attempts += 1
    delivery.next_attempt_at = now + timedelta(seconds=lease_seconds)
    session.flush()
    return delivery


def destination_for(
    session: Session, delivery: RunDelivery, root: SharedStorageRoot, artifact: Artifact
) -> Path:
    """Where this artifact goes inside the root.

    Named so a researcher can find it without being told: the pipeline, the
    date, the run as the interface shows it, and the task — which is what
    distinguishes six deliveries of a field called `results` in a fanned-out
    run.
    """
    run = session.get(Run, delivery.run_id)
    pipeline = "pipeline"
    if run is not None:
        revision = session.get(PipelineRevision, run.pipeline_revision_id)
        if revision is not None:
            owner = session.get(Pipeline, revision.pipeline_id)
            if owner is not None:
                pipeline = owner.slug
    task_key = delivery.field_key
    if delivery.task_id is not None:
        task = session.get(RunTask, delivery.task_id)
        if task is not None:
            task_key = task.task_key
    created = (run.created_at if run is not None else datetime.now(UTC)).astimezone(UTC)
    relative = LAYOUT.format(
        pipeline=safe_segment(pipeline),
        date=created.strftime("%Y-%m-%d"),
        run=str(delivery.run_id)[:8],
        task=safe_segment(task_key),
    )
    return Path(root.root_path) / relative / artifact.filename


def _usable(root: SharedStorageRoot | None, root_id: str | None) -> str | None:
    """Why this root cannot be written to, or None if it can.

    Split from the transient checks on purpose: everything here is an
    administrator's decision, and retrying it changes nothing.
    """
    if root_id is None:
        return (
            "This output is declared for shared storage but names no root. "
            "The pipeline has to say which root before it can be delivered."
        )
    if root is None:
        return f"Storage root '{root_id}' does not exist."
    if root.revoked_at is not None:
        return f"Storage root '{root_id}' has been withdrawn."
    if not root.writable:
        return (
            f"Storage root '{root_id}' is registered read-only. An administrator "
            "has to reinstate it as writable before outputs can be delivered there."
        )
    if root.attested_at is None:
        return f"Storage root '{root_id}' has no attestation, so the platform will not write to it."
    return None


def _same_bytes(source: Path, target: Path) -> bool:
    """Whether what is already there is what this delivery would write.

    Cheap comparison first: two files of different sizes cannot be the same,
    and that is the common case for a genuine collision.
    """
    if source.is_dir() or target.is_dir():
        return source.is_dir() and target.is_dir()
    if source.stat().st_size != target.stat().st_size:
        return False
    return checksum(source) == checksum(target)


def _place(source: Path, target: Path, *, attempt: int) -> None:
    """Copy into place through a temporary name.

    The temporary carries the attempt number, so a retry that overlaps a lease
    that has not quite expired cannot write into the same scratch path as the
    attempt it is replacing.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(f".{target.name}.incoming-{attempt}")
    _discard(staging)
    try:
        if source.is_dir():
            shutil.copytree(source, staging)
        else:
            shutil.copy2(source, staging)
        staging.replace(target)
    except OSError:
        # A copy that ran out of disk halfway has already written most of a
        # forty-gigabyte file onto somebody else's share, and nothing else
        # would ever remove it: the next attempt writes under a new name, and
        # the platform does not sweep storage it does not own.
        _discard(staging)
        raise


def _discard(path: Path) -> None:
    """Remove a partial copy, and never fail for it.

    Best effort on purpose. If the share has gone away, the tidying cannot
    happen and the delivery's own failure is the thing worth reporting.
    """
    try:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.exists():
            path.unlink()
    except OSError:
        pass


def deliver_one(
    session: Session,
    delivery_id: uuid.UUID,
    *,
    store: PosixArtifactStore,
    now: datetime | None = None,
    lease_seconds: int = 2 * 3600,
    max_attempts: int = 5,
    retry_seconds: int = 60,
) -> DeliveryReport:
    """Attempt one delivery. Never raises for an ordinary failure.

    The caller commits. A raise here would roll back the attempt count with
    the failure that caused it, which is how a broken delivery retries for
    ever without the count ever moving.
    """
    now = now or datetime.now(UTC)
    delivery = _claim(session, delivery_id, now=now, lease_seconds=lease_seconds)
    if delivery is None:
        return DeliveryReport(delivery_id=delivery_id, skipped=True)

    root = (
        session.get(SharedStorageRoot, delivery.target_root_id) if delivery.target_root_id else None
    )
    refusal = _usable(root, delivery.target_root_id)
    if refusal is not None:
        return _fail(session, delivery, refusal, permanent=True)

    assert root is not None  # `_usable` returned None, so there is one
    artifact = session.get(Artifact, delivery.artifact_id) if delivery.artifact_id else None
    if artifact is None or artifact.purged_at is not None:
        return _fail(
            session,
            delivery,
            "The output this delivery names is no longer in the artifact store.",
            permanent=True,
        )

    source = store.path_for(artifact.storage_key)
    if not source.exists():
        return _fail(
            session,
            delivery,
            f"The bytes of '{artifact.filename}' are missing from the artifact store.",
            permanent=True,
        )

    target = destination_for(session, delivery, root, artifact)
    if not Path(root.root_path).is_dir():
        # Transient, and the one failure here that is worth retrying: a share
        # that is not mounted right now is usually mounted again later.
        return _fail(
            session,
            delivery,
            f"Storage root '{root.id}' is not mounted on the machine doing the delivery.",
            permanent=False,
            retry_seconds=retry_seconds,
            max_attempts=max_attempts,
        )

    try:
        if target.exists():
            if not _same_bytes(source, target):
                return _fail(
                    session,
                    delivery,
                    f"Something else is already at {target}. The platform will not "
                    "overwrite a file on shared storage; move it and retry.",
                    permanent=True,
                )
        else:
            _place(source, target, attempt=delivery.attempts)
    except OSError as error:
        return _fail(
            session,
            delivery,
            f"Copying to {target} failed: {error.strerror or error}.",
            permanent=False,
            retry_seconds=retry_seconds,
            max_attempts=max_attempts,
        )

    delivery.status = DeliveryStatus.DELIVERED
    delivery.target_path = str(target)
    delivery.delivered_at = now
    delivery.next_attempt_at = None
    delivery.message = None
    session.flush()
    return DeliveryReport(delivery_id=delivery.id, delivered=True, target_path=str(target))


def _fail(
    session: Session,
    delivery: RunDelivery,
    message: str,
    *,
    permanent: bool,
    retry_seconds: int = 60,
    max_attempts: int = 5,
) -> DeliveryReport:
    """Record why an attempt did not deliver, and whether to try again.

    A retryable failure keeps the delivery `pending` and says what went wrong
    in the meantime, so "waiting to be delivered" and "failing every few
    minutes" are not the same row to look at.
    """
    exhausted = delivery.attempts >= max_attempts
    if permanent or exhausted:
        delivery.status = DeliveryStatus.FAILED
        delivery.next_attempt_at = None
        delivery.message = (
            message
            if permanent
            else f"{message} Given up after {delivery.attempts} attempts; retry when it is fixed."
        )
        session.flush()
        return DeliveryReport(delivery_id=delivery.id, failed=True, message=delivery.message)

    backoff = retry_seconds * (2 ** (delivery.attempts - 1))
    delivery.next_attempt_at = datetime.now(UTC) + timedelta(seconds=backoff)
    delivery.message = f"Attempt {delivery.attempts} did not succeed: {message}"
    session.flush()
    return DeliveryReport(delivery_id=delivery.id, message=delivery.message)


def retry_delivery(session: Session, delivery: RunDelivery) -> RunDelivery:
    """Put a failed delivery back in the queue.

    For the case the message describes: an administrator has mounted the
    share, or made the root writable, and the delivery should be attempted
    again now rather than at the end of a backoff nobody can see.
    """
    if delivery.mode != DeliveryMode.SHARED.value:
        raise DeliveryRefused("Only a delivery to shared storage can be retried.")
    if delivery.status == DeliveryStatus.DELIVERED.value:
        raise DeliveryRefused("This output has already been delivered.")
    delivery.status = DeliveryStatus.PENDING
    delivery.next_attempt_at = None
    delivery.message = "Queued for another attempt."
    session.flush()
    return delivery
