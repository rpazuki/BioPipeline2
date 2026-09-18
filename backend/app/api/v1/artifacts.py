"""Getting results out.

The end of the journey the rest of the system exists for: a run produced
verified, checksummed bytes, and this is where somebody retrieves them.

Three things are deliberate.

**Every response is an attachment, typed `application/octet-stream`.** An
artifact's bytes were written by scientific code, so serving one inline under a
content type derived from its name would make the API origin a place to host
whatever a task wrote. `attachment` plus `nosniff` removes the question rather
than reasoning about which types are safe.

**A directory is retrieved a file at a time.** Packaging a multi-gigabyte
output tree into an archive is slow, and doing it inside the process that also
answers every other request is not a thing to do on a click. The store already
writes a manifest for exactly this.

**Reads are audited, in their own transaction.** `audit_artifact_reads` has
defaulted to true since the settings were written and nothing wrote a row,
because until now there was nothing to audit. Refusals are recorded too — and
a refusal ends in an exception, which rolls the request's transaction back, so
an audit row sharing that transaction would record every successful read and
lose every denied one. Which is precisely backwards.
"""

from __future__ import annotations

import ipaddress
import uuid

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse

from app.api.deps import Config, CurrentUser, Db
from app.api.schemas import ArtifactDetail, ArtifactFile
from app.application.artifacts import (
    ArtifactUnavailable,
    DownloadableFile,
    artifact_for_download,
    record_access,
    resolve_download,
)
from app.domain.enums import ArtifactKind
from app.infrastructure.artifacts import PosixArtifactStore
from app.infrastructure.db.models import Artifact, Run
from app.settings import Settings

router = APIRouter(prefix="/artifacts", tags=["artifacts"])

# Never the stored content type, and never guessed from the filename. See the
# module docstring: this is the whole of the policy.
DOWNLOAD_HEADERS = {"X-Content-Type-Options": "nosniff"}
DOWNLOAD_TYPE = "application/octet-stream"


def _peer(request: Request) -> str | None:
    """The caller's address, if it is one.

    Stored in an `inet` column, so anything that is not an address has to
    become NULL rather than reaching the database — a malformed peer would
    otherwise turn a successful download into a 500. Only the direct peer:
    honouring `X-Forwarded-For` without a configured list of trusted proxies
    would record whatever the client asked us to.
    """
    client = request.client
    if client is None:
        return None
    try:
        return str(ipaddress.ip_address(client.host))
    except ValueError:
        return None


def _audit(
    request: Request,
    *,
    settings: Settings,
    artifact_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    access_type: str,
    bytes_served: int | None = None,
) -> None:
    """Record one access, on a session of its own, committed immediately.

    Not the request's session: a denial raises, the request transaction rolls
    back, and the row would go with it. It is also written *before* the bytes
    leave — a `FileResponse` streams after the handler returns, so there is no
    arrangement in which the record can depend on the transfer completing.
    """
    if not settings.audit_artifact_reads:
        return
    with request.app.state.sessions() as session:
        record_access(
            session,
            artifact_id=artifact_id,
            actor_id=actor_id,
            access_type=access_type,
            bytes_served=bytes_served,
            request_id=getattr(request.state, "request_id", None),
            ip_address=_peer(request),
        )
        session.commit()


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "artifact.not_found", "message": "No such artifact."},
    )


def _visible_or_404(
    db: Db, request: Request, settings: Settings, artifact_id: uuid.UUID, principal: CurrentUser
) -> Artifact:
    """An artifact the caller may have.

    Somebody else's artifact is a 404 rather than a 403, as their run is:
    telling a caller that something exists but is not theirs leaks which runs
    exist. A refusal is audited — walking artifact ids that are not yours is
    precisely what a read audit is for.
    """
    artifact = artifact_for_download(db, artifact_id)
    if artifact is None:
        raise _not_found()
    run = db.get(Run, artifact.run_id) if artifact.run_id else None
    # Two ways to own an artifact, and until uploads existed only one of them
    # was ever exercised: a run's outputs belong to whoever submitted it, and
    # an uploaded input belongs to whoever uploaded it and has no run at all.
    # `artifacts.owner_id` was on the row the whole time and nothing read it.
    mine = (
        principal.is_admin
        or (artifact.owner_id is not None and artifact.owner_id == principal.user_id)
        or (run is not None and run.requested_by == principal.user_id)
    )
    if not mine:
        _audit(
            request,
            settings=settings,
            artifact_id=artifact_id,
            actor_id=principal.user_id,
            access_type="denied",
        )
        raise _not_found()
    return artifact


@router.get("/{artifact_id}", response_model=ArtifactDetail)
def read_artifact(
    artifact_id: uuid.UUID,
    db: Db,
    request: Request,
    principal: CurrentUser,
    settings: Config,
) -> ArtifactDetail:
    """What this artifact is, and what can be retrieved from it.

    A directory answers with its manifest, so a client can offer per-file
    download without anybody building an archive. An artifact whose bytes have
    expired answers with `available: false` and why, rather than a 404 — the
    run still succeeded and the researcher is owed that distinction.
    """
    artifact = _visible_or_404(db, request, settings, artifact_id, principal)
    store = PosixArtifactStore(settings.artifact_root)

    detail = ArtifactDetail(
        id=artifact.id,
        kind=ArtifactKind(artifact.kind),
        filename=artifact.filename,
        size_bytes=artifact.size_bytes,
        checksum_sha256=artifact.checksum_sha256,
        created_at=artifact.created_at,
        expires_at=artifact.expires_at,
        run_id=artifact.run_id,
        task_id=artifact.task_id,
        content_type=artifact.content_type,
    )

    if artifact.deleted_at is not None or artifact.purged_at is not None:
        detail.available = False
        detail.unavailable_reason = (
            "These outputs have been removed. Artifacts are kept until their "
            "retention expires; the run's record of what happened stays."
        )
        return detail

    path = store.path_for(artifact.storage_key)
    if path.is_dir():
        detail.is_directory = True
        detail.files = [
            ArtifactFile(
                path=entry.relative_path,
                size_bytes=entry.size_bytes,
                checksum_sha256=entry.checksum_sha256,
            )
            for entry in store.manifest(artifact.storage_key)
        ]
    elif not path.is_file():
        detail.available = False
        detail.unavailable_reason = "The bytes of this artifact are missing from the store."

    _audit(
        request,
        settings=settings,
        artifact_id=artifact_id,
        actor_id=principal.user_id,
        access_type="metadata",
    )
    return detail


def _serve(
    db: Db,
    request: Request,
    settings: Settings,
    principal: CurrentUser,
    artifact_id: uuid.UUID,
    member: str | None,
) -> FileResponse:
    artifact = _visible_or_404(db, request, settings, artifact_id, principal)
    store = PosixArtifactStore(settings.artifact_root)
    try:
        found: DownloadableFile = resolve_download(artifact, store, member=member)
    except ArtifactUnavailable as error:
        _audit(
            request,
            settings=settings,
            artifact_id=artifact_id,
            actor_id=principal.user_id,
            access_type="denied",
        )
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={"code": error.code, "message": error.message, "details": error.details},
        ) from error

    # The size offered, not the size delivered: a client may disconnect
    # halfway and the row is written before a byte leaves. Named `bytes_served`
    # in the schema, so this is the one place to say which it is.
    _audit(
        request,
        settings=settings,
        artifact_id=artifact_id,
        actor_id=principal.user_id,
        access_type="download",
        bytes_served=found.size_bytes,
    )
    return FileResponse(
        found.path,
        media_type=DOWNLOAD_TYPE,
        filename=found.filename,
        headers=DOWNLOAD_HEADERS,
    )


@router.get("/{artifact_id}/download")
def download(
    artifact_id: uuid.UUID,
    db: Db,
    request: Request,
    principal: CurrentUser,
    settings: Config,
) -> FileResponse:
    """The artifact's bytes.

    Streamed from disk with range support, so a twenty-gigabyte alignment can
    be resumed rather than restarted, and so the process never holds one in
    memory.
    """
    return _serve(db, request, settings, principal, artifact_id, None)


@router.get("/{artifact_id}/files/{member:path}")
def download_member(
    artifact_id: uuid.UUID,
    member: str,
    db: Db,
    request: Request,
    principal: CurrentUser,
    settings: Config,
) -> FileResponse:
    """One file from inside a directory artifact.

    `member` arrives from a URL, so it is resolved against the artifact's own
    directory and refused if it lands outside — a path is not trusted for
    looking relative.
    """
    return _serve(db, request, settings, principal, artifact_id, member)
