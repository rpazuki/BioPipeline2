"""Registering the institutional paths a task container may read.

Until a root is registered, `readable_roots` is empty, `DirectoryFanOut`
refuses every path, and nothing can be submitted that names a file the lab
already has. So this is the first thing a deployment does — and it was the one
thing that could only be done by hand-written SQL.

**The attestation is the product here, not the path.** ADR 0013 decided that
the platform reads shared storage as a *service account*, which is safe only
because a root is exposed solely within a project whose members already share
it. That is a judgement about a filesystem the platform cannot see the ACLs of,
so it is recorded against a person, with what they were attesting, and it can
be withdrawn. The database refuses to hold an unattested service-account root
at all.

Everything else here is refusing paths. An admin who can attest a root can
already reach a great deal, so these are guards against a slip rather than a
security boundary — but the slips they catch are the ones nobody would notice:
a root that silently mounts nothing, a root whose flags are a lie because
another root already exposes it, and a root that would hand every task
container a read-only view of every other run's outputs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.pipelines import default_project_id
from app.domain.errors import ValidationFailed
from app.infrastructure.db.models import SharedStorageRoot
from app.settings import Settings

IDENTIFIER = re.compile(r"^[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?$")

# Directories that are the operating system rather than anybody's data. Not a
# security boundary -- an admin can still name `/srv` -- but naming one of
# these is a mistake rather than an intention, and mounting it into every task
# container is not a mistake anyone would spot afterwards.
SYSTEM_PATHS = (
    "/",
    "/bin",
    "/boot",
    "/dev",
    "/etc",
    "/lib",
    "/lib64",
    "/proc",
    "/root",
    "/run",
    "/sbin",
    "/sys",
    "/usr",
)


class RootRejected(ValidationFailed):
    """A path that must not become a mount."""

    code = "storage_root.rejected"


@dataclass(frozen=True, slots=True)
class RootView:
    """A root, and whether it is currently doing anything."""

    root: SharedStorageRoot
    visible: bool
    """Whether the path is a directory the platform can see right now.

    A root whose share has been unmounted is skipped silently by
    `shared_root_mounts`, which is the correct behaviour there and an invisible
    one everywhere else. Saying it here is what turns "submissions started
    failing" into "that root is gone".
    """

    @property
    def in_use(self) -> bool:
        """Whether tasks will actually be given this root."""
        return (
            self.visible
            and self.root.readable
            and self.root.attested_at is not None
            and self.root.revoked_at is None
        )


def _overlaps(one: Path, other: Path) -> bool:
    """Whether mounting either would expose the other."""
    return one == other or one.is_relative_to(other) or other.is_relative_to(one)


def _platform_paths(settings: Settings) -> dict[str, Path]:
    """Where the platform keeps its own state.

    Named rather than listed, because the refusal has to say *which* one was
    hit: "that is the artifact store" is actionable and "that path is reserved"
    is not.
    """
    paths = {
        "the artifact store": Path(settings.artifact_root),
        "the workspace root": Path(settings.workspace_root),
        "the component library": Path(settings.component_library_root),
    }
    for library in settings.task_library_paths:
        paths[f"a mounted science library ({library})"] = Path(library)
    return paths


def validate_root_path(path: str, *, settings: Settings, existing: list[Path]) -> Path:
    """The path a root may have, or why it may not have this one."""
    if not path.strip():
        raise RootRejected("A storage root needs a path.")
    candidate = Path(path.strip())
    if not candidate.is_absolute():
        raise RootRejected(
            f"'{path}' is relative. A root has to be absolute, because a relative "
            "one would resolve against whatever directory a worker happened to "
            "start in."
        )
    # Not `.resolve()`: following symlinks here would register the target and
    # silently expose something other than what was typed.
    candidate = Path(candidate.as_posix().rstrip("/") or "/")

    for denied in SYSTEM_PATHS:
        system = Path(denied)
        if candidate == system or system.is_relative_to(candidate):
            raise RootRejected(
                f"'{candidate}' is, or contains, the system directory '{denied}'. "
                "Mounting it would give every task container a read-only copy "
                "of the machine."
            )

    for what, reserved in _platform_paths(settings).items():
        if _overlaps(candidate, reserved):
            raise RootRejected(
                f"'{candidate}' overlaps {what} ({reserved}). A task container "
                "would be able to read data belonging to other runs, which is "
                "the opposite of what a shared input root is for."
            )

    for other in existing:
        if _overlaps(candidate, other):
            raise RootRejected(
                f"'{candidate}' overlaps the registered root '{other}'. Two "
                "overlapping roots cannot have different permissions in "
                "practice: whichever is mounted exposes the other, so the "
                "narrower one's settings would be a fiction."
            )

    if not candidate.is_dir():
        raise RootRejected(
            f"'{candidate}' is not a directory the platform can see. Checked "
            "from the API process, which shares a filesystem with the workers "
            "in this deployment — a root that cannot be seen would be "
            "registered, listed, and mounted into nothing."
        )
    return candidate


def register_root(
    session: Session,
    *,
    root_id: str,
    label: str,
    root_path: str,
    attested_by: UUID,
    attestation_note: str,
    settings: Settings,
    readable: bool = True,
    writable: bool = False,
    identity_mode: str = "service_account",
    metadata: dict[str, Any] | None = None,
) -> SharedStorageRoot:
    """Allowlist a path, on somebody's stated authority.

    ``attestation_note`` is required rather than optional: an attestation with
    nothing written in it is a checkbox, and the thing being recorded is
    *what* was checked — which share, whose members, against which ACL.
    """
    if not IDENTIFIER.match(root_id):
        raise RootRejected(
            f"'{root_id}' is not a usable identifier. Use lowercase letters, "
            "digits and hyphens, starting and ending with a letter or digit."
        )
    if session.get(SharedStorageRoot, root_id) is not None:
        raise RootRejected(f"A storage root called '{root_id}' already exists.")
    if not label.strip():
        raise RootRejected("Give the root a label people will recognise.")
    if not readable and not writable:
        raise RootRejected("A root that is neither readable nor writable does nothing.")
    if not attestation_note.strip():
        raise RootRejected(
            "Record what you are attesting: which share this is, and why "
            "everyone who can reach it through the platform already has "
            "access to it. This is the part nobody can reconstruct later."
        )

    existing = [
        Path(row.root_path)
        for row in session.execute(select(SharedStorageRoot)).scalars()
        if row.revoked_at is None
    ]
    path = validate_root_path(root_path, settings=settings, existing=existing)

    root = SharedStorageRoot(
        id=root_id,
        project_id=default_project_id(session),
        label=label.strip(),
        root_path=str(path),
        readable=readable,
        writable=writable,
        identity_mode=identity_mode,
        attested_by=attested_by,
        attested_at=datetime.now(UTC),
        attestation_note=attestation_note.strip(),
        metadata_=metadata or {},
    )
    session.add(root)
    session.flush()
    return root


def list_roots(session: Session) -> list[RootView]:
    roots = session.execute(select(SharedStorageRoot).order_by(SharedStorageRoot.id)).scalars()
    return [RootView(root=root, visible=Path(root.root_path).is_dir()) for root in roots]


def get_root(session: Session, root_id: str) -> RootView | None:
    root = session.get(SharedStorageRoot, root_id)
    if root is None:
        return None
    return RootView(root=root, visible=Path(root.root_path).is_dir())


def revoke(session: Session, root_id: str, *, actor_id: UUID, reason: str) -> SharedStorageRoot:
    """Stop offering a root, without forgetting it existed.

    Withdrawn rather than deleted, and the attestation stays where it is: who
    signed for this root is part of the record whether or not it is still
    mounted, and a delivery that went here still names it.

    Takes effect on a worker's next start, not immediately — the mounts are
    resolved once per process. Anything already running keeps the root it was
    given, which is why this is a withdrawal and not a revocation of access
    that has already happened.
    """
    root = session.get(SharedStorageRoot, root_id)
    if root is None:
        raise ValidationFailed(f"No storage root called '{root_id}'.")
    if root.revoked_at is not None:
        return root
    root.readable = False
    root.writable = False
    root.revoked_at = datetime.now(UTC)
    root.metadata_ = {
        **(root.metadata_ or {}),
        "revoked_by": str(actor_id),
        "revoked_reason": reason.strip()[:512],
    }
    session.flush()
    return root


def reinstate(
    session: Session,
    root_id: str,
    *,
    actor_id: UUID,
    attestation_note: str,
    settings: Settings,
    readable: bool = True,
    writable: bool = False,
) -> SharedStorageRoot:
    """Put a withdrawn root back, on a fresh attestation.

    Not a simple undo: the path is re-checked and the attestation is made
    again, because the reason it was withdrawn may have been that the share's
    permissions changed. Re-signing the original statement would be recording
    a check nobody performed.
    """
    root = session.get(SharedStorageRoot, root_id)
    if root is None:
        raise ValidationFailed(f"No storage root called '{root_id}'.")
    if root.revoked_at is None:
        raise ValidationFailed(f"Storage root '{root_id}' has not been withdrawn.")
    if not attestation_note.strip():
        raise RootRejected("Record what you are attesting, as at first registration.")
    if not readable and not writable:
        raise RootRejected("A root that is neither readable nor writable does nothing.")

    others = [
        Path(row.root_path)
        for row in session.execute(select(SharedStorageRoot)).scalars()
        if row.id != root_id and row.revoked_at is None
    ]
    validate_root_path(root.root_path, settings=settings, existing=others)

    root.readable = readable
    root.writable = writable
    root.revoked_at = None
    root.attested_by = actor_id
    root.attested_at = datetime.now(UTC)
    root.attestation_note = attestation_note.strip()[:512]
    session.flush()
    return root
