"""The artifact store: where outputs live once they are no longer scratch.

A workspace is disposable; the artifact store is not. Promotion moves the
boundary: bytes the janitor may delete become bytes a researcher can retrieve,
recorded with a checksum so their integrity is checkable later.

Two choices worth stating.

**Hardlink, then copy.** An output is linked into the store when the workspace
and the store share a filesystem, and copied otherwise. Copying is the obvious
implementation and it doubles the disk cost of every run; with RNA-seq outputs
measured in tens of gigabytes that is the difference between a VM that works
and one that fills up. A hardlink is not a second copy, and because artifacts
are immutable once promoted, sharing the inode is safe.

**Directories stay directories.** Packaging a large output tree into a single
archive is neither fast nor useful, so a directory output is promoted as a
directory plus a manifest of its contents. Producing a convenience archive is
a separate, optional step for outputs small enough to be worth it.
"""

from __future__ import annotations

import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.domain.errors import DomainError
from app.infrastructure.workspace import checksum


class ArtifactStoreError(DomainError):
    code = "artifact.store_failed"


@dataclass(frozen=True, slots=True)
class StoredArtifact:
    storage_key: str
    size_bytes: int
    checksum_sha256: str | None
    is_directory: bool
    linked: bool
    """True when the bytes were shared rather than copied."""


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    relative_path: str
    size_bytes: int
    checksum_sha256: str


class PosixArtifactStore:
    """Artifacts on a mounted POSIX volume."""

    backend = "posix"

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).resolve()

    def key_for(self, *, run_id: uuid.UUID, task_key: str, attempt: int, output_key: str) -> str:
        """Build a storage key.

        Generated entirely from identifiers the platform controls, never from
        a filename a task chose. A retry gets its own key through ``attempt``,
        so a second attempt cannot collide with the first -- which matters
        because live artifacts are unique on their storage key.
        """
        safe_task = safe_segment(task_key)
        safe_output = safe_segment(output_key)
        return f"runs/{run_id}/{safe_task}/attempt-{attempt}/{safe_output}"

    def path_for(self, storage_key: str) -> Path:
        """Resolve a storage key, refusing anything that escapes the root."""
        candidate = (self.root / storage_key).resolve()
        if not candidate.is_relative_to(self.root):
            raise ArtifactStoreError(
                f"Storage key '{storage_key}' resolves outside the artifact root.",
                details={"storage_key": storage_key},
            )
        return candidate

    def put(self, source: Path, storage_key: str) -> StoredArtifact:
        """Promote a file or directory into the store."""
        if not source.exists():
            raise ArtifactStoreError(
                f"Cannot promote '{source}': it does not exist.",
                details={"storage_key": storage_key},
            )
        destination = self.path_for(storage_key)
        destination.parent.mkdir(parents=True, exist_ok=True)

        if source.is_dir():
            size = _copy_tree(source, destination)
            return StoredArtifact(
                storage_key=storage_key,
                size_bytes=size,
                checksum_sha256=None,
                is_directory=True,
                linked=False,
            )

        linked = _link_or_copy(source, destination)
        return StoredArtifact(
            storage_key=storage_key,
            size_bytes=destination.stat().st_size,
            checksum_sha256=checksum(destination),
            is_directory=False,
            linked=linked,
        )

    def manifest(self, storage_key: str) -> list[ManifestEntry]:
        """List a directory artifact's contents, with checksums.

        This is what replaces packaging for a large output: the UI can offer
        per-file download without anyone having to build a multi-gigabyte
        archive first.
        """
        root = self.path_for(storage_key)
        if not root.is_dir():
            return []
        entries: list[ManifestEntry] = []
        for path in sorted(root.rglob("*")):
            if path.is_file() and not path.is_symlink():
                entries.append(
                    ManifestEntry(
                        relative_path=str(path.relative_to(root)),
                        size_bytes=path.stat().st_size,
                        checksum_sha256=checksum(path),
                    )
                )
        return entries

    def delete(self, storage_key: str) -> bool:
        """Remove an artifact's bytes. Idempotent.

        Returns whether anything was there, which is what lets the janitor
        distinguish "purged now" from "already gone" without treating the
        second as an error.
        """
        try:
            path = self.path_for(storage_key)
        except ArtifactStoreError:
            return False
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
            return True
        if path.exists():
            path.unlink(missing_ok=True)
            return True
        return False

    def exists(self, storage_key: str) -> bool:
        try:
            return self.path_for(storage_key).exists()
        except ArtifactStoreError:
            return False


def _link_or_copy(source: Path, destination: Path) -> bool:
    """Hardlink if the filesystems allow it, otherwise copy.

    Returns whether a link was made. ``EXDEV`` means a cross-device link,
    which is the expected case when the workspace and the store are separate
    mounts; anything else is also handled by copying, since falling back is
    always correct and only costs disk.
    """
    destination.unlink(missing_ok=True)
    try:
        os.link(source, destination)
        return True
    except OSError:
        shutil.copy2(source, destination)
        return False


def _copy_tree(source: Path, destination: Path) -> int:
    """Copy a directory, linking the files where possible. Returns total size."""
    total = 0
    for item in sorted(source.rglob("*")):
        if item.is_symlink():
            # Never followed: a link could point outside the workspace, and
            # promoting what it points at would copy bytes the task was not
            # supposed to reach.
            continue
        target = destination / item.relative_to(source)
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif item.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            _link_or_copy(item, target)
            total += target.stat().st_size
    destination.mkdir(parents=True, exist_ok=True)
    return total


def safe_segment(value: str) -> str:
    """Make an identifier safe for a path segment.

    Task keys contain ':' and '#', which are legal in a filename but awkward
    in a URL and on some filesystems. Public, because delivery builds a path
    on somebody else's storage out of the same identifiers and must mangle
    them the same way.
    """
    safe = "".join(
        character if character.isalnum() or character in "-_." else "-" for character in value
    )
    return safe.strip("-") or "unnamed"
