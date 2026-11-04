"""Assemble owned file uploads and checked ZIP files into immutable directory inputs."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.pipelines import default_project_id
from app.application.uploads import (
    DIRECTORY_TYPES,
    _clean_filename,
    exclusive,
    input_kind,
    resolve_reference,
)
from app.domain.enums import ArtifactKind, RetentionClass, UploadStatus
from app.domain.errors import Conflict, LimitExceeded, ValidationFailed
from app.infrastructure.archives import check_members, extract_zip
from app.infrastructure.artifacts import PosixArtifactStore
from app.infrastructure.db.models import Artifact, Upload
from app.settings import Settings


def make_directory(
    session: Session,
    *,
    request_id: uuid.UUID,
    owner_id: uuid.UUID,
    name: str,
    settings: Settings,
    files: list[tuple[str, uuid.UUID]] | None = None,
    zip_upload_id: uuid.UUID | None = None,
) -> Upload:
    """Create an idempotent directory upload from files owned by the requester."""
    name = _clean_filename(name)
    store = PosixArtifactStore(settings.artifact_root)
    kind = "zip" if zip_upload_id else "folder"
    members = files or []
    if zip_upload_id is None and len(members) > settings.upload_directory_max_files:
        raise LimitExceeded("The folder contains too many files.")
    paths = check_members(
        [(path, False) for path, _ in members], max_members=settings.upload_directory_max_files
    )
    sources: list[Artifact] = []
    for upload_id in [zip_upload_id] if zip_upload_id else [item[1] for item in members]:
        staged = resolve_reference(session, f"upload:{upload_id}", requested_by=owner_id)
        artifact = session.get(Artifact, staged.artifact_id)
        if artifact is None or input_kind(artifact) != "file":
            raise ValidationFailed("A directory must be built from completed file uploads.")
        sources.append(artifact)
    total = sum(artifact.size_bytes for artifact in sources)
    if not zip_upload_id and total > settings.upload_directory_max_bytes:
        raise LimitExceeded("The folder exceeds the expanded directory size limit.")
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "kind": kind,
                "name": name,
                "paths": paths,
                "sources": [str(artifact.id) for artifact in sources],
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    lock = store.path_for(f"uploads/assembly-locks/{request_id}")
    with exclusive(lock):
        existing = session.get(Upload, request_id)
        if existing:
            if existing.owner_id != owner_id or existing.checksum_sha256 != fingerprint:
                raise Conflict("That directory request identifier has already been used.")
            if existing.status != UploadStatus.COMPLETED:
                raise Conflict("The directory is not complete. Start a new directory request.")
            return existing
        temporary_root = store.path_for("uploads/assembly")
        temporary_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary_root) as temporary:
            directory = Path(temporary)
            if zip_upload_id:
                extract_zip(
                    store.path_for(sources[0].storage_key),
                    directory,
                    max_bytes=settings.upload_directory_max_bytes,
                    max_files=settings.upload_directory_max_files,
                )
            else:
                for path, artifact in zip(paths, sources, strict=True):
                    target = directory / path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    source = store.path_for(artifact.storage_key)
                    if not source.is_file() or source.stat().st_size != artifact.size_bytes:
                        raise ValidationFailed("An uploaded file is missing or has changed.")
                    shutil.copyfile(source, target)
            key = f"uploads/{request_id}/{name}"
            if session.scalar(
                select(Artifact.id).where(
                    Artifact.storage_key == key, Artifact.deleted_at.is_(None)
                )
            ):
                raise Conflict("That directory storage location is already in use.")
            # Remove only an unreferenced partial assembly left by this exact request.
            store.delete(key)
            stored = store.put(directory, key)
        upload = Upload(
            id=request_id,
            project_id=default_project_id(session),
            owner_id=owner_id,
            filename=name,
            storage_key=key,
            status=UploadStatus.COMPLETED,
            received_bytes=stored.size_bytes,
            declared_size_bytes=stored.size_bytes,
            checksum_sha256=fingerprint,
            completed_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(hours=settings.upload_expiry_hours),
        )
        artifact = Artifact(
            project_id=upload.project_id,
            owner_id=owner_id,
            kind=ArtifactKind.UPLOAD_INPUT,
            storage_backend=store.backend,
            storage_key=key,
            filename=name,
            size_bytes=stored.size_bytes,
            content_type=DIRECTORY_TYPES[kind],
            retention_class=RetentionClass.STANDARD,
            expires_at=datetime.now(UTC) + timedelta(days=settings.default_retention_days),
        )
        session.add(artifact)
        session.flush()
        upload.artifact_id = artifact.id
        session.add(upload)
        session.flush()
        # Keep the filesystem lock until the idempotency row is visible to other requests.
        session.commit()
        return upload
