"""Uploads over HTTP: offset-append, resumable, streamed to disk.

The protocol is four verbs and one number.

    POST   /uploads                  open one, get an id
    PATCH  /uploads/{id}             append at an offset, Content-Range says where
    GET    /uploads/{id}             where did it get to
    POST   /uploads/{id}/complete    check the bytes, mint the artifact
    DELETE /uploads/{id}             give up, release the disk

`PATCH` is the only `async` handler in this API, and for one reason: it is the
only one whose body must not be read into memory. Everything else runs in the
threadpool, where blocking database calls belong. Here the body is drained to
disk as it arrives and the short database calls around it are accepted as
they are — they take a millisecond against a transfer that takes minutes.

The cap is enforced against bytes **received**, never against
`Content-Length`: a sender that lies about its length is exactly the case a
cap exists for.
"""

from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass
from typing import IO

import anyio.to_thread
from fastapi import APIRouter, HTTPException, Request, status
from starlette.requests import ClientDisconnect

from app.api.deps import Config, CurrentUser, Db
from app.api.schemas import CreateUploadRequest, UploadResponse
from app.application.uploads import (
    BUFFER_BYTES,
    REFERENCE_PREFIX,
    ChecksumMismatch,
    OffsetMismatch,
    UploadTooLarge,
    abort_upload,
    allowance,
    begin_upload,
    complete_upload,
    exclusive,
    find_upload,
    record_append,
    repair,
    staging_key,
)
from app.domain.enums import UploadStatus
from app.infrastructure.artifacts import PosixArtifactStore
from app.infrastructure.db.models import Upload
from app.settings import Settings

router = APIRouter(prefix="/uploads", tags=["uploads"])

CONTENT_RANGE = re.compile(r"^bytes\s+(\d+)-(\d+)/(\d+|\*)$")


def _response(upload: Upload, settings: Settings) -> UploadResponse:
    return UploadResponse(
        id=upload.id,
        filename=upload.filename,
        status=UploadStatus(upload.status),
        received_bytes=upload.received_bytes,
        declared_size_bytes=upload.declared_size_bytes,
        checksum_sha256=upload.checksum_sha256,
        chunk_max_bytes=settings.upload_chunk_max_bytes,
        expires_at=upload.expires_at,
        completed_at=upload.completed_at,
        artifact_id=upload.artifact_id,
        reference=(
            f"{REFERENCE_PREFIX}{upload.id}"
            if upload.status == UploadStatus.COMPLETED.value
            else None
        ),
    )


def _mine_or_404(db: Db, upload_id: uuid.UUID, principal: CurrentUser) -> Upload:
    upload = find_upload(db, upload_id, actor_id=principal.user_id, is_admin=principal.is_admin)
    if upload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "upload.not_found", "message": "No such upload."},
        )
    return upload


@dataclass(frozen=True, slots=True)
class _Span:
    start: int
    end: int


def _range_or_400(request: Request) -> _Span:
    """Where the client says this chunk belongs.

    Required rather than defaulted to "wherever you got to". A client that
    does not say where it is writing cannot be resuming — it is guessing, and
    a guess that lands in the wrong place produces a file that is the right
    length and the wrong contents.
    """
    header = request.headers.get("content-range")
    if not header:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "upload.range_required",
                "message": (
                    "Append requests must carry a Content-Range header, "
                    "for example 'bytes 0-1048575/41943040'."
                ),
            },
        )
    match = CONTENT_RANGE.match(header.strip())
    if match is None or int(match.group(1)) > int(match.group(2)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "upload.range_invalid",
                "message": f"'{header}' is not a byte range this endpoint understands.",
                "details": {"content_range": header},
            },
        )
    return _Span(start=int(match.group(1)), end=int(match.group(2)))


@dataclass(slots=True)
class _Drained:
    written: int
    disconnected: bool


def _flush(handle: IO[bytes]) -> None:
    """Get the bytes onto the disk before the row claims they are there.

    The cost of an fsync per chunk, against the alternative: a machine that
    loses power leaves a row promising bytes the file does not have, and the
    next append writes past the hole rather than over it. A file with a hole
    in it passes every length check there is.
    """
    handle.flush()
    os.fsync(handle.fileno())


async def _drain(request: Request, handle: IO[bytes], *, offset: int, limit: int) -> _Drained:
    """Move the request body onto disk, buffered and bounded."""
    await anyio.to_thread.run_sync(handle.seek, offset)
    buffer = bytearray()
    written = 0
    disconnected = False
    try:
        async for chunk in request.stream():
            if not chunk:
                continue
            written += len(chunk)
            if written > limit:
                raise UploadTooLarge(
                    f"This chunk is larger than the {limit} bytes this upload can "
                    "accept here. Send it in smaller pieces.",
                    details={"limit_bytes": limit},
                )
            buffer += chunk
            if len(buffer) >= BUFFER_BYTES:
                await anyio.to_thread.run_sync(handle.write, bytes(buffer))
                buffer.clear()
    except ClientDisconnect:
        # Keep what arrived. TCP delivers a prefix or nothing, so the bytes on
        # disk are the first N the client sent — exactly what resuming needs.
        # Throwing them away would make a flaky link cost the whole chunk
        # every time.
        disconnected = True
    if buffer:
        await anyio.to_thread.run_sync(handle.write, bytes(buffer))
    await anyio.to_thread.run_sync(_flush, handle)
    return _Drained(written=written, disconnected=disconnected)


@router.post("", response_model=UploadResponse, status_code=status.HTTP_201_CREATED)
def create_upload(
    payload: CreateUploadRequest, db: Db, principal: CurrentUser, settings: Config
) -> UploadResponse:
    """Open an upload. Nothing is written until the first chunk arrives."""
    upload = begin_upload(
        db,
        owner_id=principal.user_id,
        filename=payload.filename,
        declared_size_bytes=payload.declared_size_bytes,
        checksum_sha256=payload.checksum_sha256,
        settings=settings,
    )
    return _response(upload, settings)


@router.get("/{upload_id}", response_model=UploadResponse)
def read_upload(
    upload_id: uuid.UUID, db: Db, principal: CurrentUser, settings: Config
) -> UploadResponse:
    """How far this upload got, which is how a client resumes one."""
    return _response(_mine_or_404(db, upload_id, principal), settings)


@router.patch("/{upload_id}", response_model=UploadResponse)
async def append_chunk(
    upload_id: uuid.UUID, request: Request, db: Db, principal: CurrentUser, settings: Config
) -> UploadResponse:
    """Append one chunk at the offset the client names.

    Under an exclusive lock on the staging file, held for as long as bytes are
    moving — which is why it is a file lock and not a locked row. The offset
    is checked against the file *after* it has been reconciled with the row,
    so a request that died half-written cannot leave the next one writing into
    a gap.
    """
    span = _range_or_400(request)
    upload = _mine_or_404(db, upload_id, principal)
    store = PosixArtifactStore(settings.artifact_root)

    with exclusive(store.path_for(staging_key(upload.id))) as handle:
        # Re-read under the lock: between the check above and this line
        # another request may have appended, completed, or aborted it.
        db.expire(upload)
        upload = _mine_or_404(db, upload_id, principal)
        offset = repair(handle, upload)
        # Place before size, and not the other way around. An upload that has
        # received everything it declared has no allowance left, so asking
        # "how much may you send" first answers a misplaced chunk with "too
        # large" — a different status, and one the client's resume logic does
        # not know how to recover from.
        if span.start != offset:
            handle.truncate(offset)
            raise OffsetMismatch(expected=offset, received=span.start)
        limit = allowance(upload, offset=offset, settings=settings)

        try:
            drained = await _drain(request, handle, offset=offset, limit=limit)
        except UploadTooLarge:
            # Nothing is kept from an over-long chunk: the client has to send
            # it again anyway, and half of it on disk is only confusing.
            await anyio.to_thread.run_sync(handle.truncate, offset)
            await anyio.to_thread.run_sync(_flush, handle)
            raise
        record_append(db, upload, received=offset + drained.written, settings=settings)

    return _response(upload, settings)


@router.post("/{upload_id}/complete", response_model=UploadResponse)
def finish_upload(
    upload_id: uuid.UUID, db: Db, principal: CurrentUser, settings: Config
) -> UploadResponse:
    """Verify the bytes and turn them into an artifact.

    Takes the same lock an append does, so a client that completes while a
    chunk is still in flight is told to wait rather than having half a file
    certified.
    """
    upload = _mine_or_404(db, upload_id, principal)
    store = PosixArtifactStore(settings.artifact_root)
    with exclusive(store.path_for(staging_key(upload.id))):
        db.expire(upload)
        upload = _mine_or_404(db, upload_id, principal)
        try:
            complete_upload(db, upload, store=store, settings=settings)
        except ChecksumMismatch:
            # A refusal that already deleted the bytes, so the row saying so
            # must survive the request that raised. Rolling back here would
            # leave an upload marked open with nothing behind it — the same
            # trap the artifact read audit fell into, where the failure path
            # is exactly the one whose record matters.
            db.commit()
            raise
    return _response(upload, settings)


@router.delete("/{upload_id}", response_model=UploadResponse)
def cancel_upload(
    upload_id: uuid.UUID, db: Db, principal: CurrentUser, settings: Config
) -> UploadResponse:
    """Abandon an upload and release the disk it was holding."""
    upload = _mine_or_404(db, upload_id, principal)
    store = PosixArtifactStore(settings.artifact_root)
    with exclusive(store.path_for(staging_key(upload.id))):
        db.expire(upload)
        upload = _mine_or_404(db, upload_id, principal)
        abort_upload(db, upload, store=store)
    return _response(upload, settings)
