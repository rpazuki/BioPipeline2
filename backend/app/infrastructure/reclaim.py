"""Removing a directory that a database row named.

Every reclamation in this system works the same way: something in Postgres
says where bytes are, and a sweep removes them. That makes the path an
*input*, and an input is exactly what a destructive operation must not trust
blindly -- a row edited by hand, a restored dump from a host with a different
layout, or a column somebody migrated wrongly would otherwise aim `rmtree` at
whatever it liked.

One implementation, used by the artifact store's callers, the environment
janitor and the reconciler, so the check cannot be present in one sweep and
forgotten in the next.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from app.domain.errors import DomainError


class OutsideRoot(DomainError):
    """A path a sweep was asked to remove that is not inside its root."""

    code = "storage.outside_root"


def within(path: Path | str, root: Path | str) -> Path:
    """Resolve `path` and refuse it unless it is strictly inside `root`.

    Symlinks are resolved first, so a directory that merely *points* outside
    the root is refused as well. The root itself is refused: removing it would
    take every other deployment's data with it.
    """
    resolved = Path(path).expanduser().resolve(strict=False)
    anchor = Path(root).expanduser().resolve(strict=False)
    if resolved == anchor or not resolved.is_relative_to(anchor):
        raise OutsideRoot(f"'{path}' is not inside '{root}'.")
    return resolved


def remove_within(path: Path | str, *, root: Path | str) -> bool:
    """Remove a file or directory inside `root`. True when one was there.

    Errors are raised rather than swallowed: a removal that failed must never
    be recorded as a removal that happened, because the record is what the
    next sweep believes.
    """
    resolved = within(path, root)
    if not resolved.exists():
        return False
    if resolved.is_dir():
        shutil.rmtree(resolved)
    else:
        resolved.unlink()
    return True


def size_of(path: Path) -> int:
    """Bytes on disk under `path`, for saying what a reclamation would free.

    Best effort: a file that disappears while being walked is one the sweep
    would not have had to remove anyway.
    """
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for child in path.rglob("*"):
        try:
            if child.is_file() and not child.is_symlink():
                total += child.stat().st_size
        except OSError:
            continue
    return total
