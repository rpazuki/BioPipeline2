"""Delete resources with durable cleanup requests and retained audit history."""

from __future__ import annotations

import uuid
from contextlib import ExitStack, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import String, cast, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.application import audit
from app.application.deliveries import destination_for
from app.domain.errors import Conflict, DomainError, NotFound, ValidationFailed
from app.infrastructure.component_store import ComponentStore
from app.infrastructure.db.models import (
    Artifact,
    ArtifactBundle,
    PipelineRevision,
    Publication,
    PublicationRevision,
    ResourceDeletion,
    Run,
    RunDelivery,
    RunTask,
    Schedule,
    SharedStorageRoot,
    Upload,
    User,
    Workspace,
)
from app.infrastructure.reclaim import OutsideRoot, remove_within, within
from app.settings import Settings


def visible_definition(column: Any, kind: str) -> Any:
    """Exclude deleted definitions while retaining immutable historical rows."""
    return (
        ~select(ResourceDeletion.id)
        .where(
            ResourceDeletion.target_type == kind,
            ResourceDeletion.target_key == cast(column, String),
        )
        .exists()
    )


def is_deleted(session: Session, kind: str, key: str | uuid.UUID) -> bool:
    """Report whether an identifier has a retained deletion marker."""
    return (
        session.scalar(
            select(ResourceDeletion.id).where(
                ResourceDeletion.target_type == kind,
                ResourceDeletion.target_key == str(key),
            )
        )
        is not None
    )


def _request(
    session: Session,
    kind: str,
    key: str | uuid.UUID,
    context: audit.RequestContext,
    details: dict[str, Any],
    *,
    complete: bool = False,
) -> ResourceDeletion:
    existing = session.scalar(
        select(ResourceDeletion).where(
            ResourceDeletion.target_type == kind,
            ResourceDeletion.target_key == str(key),
        )
    )
    if existing:
        return existing
    requester = session.get(User, context.actor_id) if context.actor_id else None
    details = {
        **details,
        "deletion_requested_by": {
            "id": str(context.actor_id) if context.actor_id else None,
            "display_name": requester.display_name if requester else None,
            "email": requester.email if requester else None,
        },
    }
    job = ResourceDeletion(
        target_type=kind,
        target_key=str(key),
        requested_by=context.actor_id,
        details=details,
        status="complete" if complete else "pending",
        completed_at=datetime.now(UTC) if complete else None,
    )
    session.add(job)
    session.flush()
    summary = {key: value for key, value in details.items() if key not in {"paths", "artifact_ids"}}
    summary["file_locations"] = len(details.get("paths", []))
    audit.record(
        session,
        action=f"{kind}.deleted" if complete else f"{kind}.deletion_requested",
        target_type=kind,
        target_id=uuid.UUID(str(key)) if kind != "component" else None,
        context=context,
        deletion_id=str(job.id),
        **summary,
    )
    return job


def delete_publication(
    session: Session, publication_id: uuid.UUID, context: audit.RequestContext
) -> ResourceDeletion:
    """Delete a withdrawn publication from authoring without erasing run provenance."""
    publication = session.scalar(
        select(Publication).where(Publication.id == publication_id).with_for_update()
    )
    if publication is None:
        raise NotFound("Publication does not exist.")
    if publication.status != "archived":
        raise Conflict("Withdraw the publication before deleting it.")
    return _request(
        session, "publication", publication.id, context, {"slug": publication.slug}, complete=True
    )


def delete_revision(
    session: Session, revision_id: uuid.UUID, context: audit.RequestContext
) -> ResourceDeletion:
    """Delete a pipeline version from authoring after its live publications are withdrawn."""
    revision = session.scalar(
        select(PipelineRevision).where(PipelineRevision.id == revision_id).with_for_update()
    )
    if revision is None:
        raise NotFound("Pipeline version does not exist.")
    live = session.scalar(
        select(Publication.id)
        .join(PublicationRevision, Publication.current_revision_id == PublicationRevision.id)
        .where(
            PublicationRevision.pipeline_revision_id == revision_id,
            Publication.status == "published",
        )
    )
    if live:
        raise Conflict("Withdraw publications using this version before deleting it.")
    return _request(
        session,
        "pipeline_revision",
        revision.id,
        context,
        {
            "pipeline_id": str(revision.pipeline_id),
            "version": revision.version,
            "graph_hash": revision.graph_hash,
        },
        complete=True,
    )


def delete_component(
    session: Session, name: str, digest: str, settings: Settings, context: audit.RequestContext
) -> ResourceDeletion:
    """Queue removal of the selected component source, refusing stale selections."""
    store = ComponentStore(settings.component_library_root)
    _safe_path(store.root, name)
    source = store.read(name)
    if source["digest"] != digest:
        raise Conflict("The component changed. Reload before removing it.")
    existing = session.scalar(
        select(ResourceDeletion)
        .where(
            ResourceDeletion.target_type == "component",
            ResourceDeletion.status.in_(["pending", "failed"]),
            ResourceDeletion.details["name"].astext == name,
            ResourceDeletion.details["digest"].astext == digest,
            ResourceDeletion.details["component_root"].astext == str(store.root),
        )
        .limit(1)
    )
    if existing is not None:
        return existing
    return _request(
        session,
        "component",
        uuid.uuid4(),
        context,
        {
            "name": name,
            "digest": digest,
            "graphs": source["graphs"],
            "component_root": str(store.root),
            "component_device": store.root.stat().st_dev,
        },
    )


def delete_run(
    session: Session, run_id: uuid.UUID, settings: Settings, context: audit.RequestContext
) -> ResourceDeletion:
    """Hide a stopped run and persist a validated manifest for retryable file cleanup."""
    from app.application.uploads import UploadBusy, exclusive

    run = session.scalar(select(Run).where(Run.id == run_id).with_for_update())
    if run is None:
        raise NotFound("Run does not exist.")
    existing = session.scalar(
        select(ResourceDeletion).where(
            ResourceDeletion.target_type == "run", ResourceDeletion.target_key == str(run_id)
        )
    )
    if existing:
        return existing
    active = session.scalar(
        select(RunTask.id)
        .where(
            RunTask.run_id == run_id,
            RunTask.status.not_in(["succeeded", "failed", "cancelled", "skipped"]),
        )
        .limit(1)
    )
    if run.status not in {"succeeded", "failed", "cancelled"} or active:
        raise Conflict("Cancel the run and wait for every task to stop before deleting it.")
    bundles = list(session.scalars(select(ArtifactBundle).where(ArtifactBundle.run_id == run_id)))
    with ExitStack() as locks:
        for bundle in sorted(bundles, key=lambda item: str(item.id)):
            try:
                locks.enter_context(
                    exclusive(Path(settings.artifact_root) / f"bundles/locks/{bundle.id}")
                )
            except UploadBusy as error:
                raise Conflict(
                    "A results ZIP is still being prepared. Wait before deleting the run."
                ) from error
        try:
            with session.begin_nested():
                deliveries = list(
                    session.scalars(
                        select(RunDelivery)
                        .where(RunDelivery.run_id == run_id)
                        .with_for_update(nowait=True)
                    )
                )
        except OperationalError as error:
            if getattr(error.orig, "sqlstate", None) == "55P03":
                raise Conflict(
                    "Results are still being delivered. Wait before deleting the run."
                ) from error
            raise
        paths: list[dict[str, Any]] = [
            {"root": "workspace", "path": str(run_id)},
            {"root": "artifacts", "path": f"runs/{run_id}"},
        ]
        for workspace in session.scalars(select(Workspace).where(Workspace.run_id == run_id)):
            paths.append({"root": "workspace", "path": workspace.root_key})
        artifacts = list(session.scalars(select(Artifact).where(Artifact.run_id == run_id)))
        # Lock uploaded artifacts before checking other runs: submissions acquire a shared lock.
        input_ids = [
            uuid.UUID(item["artifact_id"])
            for item in run.compiled_run_spec.get("staged_inputs", [])
        ]
        preserved = []
        for artifact_id in sorted(set(input_ids), key=str):
            artifact = session.scalar(
                select(Artifact).where(Artifact.id == artifact_id).with_for_update()
            )
            if artifact is None:
                continue
            reused = session.scalar(
                select(Run.id)
                .where(
                    Run.id != run_id,
                    Run.deleted_at.is_(None),
                    Run.compiled_run_spec["staged_inputs"].contains(
                        [{"artifact_id": str(artifact_id)}]
                    ),
                )
                .limit(1)
            )
            uploads = list(session.scalars(select(Upload).where(Upload.artifact_id == artifact_id)))
            scheduled = any(
                session.scalar(
                    select(Schedule.id)
                    .where(
                        cast(Schedule.input_values, String).contains(f"upload:{upload.id}"),
                        Schedule.status.in_(["active", "paused"]),
                    )
                    .limit(1)
                )
                for upload in uploads
            )
            if reused or scheduled:
                preserved.append(str(artifact_id))
                continue
            artifacts.append(artifact)
            for upload in uploads:
                paths += [
                    {"root": "artifacts", "path": f"uploads/{upload.id}"},
                    {"root": "artifacts", "path": upload.storage_key},
                ]
        for artifact in artifacts:
            if artifact.kind != "shared_input_reference" and artifact.storage_backend == "posix":
                paths.append({"root": "artifacts", "path": artifact.storage_key})
            artifact.deleted_at = datetime.now(UTC)
        for bundle in bundles:
            paths += [
                {"root": "artifacts", "path": f"bundles/{bundle.id}"},
                {"root": "artifacts", "path": f"bundles/locks/{bundle.id}"},
                {"root": "artifacts", "path": f"bundles/staging/{bundle.id}.zip.partial"},
            ]
            bundle.status = "failed"
            bundle.message = "The run was deleted."
        for delivery in deliveries:
            if delivery.mode == "shared" and delivery.artifact_id:
                root = session.get(SharedStorageRoot, delivery.target_root_id)
                artifact = session.get(Artifact, delivery.artifact_id)
                if root is None or artifact is None:
                    raise ValidationFailed("A delivery's storage root or artifact is missing.")
                target = destination_for(session, delivery, root, artifact)
                if delivery.target_path and Path(delivery.target_path) != target:
                    raise ValidationFailed(
                        "A delivery path no longer matches this run's destination."
                    )
                relative = str(
                    within(target, root.root_path).relative_to(Path(root.root_path).resolve())
                )
                if delivery.target_path:
                    paths.append({"root": "shared", "root_id": root.id, "path": relative})
                elif target.exists():
                    raise Conflict(
                        "An unconfirmed delivery destination already contains a file. "
                        "Retry the delivery or review that file before deleting the run."
                    )
                for attempt in range(1, delivery.attempts + 1):
                    paths.append(
                        {
                            "root": "shared",
                            "root_id": root.id,
                            "path": str(
                                Path(relative).with_name(f".{target.name}.incoming-{attempt}")
                            ),
                        }
                    )
            if delivery.status == "pending":
                delivery.status = "skipped"
                delivery.message = "The run was deleted."
        # Validate every path before accepting a request; the worker validates again before removal.
        for item in paths:
            anchor = _root(session, settings, item)
            _safe_path(anchor, item["path"])
            item["device"] = anchor.stat().st_dev
            item["anchor"] = str(anchor)
        run.deleted_at = datetime.now(UTC)
        job = _request(
            session,
            "run",
            run_id,
            context,
            {
                "paths": paths,
                "artifact_ids": [str(item.id) for item in artifacts],
                "preserved_shared_uploads": preserved,
                "status": run.status,
                "requested_by": str(run.requested_by),
                "pipeline_revision_id": str(run.pipeline_revision_id),
            },
        )
        # The request and audit must be durable before releasing the ZIP writer locks.
        session.commit()
        return job


def _root(session: Session, settings: Settings, item: dict[str, Any]) -> Path:
    if item["root"] == "workspace":
        return Path(settings.workspace_root).resolve()
    if item["root"] == "artifacts":
        return Path(settings.artifact_root).resolve()
    root = session.get(SharedStorageRoot, item.get("root_id"))
    if root is None:
        raise ValidationFailed("The shared storage root is no longer configured.")
    anchor = Path(root.root_path).resolve()
    if not anchor.is_dir():
        raise ValidationFailed("The shared storage root is not mounted or accessible.")
    return anchor


def _safe_path(anchor: Path, relative: str) -> Path:
    """Validate a deletion path without following links into another resource."""
    if not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise OutsideRoot("Deletion paths must be relative to their configured storage root.")
    current = anchor
    for part in Path(relative).parts:
        current = current / part
        if current.is_symlink():
            raise OutsideRoot("Deletion refuses symbolic links in resource paths.")
    return within(current, anchor)


def process_deletions(session: Session, settings: Settings, *, limit: int = 20) -> int:
    """Remove queued resource files and audit success or failure without losing retry state."""
    jobs = list(
        session.scalars(
            select(ResourceDeletion)
            .where(ResourceDeletion.status == "pending")
            .order_by(ResourceDeletion.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )
    for job in jobs:
        try:
            if job.target_type == "component":
                store = ComponentStore(settings.component_library_root)
                if str(store.root) != job.details.get(
                    "component_root"
                ) or store.root.stat().st_dev != job.details.get("component_device"):
                    raise Conflict(
                        "The component storage root changed after deletion was requested."
                    )
                _safe_path(store.root, job.details["name"])
                with suppress(NotFound):
                    store.remove(job.details["name"], job.details["digest"])
            else:
                resolved = [
                    (item, _root(session, settings, item)) for item in job.details.get("paths", [])
                ]
                for item, anchor in resolved:
                    if "anchor" in item and str(anchor) != item["anchor"]:
                        raise Conflict("The storage root changed since deletion was requested.")
                    if "device" in item and anchor.stat().st_dev != item["device"]:
                        raise Conflict("The storage mount changed since deletion was requested.")
                    _safe_path(anchor, item["path"])
                for item, anchor in resolved:
                    remove_within(anchor / item["path"], root=anchor)
                    parent = (anchor / item["path"]).parent
                    while parent != anchor and parent.is_relative_to(anchor):
                        try:
                            parent.rmdir()
                        except OSError:
                            break
                        parent = parent.parent
                for identifier in job.details.get("artifact_ids", []):
                    artifact = session.get(Artifact, uuid.UUID(identifier))
                    if artifact:
                        artifact.purged_at = datetime.now(UTC)
                for workspace in session.scalars(
                    select(Workspace).where(Workspace.run_id == uuid.UUID(job.target_key))
                ):
                    workspace.deleted_at = datetime.now(UTC)
                    workspace.status = "deleted"
            job.status = "complete"
            job.completed_at = datetime.now(UTC)
            job.error = None
            action = f"{job.target_type}.deleted"
        except (OSError, ValueError, KeyError, DomainError) as error:
            job.status = "failed"
            job.error = str(error)
            action = f"{job.target_type}.deletion_failed"
        audit.record(
            session,
            action=action,
            target_type=job.target_type,
            target_id=uuid.UUID(job.target_key) if job.target_type != "component" else None,
            context=audit.RequestContext(actor_id=job.requested_by),
            deletion_id=str(job.id),
            error=job.error,
            name=job.details.get("name"),
            status=job.status,
        )
    session.flush()
    return len(jobs)
