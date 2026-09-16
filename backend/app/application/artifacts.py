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

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import ArtifactKind, DeliveryMode, DeliveryStatus, RetentionClass
from app.infrastructure.artifacts import PosixArtifactStore
from app.infrastructure.db.models import Artifact, Run, RunDelivery
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
