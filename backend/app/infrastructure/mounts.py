"""Which host paths a task container may see.

A pipeline names its inputs by path — `{data_root}/plate_01.csv` — and that
path is written by an author who is thinking about the filesystem the lab
already has. For it to mean the same thing inside the container as outside,
the root has to be mounted **at its own path**. Mounting it somewhere else
would mean rewriting every path in every task spec, and any path the platform
failed to rewrite would silently point at nothing.

Only attested, readable roots are offered, and only read-only. ADR 0013
decided that the platform reads shared storage as a service account, which is
safe only because a root is exposed solely within the project whose members
already share it — and the attestation is what makes that a fact somebody
signed rather than an assumption. A root the database would refuse to hold
unattested must not become a mount here either.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.db.models import SharedStorageRoot


def shared_root_mounts(session: Session) -> dict[str, str]:
    """Host path -> container path, for every root a task may read.

    Writable roots are *not* included. Output delivery copies into them from
    the worker, after the run has been verified, rather than letting task code
    write to institutional storage directly — a task that can write there can
    overwrite somebody else's results with a bug.
    """
    roots = session.execute(
        select(SharedStorageRoot).where(
            SharedStorageRoot.readable.is_(True),
            SharedStorageRoot.attested_at.is_not(None),
        )
    ).scalars()

    mounts: dict[str, str] = {}
    for root in roots:
        path = Path(root.root_path)
        # A relative root would resolve against the worker's working directory,
        # which is not a thing a deployment should depend on.
        if not path.is_absolute() or not path.is_dir():
            continue
        mounts[str(path)] = str(path)
    return mounts


def readable_roots(session: Session) -> tuple[Path, ...]:
    """The roots a submission may name.

    The same set the mounts come from, and for the same reason: a path a task
    container will not be able to see is not a path a submission should be
    allowed to fan out over. Deriving both from one query keeps them from
    drifting apart, which would produce a run that builds and then fails inside
    every container.
    """
    return tuple(Path(path) for path in sorted(shared_root_mounts(session)))
