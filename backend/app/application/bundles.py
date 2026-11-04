"""Prepare bounded result ZIP files in the delivery service and retain durable progress."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import stat
import uuid
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.application.transfers import result_modes
from app.application.uploads import UploadBusy, exclusive
from app.domain.enums import ArtifactKind, RetentionClass
from app.domain.errors import DomainError, LimitExceeded, ValidationFailed
from app.infrastructure.archives import BUFFER, check_members
from app.infrastructure.artifacts import PosixArtifactStore, safe_segment
from app.infrastructure.db.models import Artifact, ArtifactBundle, Run
from app.settings import Settings

logger = logging.getLogger("biopipeline2.courier.bundles")


def require_delivery(run: Run, mode: str) -> None:
    """Enforce the download choices frozen when this run was submitted."""
    if mode not in result_modes(run.compiled_run_spec):
        raise ValidationFailed(f"This publication does not offer '{mode}' result downloads.")


def create_bundle(
    session: Session,
    run: Run,
    requested_by: uuid.UUID,
    settings: Settings,
    artifact_ids: list[uuid.UUID] | None = None,
) -> ArtifactBundle:
    """Queue or reuse a ZIP request for immutable outputs from a completed run."""
    require_delivery(run, "zip")
    if run.status not in {"succeeded", "failed", "cancelled"}:
        raise ValidationFailed("Wait for the run to finish before preparing its result ZIP.")
    query = select(Artifact).where(
        Artifact.run_id == run.id,
        Artifact.kind == ArtifactKind.TASK_OUTPUT,
        Artifact.deleted_at.is_(None),
        Artifact.purged_at.is_(None),
    )
    if artifact_ids:
        query = query.where(Artifact.id.in_(artifact_ids))
    artifacts = list(session.scalars(query.order_by(Artifact.id)))
    if not artifacts or (artifact_ids and set(artifact_ids) != {item.id for item in artifacts}):
        raise ValidationFailed("Select available outputs belonging to this run.")
    total = sum(artifact.size_bytes for artifact in artifacts)
    if total > settings.output_bundle_max_bytes:
        raise LimitExceeded("These outputs exceed the ZIP size limit. Use individual downloads.")
    ids = [str(artifact.id) for artifact in artifacts]
    key = hashlib.sha256(json.dumps(ids).encode()).hexdigest()
    existing = session.scalar(
        select(ArtifactBundle).where(
            ArtifactBundle.run_id == run.id, ArtifactBundle.request_key == key
        )
    )
    if existing:
        output = session.get(Artifact, existing.artifact_id) if existing.artifact_id else None
        if existing.status == "failed" or (
            existing.status == "ready"
            and (output is None or output.deleted_at is not None or output.purged_at is not None)
        ):
            existing.status = "pending"
            existing.artifact_id = None
            existing.message = None
            existing.completed_bytes = 0
        return existing
    job = ArtifactBundle(
        run_id=run.id,
        requested_by=requested_by,
        request_key=key,
        source_ids=ids,
        total_bytes=total,
        status="pending",
    )
    try:
        with session.begin_nested():
            session.add(job)
            session.flush()
    except IntegrityError:
        return session.scalar(
            select(ArtifactBundle).where(
                ArtifactBundle.run_id == run.id, ArtifactBundle.request_key == key
            )
        )
    return job


def _members(artifacts: list[Artifact], store: PosixArtifactStore, settings: Settings):
    entries: list[tuple[str, Path | None, int]] = []
    total = 0
    for artifact in artifacts:
        root = store.path_for(artifact.storage_key)
        if artifact.deleted_at is not None or artifact.purged_at is not None or not root.exists():
            raise ValidationFailed("An output was removed before the ZIP could be prepared.")
        filename = safe_segment(artifact.filename)
        while len(filename.encode("utf-8")) > 220:
            filename = filename[:-1]
        base = f"{artifact.task_id or 'outputs'}/{str(artifact.id)[:8]}-{filename}"
        paths = [root]
        for index, path in enumerate(paths):
            mode = path.lstat().st_mode
            name = base if path == root else f"{base}/{path.relative_to(root).as_posix()}"
            if stat.S_ISDIR(mode):
                entries.append((name, None, 0))
                with os.scandir(path) as children:
                    for child in children:
                        if len(entries) + len(paths) - index > settings.output_bundle_max_files:
                            raise LimitExceeded("The output ZIP contains too many files.")
                        paths.append(Path(child.path))
            elif stat.S_ISREG(mode):
                size = path.stat().st_size
                total += size
                entries.append((name, path, size))
            else:
                raise ValidationFailed("Output ZIP files cannot contain links or special files.")
            if (
                len(entries) > settings.output_bundle_max_files
                or total > settings.output_bundle_max_bytes
            ):
                raise LimitExceeded("The output ZIP exceeds its file count or size limit.")
    check_members([(name, path is None) for name, path, _ in entries])
    return entries, total


def process_bundle(
    session: Session, bundle_id: uuid.UUID, *, store: PosixArtifactStore, settings: Settings
) -> bool:
    """Prepare one queued ZIP with bounded buffers and a process-wide filesystem lock.

    Progress is committed between chunks. A restarted courier can rebuild an
    interrupted request; temporary bytes are replaced or removed under the lock.
    """
    try:
        with exclusive(store.path_for(f"bundles/locks/{bundle_id}")):
            job = session.get(ArtifactBundle, bundle_id, populate_existing=True)
            if job is None or job.status not in {"pending", "working"}:
                return False
            job.status = "working"
            job.completed_bytes = 0
            job.message = None
            session.commit()
            partial = store.path_for(f"bundles/staging/{bundle_id}.zip.partial")
            partial.parent.mkdir(parents=True, exist_ok=True)
            stored_key = None
            try:
                run = session.get(Run, job.run_id)
                if run is None or run.deleted_at is not None:
                    raise ValidationFailed("The run is no longer available.")
                require_delivery(run, "zip")
                artifacts = [session.get(Artifact, uuid.UUID(value)) for value in job.source_ids]
                if any(
                    item is None or item.run_id != run.id or item.kind != ArtifactKind.TASK_OUTPUT
                    for item in artifacts
                ):
                    raise ValidationFailed("An output is no longer available.")
                entries, total = _members(artifacts, store, settings)
                job.total_bytes = total
                session.commit()
                completed = 0
                checkpoint = 0
                with zipfile.ZipFile(
                    partial, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True
                ) as archive:
                    for name, source, expected in entries:
                        if source is None:
                            archive.writestr(name + "/", b"")
                            continue
                        received = 0
                        with (
                            source.open("rb") as reader,
                            archive.open(name, "w", force_zip64=True) as writer,
                        ):
                            while block := reader.read(BUFFER):
                                received += len(block)
                                completed += len(block)
                                if (
                                    completed > settings.output_bundle_max_bytes
                                    or received > expected
                                ):
                                    raise LimitExceeded(
                                        "An output changed or exceeded the ZIP size limit."
                                    )
                                writer.write(block)
                                if completed - checkpoint >= 8 * BUFFER:
                                    job.completed_bytes = completed
                                    session.commit()
                                    checkpoint = completed
                        if received != expected:
                            raise ValidationFailed("An output changed while preparing the ZIP.")
                        job.completed_bytes = completed
                        session.commit()
                stored_key = f"bundles/{job.id}/{uuid.uuid4()}.zip"
                stored = store.put(partial, stored_key)
                artifact = Artifact(
                    project_id=run.project_id,
                    run_id=run.id,
                    owner_id=job.requested_by,
                    kind=ArtifactKind.RUN_OUTPUT_PACKAGE,
                    storage_backend=store.backend,
                    storage_key=stored.storage_key,
                    filename=f"run-{run.id}.zip",
                    content_type="application/zip",
                    size_bytes=stored.size_bytes,
                    checksum_sha256=stored.checksum_sha256,
                    retention_class=RetentionClass.STANDARD,
                    expires_at=datetime.now(UTC) + timedelta(days=settings.default_retention_days),
                )
                session.add(artifact)
                session.flush()
                job.artifact_id = artifact.id
                job.status = "ready"
                session.commit()
            except Exception as error:
                logger.warning("ZIP preparation %s failed", bundle_id, exc_info=True)
                session.rollback()
                if stored_key:
                    store.delete(stored_key)
                job = session.get(ArtifactBundle, bundle_id)
                job.status = "failed"
                job.message = (
                    error.message
                    if isinstance(error, DomainError)
                    else (
                        "The results ZIP could not be prepared. "
                        "Retry or ask an administrator for help."
                    )
                )
                session.commit()
            finally:
                partial.unlink(missing_ok=True)
            return True
    except UploadBusy:
        return False
