"""Getting a file in: chunked, resumable, and never held in memory.

The mirror of the artifact download, and the harder direction. A researcher's
input can be tens of gigabytes (ADR 0006), and their laptop is on a campus VPN
that drops. A single `POST /files/uploads` -- which is what the plan proposed
and G14 rejected -- means a four-hour transfer that fails at 98% starts again.

So an upload is a **row with an offset**. The client asks where to continue,
appends there, and finishes by asking for the bytes to be checked and minted
as an artifact. Five decisions hold it together.

**The row is the truth; the file is repaired to match it.** The opposite of
artifact promotion, where bytes come first and the row second, and for the
opposite reason: a promoted artifact missing its bytes is a lie in the audit
trail, while a staging file with extra bytes is only garbage from a request
that died before it could be recorded. So an append fsyncs, then commits, and
the next append truncates the file back to whatever the row says. If the file
is *shorter* than the row claims -- which fsync should prevent -- the file
wins and the offset moves back, because the bytes are what the checksum will
be taken over.

**The offset must be exact.** A chunk that arrives anywhere other than the end
of what has been recorded is refused with the offset it should have used. The
alternative is silently writing a hole or overwriting good bytes, and the
researcher discovering months later that one BAM file was subtly wrong.

**The lock is on the file, not on a row.** Two chunks appended at once would
interleave, so appending is serialised -- but with `flock`, not
`SELECT FOR UPDATE`. Holding a database transaction open while a laptop pushes
64 MB over a VPN is minutes of idle-in-transaction per upload, which is how a
connection pool and autovacuum both suffer for something that is not a
database problem. The lock lives as long as the file descriptor, and the row
is re-read under it.

**Nothing is ever fully in memory.** Chunks are drained to disk as they
arrive, with a bounded buffer. The cap is enforced against bytes *received*,
not against `Content-Length`, because that header is a claim by the sender.

**HTTP upload is the small-file path.** ADR 0033: inputs in the tens of
gigabytes belong on a shared root, where they can be put by the tools built
for moving data at that size, and named rather than re-transferred.
"""

from __future__ import annotations

import fcntl
import os
import re
import shutil
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import IO, Any

from sqlalchemy.orm import Session

from app.application.pipelines import default_project_id
from app.domain.enums import ArtifactKind, RetentionClass, UploadStatus
from app.domain.errors import Conflict, LimitExceeded, ValidationFailed
from app.infrastructure.artifacts import PosixArtifactStore
from app.infrastructure.db.models import Artifact, Run, Upload
from app.settings import Settings

# Where a partial upload's bytes live until they are worth keeping. Under the
# artifact root so that completing one is a hardlink rather than a copy of
# however many gigabytes just arrived.
STAGING_PREFIX = "uploads/staging"
ARTIFACT_PREFIX = "uploads"

# Written to disk in pieces this size rather than as each chunk arrives, so a
# 64 MB append is a few dozen writes instead of a thousand thread hops, and
# never more than this much of it is in memory at once.
BUFFER_BYTES = 1024 * 1024

# A filename is the one part of an upload the researcher chooses, and it ends
# up as a path segment in the artifact store. Refused rather than mangled: a
# name silently rewritten is a file they cannot find again.
FILENAME_MAX = 255
_FILENAME_FORBIDDEN = re.compile(r"[/\\\x00-\x1f]")


_BUSY = (
    "Another chunk of this upload is being written. Ask where it is up to and continue from there."
)


class UploadRejected(ValidationFailed):
    """The upload cannot be created or finished as asked."""

    code = "upload.invalid"


class UploadBusy(Conflict):
    """Another request is appending to this upload right now."""

    code = "upload.busy"


class UploadNotOpen(Conflict):
    """Completed, aborted, or expired: there is nothing more to append."""

    code = "upload.not_open"


class OffsetMismatch(Conflict):
    """A chunk arrived somewhere other than the end of what was recorded."""

    code = "upload.offset_conflict"

    def __init__(self, *, expected: int, received: int) -> None:
        super().__init__(
            f"This upload continues at byte {expected}, not {received}.",
            details={"expected_offset": expected, "received_offset": received},
        )


class UploadIncomplete(Conflict):
    """Asked to finish an upload that has not received everything it declared."""

    code = "upload.incomplete"


class UploadTooLarge(LimitExceeded):
    code = "upload.too_large"


class ChecksumMismatch(ValidationFailed):
    """The bytes that arrived are not the bytes the client said it was sending."""

    code = "upload.checksum_mismatch"


def staging_key(upload_id: uuid.UUID) -> str:
    return f"{STAGING_PREFIX}/{upload_id}"


def artifact_key(upload_id: uuid.UUID, filename: str) -> str:
    return f"{ARTIFACT_PREFIX}/{upload_id}/{filename}"


def _clean_filename(filename: str) -> str:
    name = filename.strip()
    if not name or name in {".", ".."}:
        raise UploadRejected("A file needs a name.")
    if len(name) > FILENAME_MAX:
        raise UploadRejected(f"'{name[:40]}…' is longer than {FILENAME_MAX} characters.")
    if _FILENAME_FORBIDDEN.search(name):
        raise UploadRejected(
            f"'{name}' cannot be used as a filename: it contains a path separator "
            "or a control character."
        )
    return name


# --- the staging file ------------------------------------------------------


@contextmanager
def exclusive(path: Path) -> Iterator[IO[bytes]]:
    """Open the staging file for appending, or refuse because someone else has it.

    `flock` rather than a locked row: this serialises writers for as long as
    bytes are moving, which may be minutes, and a database transaction is the
    wrong thing to hold open for that. Non-blocking, so a second request is
    told immediately rather than occupying a thread until the first finishes.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    # Not "a+b": append mode ignores the seek and puts every write at the end,
    # which is exactly the behaviour an exact-offset protocol must not have.
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    handle = os.fdopen(descriptor, "r+b")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as error:
        handle.close()
        raise UploadBusy(_BUSY) from error
    try:
        # The lock arrived, but on which file? Between the open and the lock
        # another holder may have unlinked this path, leaving this descriptor
        # pointing at an inode with no name — where every byte written would
        # be recorded as received and then vanish. Rare, and silent, which is
        # the combination worth eight lines.
        if not _same_file(handle, path):
            raise UploadBusy(_BUSY)
        yield handle
        # An empty staging file says nothing that the row does not, and
        # completing or aborting twice would otherwise leave one behind for
        # ever.
        if handle.seek(0, os.SEEK_END) == 0:
            path.unlink(missing_ok=True)
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _same_file(handle: IO[bytes], path: Path) -> bool:
    try:
        return os.fstat(handle.fileno()).st_ino == path.stat().st_ino
    except FileNotFoundError:
        return False


def repair(handle: IO[bytes], upload: Upload) -> int:
    """Make the file agree with the row, and return the offset to append at.

    Called under the lock, before anything is written. Two directions:

    * The file is **longer** than the row: a previous request wrote bytes and
      died before recording them. They are discarded — the row is what the
      client was told, so the client will send them again.
    * The file is **shorter** than the row: the row promises bytes that are not
      there. The file wins, because the checksum will be taken over the file.
      This should not happen, since an append fsyncs before it commits; if it
      does, the client is told to resume from further back rather than being
      handed a file with a hole in it.
    """
    handle.seek(0, os.SEEK_END)
    actual = handle.tell()
    if actual > upload.received_bytes:
        handle.truncate(upload.received_bytes)
        return upload.received_bytes
    return actual


# --- lifecycle -------------------------------------------------------------


def begin_upload(
    session: Session,
    *,
    owner_id: uuid.UUID,
    filename: str,
    settings: Settings,
    declared_size_bytes: int | None = None,
    checksum_sha256: str | None = None,
) -> Upload:
    """Open an upload and reserve nothing.

    No disk is allocated: the staging file appears with the first chunk. An
    upload that is created and abandoned costs one row, which the reaper
    removes.
    """
    name = _clean_filename(filename)
    if declared_size_bytes is not None:
        if declared_size_bytes < 0:
            raise UploadRejected("A declared size cannot be negative.")
        if declared_size_bytes > settings.upload_max_total_bytes:
            raise UploadTooLarge(
                f"'{name}' is {declared_size_bytes} bytes; this deployment accepts "
                f"uploads up to {settings.upload_max_total_bytes} bytes. Put a file "
                "this size on a shared root and select it there instead.",
                details={"limit_bytes": settings.upload_max_total_bytes},
            )
    if checksum_sha256 is not None and not re.fullmatch(r"[0-9a-f]{64}", checksum_sha256):
        raise UploadRejected("A checksum must be 64 lowercase hexadecimal characters (SHA-256).")

    upload = Upload(
        project_id=default_project_id(session),
        owner_id=owner_id,
        filename=name,
        declared_size_bytes=declared_size_bytes,
        checksum_sha256=checksum_sha256,
        storage_key="",
        status=UploadStatus.OPEN,
        expires_at=datetime.now(UTC) + timedelta(hours=settings.upload_expiry_hours),
    )
    session.add(upload)
    session.flush()
    upload.storage_key = staging_key(upload.id)
    session.flush()
    return upload


def find_upload(
    session: Session, upload_id: uuid.UUID, *, actor_id: uuid.UUID, is_admin: bool = False
) -> Upload | None:
    """Somebody's upload, or nothing.

    Another user's upload is indistinguishable from one that does not exist,
    as their runs and artifacts are: answering "that exists but is not yours"
    tells a caller what other people are working on.
    """
    upload = session.get(Upload, upload_id)
    if upload is None:
        return None
    if upload.owner_id != actor_id and not is_admin:
        return None
    return upload


def allowance(upload: Upload, *, offset: int, settings: Settings) -> int:
    """The most this request may append, in bytes.

    The smallest of three limits: one chunk, whatever is left of a declared
    size, and the deployment's ceiling for a single upload. Returned rather
    than checked, because the number has to be enforced against bytes as they
    arrive — `Content-Length` is a claim, not a measurement.
    """
    if upload.status != UploadStatus.OPEN.value:
        raise UploadNotOpen(
            f"This upload is {upload.status} and cannot take more bytes.",
            details={"status": upload.status},
        )
    if upload.expires_at is not None and upload.expires_at <= datetime.now(UTC):
        raise UploadNotOpen(
            "This upload expired before it was finished. Start a new one.",
            details={"status": upload.status},
        )
    remaining = settings.upload_max_total_bytes - offset
    if upload.declared_size_bytes is not None:
        remaining = min(remaining, upload.declared_size_bytes - offset)
    if remaining <= 0:
        raise UploadTooLarge(
            "This upload has already received everything it can hold.",
            details={"limit_bytes": settings.upload_max_total_bytes},
        )
    return min(settings.upload_chunk_max_bytes, remaining)


def record_append(session: Session, upload: Upload, *, received: int, settings: Settings) -> Upload:
    """Write down where the upload has got to, once the bytes are on disk.

    The expiry moves with the last chunk rather than the creation: a
    forty-gigabyte transfer over a slow link can legitimately outlast the
    abandonment window, and expiring an upload that is visibly in progress
    would be the platform deleting work it can see happening.
    """
    upload.received_bytes = received
    upload.expires_at = datetime.now(UTC) + timedelta(hours=settings.upload_expiry_hours)
    session.flush()
    return upload


def complete_upload(
    session: Session, upload: Upload, *, store: PosixArtifactStore, settings: Settings
) -> Artifact:
    """Check the bytes and mint the artifact.

    Idempotent for an upload that is already complete: a client whose
    connection dropped on the response asks again and gets the same artifact,
    rather than a conflict for something that worked.
    """
    if upload.status == UploadStatus.COMPLETED.value and upload.artifact_id is not None:
        artifact = session.get(Artifact, upload.artifact_id)
        if artifact is not None:
            return artifact
    if upload.status != UploadStatus.OPEN.value:
        raise UploadNotOpen(
            f"This upload is {upload.status} and cannot be completed.",
            details={"status": upload.status},
        )

    staging = store.path_for(staging_key(upload.id))
    actual = staging.stat().st_size if staging.is_file() else 0
    if actual != upload.received_bytes:
        # The row is what the client was told; disagreement here means a
        # request died between writing and recording, so say where it really
        # got to rather than certifying bytes nobody vouched for.
        upload.received_bytes = min(actual, upload.received_bytes)
        session.flush()
        raise OffsetMismatch(expected=upload.received_bytes, received=actual)
    if actual == 0:
        raise UploadRejected(
            f"Nothing was uploaded for '{upload.filename}', so there is nothing to keep."
        )
    if upload.declared_size_bytes is not None and actual != upload.declared_size_bytes:
        raise UploadIncomplete(
            f"'{upload.filename}' is {actual} of {upload.declared_size_bytes} bytes. "
            "Send the rest before completing it.",
            details={"received_bytes": actual, "declared_size_bytes": upload.declared_size_bytes},
        )

    declared_checksum = upload.checksum_sha256
    stored = store.put(staging, artifact_key(upload.id, upload.filename))
    if declared_checksum is not None and stored.checksum_sha256 != declared_checksum:
        # Not recoverable by resending a chunk: nobody knows which one was
        # wrong. The upload ends here and the bytes go, so a corrupt file
        # cannot be completed by asking twice.
        store.delete(stored.storage_key)
        store.delete(staging_key(upload.id))
        upload.status = UploadStatus.ABORTED
        session.flush()
        raise ChecksumMismatch(
            f"'{upload.filename}' arrived with checksum {stored.checksum_sha256}, "
            f"not {declared_checksum}. The upload was discarded; send it again.",
            details={"expected": declared_checksum, "actual": stored.checksum_sha256},
        )

    artifact = Artifact(
        project_id=upload.project_id,
        owner_id=upload.owner_id,
        kind=ArtifactKind.UPLOAD_INPUT,
        storage_backend=store.backend,
        storage_key=stored.storage_key,
        filename=upload.filename,
        size_bytes=stored.size_bytes,
        checksum_sha256=stored.checksum_sha256,
        retention_class=RetentionClass.STANDARD,
        expires_at=datetime.now(UTC) + timedelta(days=settings.default_retention_days),
    )
    session.add(artifact)
    session.flush()

    upload.artifact_id = artifact.id
    upload.checksum_sha256 = stored.checksum_sha256
    upload.status = UploadStatus.COMPLETED
    upload.completed_at = datetime.now(UTC)
    session.flush()
    # The artifact holds the bytes now — a hardlink, on one filesystem — so
    # removing the staging name frees the upload's claim without freeing the
    # data.
    store.delete(staging_key(upload.id))
    return artifact


def abort_upload(session: Session, upload: Upload, *, store: PosixArtifactStore) -> Upload:
    """Give up on an upload and release its disk.

    Allowed only while it is open. A completed upload is an artifact, and
    artifacts are deleted through retention, not by cancelling the transfer
    that produced them.
    """
    if upload.status != UploadStatus.OPEN.value:
        raise UploadNotOpen(
            f"This upload is already {upload.status}.", details={"status": upload.status}
        )
    store.delete(staging_key(upload.id))
    upload.status = UploadStatus.ABORTED
    upload.received_bytes = 0
    session.flush()
    return upload


# --- uploads as run inputs -------------------------------------------------

REFERENCE_PREFIX = "upload:"
# Where a staged input lands inside the run's workspace. Relative, because the
# runner resolves it against `BP_WORKSPACE` and the container has no idea
# where the host keeps its artifacts.
STAGED_DIR = "inputs"


@dataclass(frozen=True, slots=True)
class StagedInput:
    """One uploaded file a run needs put where its containers can read it."""

    artifact_id: uuid.UUID
    path: str

    def as_dict(self) -> dict[str, str]:
        return {"artifact_id": str(self.artifact_id), "path": self.path}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> StagedInput:
        return cls(artifact_id=uuid.UUID(str(raw["artifact_id"])), path=str(raw["path"]))


def is_reference(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(REFERENCE_PREFIX)


def staged_path(upload_id: uuid.UUID, filename: str) -> str:
    return f"{STAGED_DIR}/{upload_id}/{filename}"


def resolve_reference(
    session: Session, value: str, *, requested_by: uuid.UUID, is_admin: bool = False
) -> StagedInput:
    """Turn `upload:<id>` into the artifact and the path a task will read.

    Resolved at submission so that a missing or expired upload is refused
    while the researcher is still looking at the form, rather than becoming a
    container that cannot find its input an hour into the queue.
    """
    raw = value[len(REFERENCE_PREFIX) :]
    try:
        upload_id = uuid.UUID(raw)
    except ValueError:
        raise ValidationFailed(f"'{value}' is not an upload reference.") from None

    upload = find_upload(session, upload_id, actor_id=requested_by, is_admin=is_admin)
    if upload is None:
        raise ValidationFailed("That upload does not exist, or does not belong to you.")
    if upload.status != UploadStatus.COMPLETED.value or upload.artifact_id is None:
        raise ValidationFailed(
            f"'{upload.filename}' was never finished uploading ({upload.status}), "
            "so it cannot be used as an input."
        )
    artifact = session.get(Artifact, upload.artifact_id)
    if artifact is None or artifact.deleted_at is not None or artifact.purged_at is not None:
        raise ValidationFailed(
            f"'{upload.filename}' has been removed by retention. Upload it again."
        )
    return StagedInput(artifact_id=artifact.id, path=staged_path(upload.id, upload.filename))


def staged_inputs_for_run(session: Session, run_id: uuid.UUID) -> list[StagedInput]:
    """What this run needs staged, as recorded when it was submitted."""
    run = session.get(Run, run_id)
    if run is None:
        return []
    raw = (run.compiled_run_spec or {}).get("staged_inputs") or []
    return [StagedInput.from_dict(item) for item in raw]


def stage_inputs(
    plan: list[StagedInput],
    *,
    session: Session,
    root: Path,
    store: PosixArtifactStore,
) -> list[str]:
    """Put a run's uploaded inputs where its containers will look for them.

    Done by the worker rather than at submission, because the workspace is the
    worker's to create and destroy, and a run may wait in the queue for a long
    time before anything needs the bytes on that host.

    Hardlinked where the filesystems allow it, so a forty-gigabyte input is
    not copied once per run. Idempotent: every attempt of every task in the
    run calls this, and the second call finds the file already there.
    """
    placed: list[str] = []
    for item in plan:
        destination = root / item.path
        if destination.exists():
            continue
        artifact = session.get(Artifact, item.artifact_id)
        if artifact is None or artifact.purged_at is not None:
            raise UploadRejected(
                f"The uploaded input for '{item.path}' is no longer in the store.",
                details={"artifact_id": str(item.artifact_id)},
            )
        source = store.path_for(artifact.storage_key)
        if not source.is_file():
            raise UploadRejected(
                f"The bytes of the uploaded input '{artifact.filename}' are missing.",
                details={"artifact_id": str(item.artifact_id)},
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(source, destination)
        except OSError:
            # A different filesystem, or a store that does not allow links.
            # Copying costs the disk twice for the length of the run, which is
            # worth saying out loud but is not worth refusing to run over.
            shutil.copy2(source, destination)
        placed.append(item.path)
    return placed
