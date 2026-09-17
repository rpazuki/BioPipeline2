"""Promoting a task's outputs into durable artifacts.

The moment a run's results stop being scratch. Before promotion the bytes live
in a workspace the janitor may delete at any time; after it they are rows with
checksums, retention, and a delivery plan.

Ordering matters and is easy to get backwards: **bytes first, row second**. An
artifact row whose bytes are missing is a broken download and a lie in the
audit trail. A promoted file with no row is merely disk the janitor will
reclaim. So the store write happens first, and the row only exists once the
bytes do.
"""

from __future__ import annotations

import shutil
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.domain.enums import ArtifactKind, DeliveryMode, DeliveryStatus, RetentionClass
from app.domain.errors import DomainError
from app.infrastructure.artifacts import PosixArtifactStore
from app.infrastructure.db.models import Artifact, ArtifactAccessEvent, Run, RunDelivery
from app.infrastructure.workspace import CollectedOutput, Workspace


@dataclass(frozen=True, slots=True)
class PromotedArtifact:
    artifact_id: uuid.UUID
    key: str
    storage_key: str
    size_bytes: int
    is_directory: bool


@dataclass(frozen=True, slots=True)
class PromotionResult:
    artifacts: list[PromotedArtifact]
    deliveries: list[uuid.UUID]
    manifests: list[uuid.UUID]

    @property
    def total_bytes(self) -> int:
        return sum(artifact.size_bytes for artifact in self.artifacts)


def promote_outputs(
    session: Session,
    *,
    run_id: uuid.UUID,
    task_id: uuid.UUID,
    attempt_id: uuid.UUID,
    task_key: str,
    attempt: int,
    workspace: Workspace,
    collected: list[CollectedOutput],
    store: PosixArtifactStore,
    declared: list[dict[str, Any]] | None = None,
    default_retention_days: int = 90,
    manifest_threshold_bytes: int = 2 * 1024**3,
) -> PromotionResult:
    """Move a task's verified outputs into the artifact store.

    ``collected`` comes from the worker's own stat of the workspace, not from
    what the task claimed, so nothing is promoted that does not exist.
    """
    run = session.get(Run, run_id)
    if run is None:
        raise ValueError(f"Run {run_id} does not exist.")

    policy = {entry["key"]: entry for entry in (declared or [])}
    promoted: list[PromotedArtifact] = []
    deliveries: list[uuid.UUID] = []
    manifests: list[uuid.UUID] = []

    for output in collected:
        source = workspace.resolve(output.relative_path)
        storage_key = store.key_for(
            run_id=run_id, task_key=task_key, attempt=attempt, output_key=output.key
        )
        stored = store.put(source, storage_key)

        entry = policy.get(output.key, {})
        retention_days = entry.get("retention_days") or default_retention_days
        artifact = Artifact(
            project_id=run.project_id,
            run_id=run_id,
            task_id=task_id,
            task_attempt_id=attempt_id,
            owner_id=run.requested_by,
            kind=ArtifactKind.TASK_OUTPUT,
            storage_backend=store.backend,
            storage_key=stored.storage_key,
            filename=source.name,
            size_bytes=stored.size_bytes,
            checksum_sha256=stored.checksum_sha256,
            retention_class=RetentionClass.STANDARD,
            expires_at=datetime.now(UTC) + timedelta(days=retention_days),
        )
        session.add(artifact)
        session.flush()
        promoted.append(
            PromotedArtifact(
                artifact_id=artifact.id,
                key=output.key,
                storage_key=stored.storage_key,
                size_bytes=stored.size_bytes,
                is_directory=stored.is_directory,
            )
        )

        # A directory gets a manifest rather than an archive. Packaging tens
        # of gigabytes into one file is slow and rarely what anyone wants; a
        # manifest lets the UI offer per-file download immediately.
        if stored.is_directory and stored.size_bytes >= 0:
            manifest_id = _write_manifest(
                session,
                run=run,
                artifact=artifact,
                store=store,
                oversized=stored.size_bytes > manifest_threshold_bytes,
            )
            manifests.append(manifest_id)

        deliveries.extend(
            _plan_deliveries(
                session,
                run_id=run_id,
                task_id=task_id,
                output_key=output.key,
                artifact_id=artifact.id,
                modes=entry.get("delivery") or [DeliveryMode.DOWNLOAD.value],
                shared_root=entry.get("shared_root"),
            )
        )

    session.flush()
    return PromotionResult(artifacts=promoted, deliveries=deliveries, manifests=manifests)


def _write_manifest(
    session: Session,
    *,
    run: Run,
    artifact: Artifact,
    store: PosixArtifactStore,
    oversized: bool,
) -> uuid.UUID:
    """Record a directory artifact's contents as its own artifact."""
    entries = store.manifest(artifact.storage_key)
    payload = {
        "artifact_id": str(artifact.id),
        "entry_count": len(entries),
        "total_bytes": sum(entry.size_bytes for entry in entries),
        "packaged": not oversized,
        "entries": [
            {
                "path": entry.relative_path,
                "size_bytes": entry.size_bytes,
                "checksum_sha256": entry.checksum_sha256,
            }
            for entry in entries
        ],
    }
    manifest_key = f"{artifact.storage_key}.manifest.json"
    path = store.path_for(manifest_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    import json

    path.write_text(json.dumps(payload, indent=2))

    manifest = Artifact(
        project_id=run.project_id,
        run_id=run.id,
        task_id=artifact.task_id,
        task_attempt_id=artifact.task_attempt_id,
        owner_id=run.requested_by,
        kind=ArtifactKind.MANIFEST,
        storage_backend=store.backend,
        storage_key=manifest_key,
        filename=f"{artifact.filename}.manifest.json",
        content_type="application/json",
        size_bytes=path.stat().st_size,
        retention_class=RetentionClass.STANDARD,
        expires_at=artifact.expires_at,
    )
    session.add(manifest)
    session.flush()
    return manifest.id


def _plan_deliveries(
    session: Session,
    *,
    run_id: uuid.UUID,
    output_key: str,
    artifact_id: uuid.UUID,
    modes: list[str],
    task_id: uuid.UUID | None = None,
    shared_root: str | None = None,
) -> list[uuid.UUID]:
    """Record where an output is meant to go.

    Delivery is tracked separately from the artifact because it can fail after
    the run has already succeeded, and a researcher needs to see that rather
    than wonder why a file never appeared on the share.
    """
    created: list[uuid.UUID] = []
    for mode in modes:
        if mode == DeliveryMode.DOWNLOAD.value:
            # Nothing to move: the artifact is retrievable as soon as it
            # exists, so the delivery is complete on creation.
            delivery = RunDelivery(
                run_id=run_id,
                task_id=task_id,
                field_key=output_key,
                mode=DeliveryMode.DOWNLOAD,
                artifact_id=artifact_id,
                status=DeliveryStatus.DELIVERED,
                delivered_at=datetime.now(UTC),
            )
        elif mode == DeliveryMode.SHARED.value:
            # Pending until a delivery pass copies the bytes to the root.
            # The platform writes as a service account (ADR 0013), which is
            # safe only because a root must be attested as group-accessible
            # before it can be exposed at all.
            delivery = RunDelivery(
                run_id=run_id,
                task_id=task_id,
                field_key=output_key,
                mode=DeliveryMode.SHARED,
                artifact_id=artifact_id,
                target_root_id=shared_root,
                status=DeliveryStatus.PENDING,
                message="awaiting delivery to the shared root",
            )
        else:
            continue
        session.add(delivery)
        session.flush()
        created.append(delivery.id)
    return created


def artifacts_for_run(session: Session, run_id: uuid.UUID) -> list[Artifact]:
    """Every live artifact of a run, newest first."""
    return list(
        session.execute(
            select(Artifact)
            .where(Artifact.run_id == run_id, Artifact.deleted_at.is_(None))
            .order_by(Artifact.created_at.desc())
        ).scalars()
    )


# --- retrieval -------------------------------------------------------------


class ArtifactUnavailable(DomainError):
    """The artifact exists in the record but its bytes do not.

    Distinct from "no such artifact" on purpose. A researcher who kept a link
    for three months needs to be told their outputs expired, not that they
    imagined them -- and the run history still says the work succeeded.
    """

    code = "artifact.unavailable"


@dataclass(frozen=True, slots=True)
class DownloadableFile:
    """A file the platform is prepared to hand over, resolved on disk."""

    artifact: Artifact
    path: Path
    filename: str
    size_bytes: int


def artifact_for_download(session: Session, artifact_id: uuid.UUID) -> Artifact | None:
    """The artifact row, live or not. Availability is a separate question."""
    return session.get(Artifact, artifact_id)


def resolve_download(
    artifact: Artifact, store: PosixArtifactStore, *, member: str | None = None
) -> DownloadableFile:
    """Turn an artifact, and optionally a file inside it, into bytes on disk.

    A directory artifact is not served as one download. Packaging a
    multi-gigabyte output tree into an archive is neither fast nor useful, and
    it would be done by the process that also answers every other request --
    so a directory is retrieved a file at a time, against the manifest the
    store already writes.
    """
    if artifact.deleted_at is not None or artifact.purged_at is not None:
        raise ArtifactUnavailable(
            f"'{artifact.filename}' has been removed. Outputs are kept until "
            "their retention expires; the run's record of what happened stays.",
            details={"artifact_id": str(artifact.id)},
        )

    root = store.path_for(artifact.storage_key)
    if member is None:
        if root.is_dir():
            raise ArtifactUnavailable(
                f"'{artifact.filename}' is a directory of results. Ask for the "
                "files it contains rather than the whole tree.",
                details={"artifact_id": str(artifact.id), "is_directory": True},
            )
        if not root.is_file():
            raise ArtifactUnavailable(
                f"The bytes of '{artifact.filename}' are missing from the store.",
                details={"artifact_id": str(artifact.id)},
            )
        return DownloadableFile(
            artifact=artifact,
            path=root,
            filename=artifact.filename,
            size_bytes=root.stat().st_size,
        )

    # A member path comes from a URL, so it is checked against the resolved
    # root rather than trusted for being "relative".
    candidate = (root / member).resolve()
    if not candidate.is_relative_to(root.resolve()) or not candidate.is_file():
        raise ArtifactUnavailable(
            f"'{member}' is not a file in '{artifact.filename}'.",
            details={"artifact_id": str(artifact.id), "member": member},
        )
    return DownloadableFile(
        artifact=artifact,
        path=candidate,
        filename=candidate.name,
        size_bytes=candidate.stat().st_size,
    )


def record_access(
    session: Session,
    *,
    artifact_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    access_type: str,
    bytes_served: int | None = None,
    request_id: str | None = None,
    ip_address: str | None = None,
) -> None:
    """Write down that somebody read an artifact, or was refused one.

    `audit_artifact_reads` has defaulted to true since the settings were
    written, and until there was a download path nothing wrote a row -- a
    setting that claimed something the code did not do. Refusals are recorded
    too: somebody walking artifact ids that are not theirs is exactly what a
    read audit is for.
    """
    session.add(
        ArtifactAccessEvent(
            artifact_id=artifact_id,
            actor_id=actor_id,
            access_type=access_type,
            bytes_served=bytes_served,
            request_id=request_id,
            ip_address=ip_address,
        )
    )
    session.flush()


# --- task logs -------------------------------------------------------------

TRUNCATION_BANNER = (
    "[the platform kept the last {kept} bytes of {total}; "
    "the rest was discarded when this log was stored]\n"
)


def promote_log(
    session: Session,
    *,
    run_id: uuid.UUID,
    task_id: uuid.UUID,
    attempt_id: uuid.UUID,
    task_key: str,
    attempt: int,
    log_path: Path,
    store: PosixArtifactStore,
    max_bytes: int,
    retention_days: int,
) -> uuid.UUID | None:
    """Keep what a task printed, for every outcome.

    Promoted on failure and timeout as much as on success -- more so: a failed
    task whose log is gone tells nobody anything, and the workspace holding it
    is the first thing retention reclaims.

    The **tail** is kept when a log is too big, not the head. A stack trace is
    at the end, and so is whatever the tool said before it stopped.

    Logs outlive outputs by default, because a failure is often diagnosed long
    after the results it did not produce were cleaned up.
    """
    if not log_path.is_file():
        return None
    total = log_path.stat().st_size
    if total == 0:
        return None

    run = session.get(Run, run_id)
    if run is None:
        return None

    source = log_path
    if total > max_bytes:
        source = log_path.with_suffix(".tail.log")
        with log_path.open("rb") as whole, source.open("wb") as tail:
            whole.seek(total - max_bytes)
            tail.write(TRUNCATION_BANNER.format(kept=max_bytes, total=total).encode())
            shutil.copyfileobj(whole, tail)

    storage_key = store.key_for(
        run_id=run_id, task_key=task_key, attempt=attempt, output_key="task-log"
    )
    stored = store.put(source, storage_key)
    artifact = Artifact(
        project_id=run.project_id,
        run_id=run_id,
        task_id=task_id,
        task_attempt_id=attempt_id,
        owner_id=run.requested_by,
        kind=ArtifactKind.TASK_LOG,
        storage_backend=store.backend,
        storage_key=stored.storage_key,
        filename=f"{task_key}-attempt-{attempt}.log",
        content_type="text/plain",
        size_bytes=stored.size_bytes,
        checksum_sha256=stored.checksum_sha256,
        retention_class=RetentionClass.LONG_TERM,
        expires_at=datetime.now(UTC) + timedelta(days=retention_days),
    )
    session.add(artifact)
    session.flush()
    session.execute(
        text("UPDATE run_task_attempts SET log_artifact_id = :a WHERE id = :i"),
        {"a": artifact.id, "i": attempt_id},
    )
    return artifact.id
