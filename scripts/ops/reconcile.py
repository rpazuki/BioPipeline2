#!/usr/bin/env python3
"""Check that the database still describes the disks, and optionally tidy up.

Run it on the host that holds the storage roots, after a restore, after an
unclean shutdown, or on a schedule.

Exit codes are the contract:

* **0** -- nothing is missing. Orphans may have been reported; they are waste,
  not damage, and a restore taken database-first produces them by design.
* **1** -- at least one row promises bytes that are not there. Something a
  person clicks will fail; this is the failure Phase 9's acceptance is about.
* **2** -- the check itself could not run.

`--reclaim` removes the orphan directories and touches no rows at all. An
operator freeing disk should not also be rewriting the record of what
happened.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.application.reconcile import reclaim_orphans, reconcile
from app.settings import load_settings
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reclaim",
        action="store_true",
        help="remove the orphan directories that were found",
    )
    parser.add_argument(
        "--quiet", action="store_true", help="print the summary line and nothing else"
    )
    parser.add_argument(
        "--limit", type=int, default=25, help="how many findings of each kind to print"
    )
    arguments = parser.parse_args()

    settings = load_settings()
    engine = create_engine(str(settings.database_url), pool_pre_ping=True)
    try:
        with Session(engine) as session:
            result = reconcile(
                session,
                artifact_root=settings.artifact_root,
                environment_root=settings.environment_root,
                workspace_root=settings.workspace_root,
            )
    except OperationalError as error:
        print(f"reconcile: the database is not reachable: {error}", file=sys.stderr)
        return 2

    if not arguments.quiet:
        for trouble in (result.missing, result.orphans):
            for finding in trouble[: arguments.limit]:
                print(finding)
            if len(trouble) > arguments.limit:
                print(f"... and {len(trouble) - arguments.limit} more")

    if arguments.reclaim and result.orphans:
        removed, freed, refused = reclaim_orphans(
            result.orphans,
            artifact_root=settings.artifact_root,
            environment_root=settings.environment_root,
            workspace_root=settings.workspace_root,
        )
        print(f"reclaim: removed {removed}, freed {freed / 1024**3:.2f} GiB")
        for path in refused:
            print(f"reclaim: refused {path}", file=sys.stderr)

    print(f"reconcile: {result.summary()}")
    return 1 if result.missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
