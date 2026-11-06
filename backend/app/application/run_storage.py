"""Measure the files currently retained for a set of runs."""

from __future__ import annotations

import stat
import uuid
from collections import defaultdict
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.infrastructure.db.models import (
    Artifact,
    ArtifactBundle,
    Run,
    RunDelivery,
    SharedStorageRoot,
    Workspace,
)
from app.settings import Settings


def measure_files(locations: list[tuple[Path, str]]) -> tuple[int, bool]:
    """Count regular-file lengths once per inode, without following symbolic links.

    Locations pair a trusted storage root with a relative file or directory.
    Missing files contribute zero. Other access errors mark the measurement
    incomplete, so inaccessible storage cannot be mistaken for an empty run.
    """
    seen: set[tuple[int, int]] = set()
    visited: set[tuple[int, int]] = set()
    total = 0
    complete = True

    def walk(path: Path) -> None:
        nonlocal total, complete
        try:
            info = path.lstat()
            identity = (info.st_dev, info.st_ino)
            if stat.S_ISREG(info.st_mode) and identity not in seen:
                seen.add(identity)
                total += info.st_size
            elif stat.S_ISDIR(info.st_mode) and identity not in visited:
                visited.add(identity)
                for child in path.iterdir():
                    walk(child)
        except FileNotFoundError:
            pass
        except OSError:
            complete = False

    for root, key in locations:
        relative = Path(key)
        if not key or relative == Path(".") or relative.is_absolute() or ".." in relative.parts:
            complete = False
            continue
        try:
            anchor = root.resolve()
            path = anchor
            for part in relative.parts:
                path = path / part
                if path.is_symlink():
                    break
            else:
                walk(path)
        except OSError:
            complete = False
    return total, complete


def retained_storage(
    session: Session, runs: list[Run], settings: Settings
) -> dict[uuid.UUID, tuple[int, bool]]:
    """Measure workspaces, stored files, uploaded inputs, bundles, and delivered copies.

    Metadata is fetched in batches before walking each run's files. Uploaded
    sources reused by several runs count towards each run; these measurements
    therefore cannot be added to obtain a deployment-wide storage total.
    """
    if not runs:
        return {}
    identifiers = [run.id for run in runs]
    artifact_root = Path(settings.artifact_root)
    workspace_root = Path(settings.workspace_root)
    locations = {
        run.id: [(workspace_root, str(run.id)), (artifact_root, f"runs/{run.id}")] for run in runs
    }
    input_runs: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for run in runs:
        for item in run.compiled_run_spec.get("staged_inputs", []):
            input_runs[uuid.UUID(item["artifact_id"])].add(run.id)
    for workspace in session.scalars(select(Workspace).where(Workspace.run_id.in_(identifiers))):
        locations[workspace.run_id].append((workspace_root, workspace.root_key))
    for artifact in session.scalars(
        select(Artifact).where(or_(Artifact.run_id.in_(identifiers), Artifact.id.in_(input_runs)))
    ):
        if artifact.storage_backend != "posix" or artifact.kind == "shared_input_reference":
            continue
        owners = input_runs.get(artifact.id, set()).copy()
        if artifact.run_id in locations:
            owners.add(artifact.run_id)
        for identifier in owners:
            locations[identifier].append((artifact_root, artifact.storage_key))
    for bundle in session.scalars(
        select(ArtifactBundle).where(ArtifactBundle.run_id.in_(identifiers))
    ):
        locations[bundle.run_id].extend(
            [
                (artifact_root, f"bundles/{bundle.id}"),
                (artifact_root, f"bundles/staging/{bundle.id}.zip.partial"),
                (artifact_root, f"bundles/locks/{bundle.id}"),
            ]
        )
    for delivery, root in session.execute(
        select(RunDelivery, SharedStorageRoot)
        .join(SharedStorageRoot, RunDelivery.target_root_id == SharedStorageRoot.id)
        .where(
            RunDelivery.run_id.in_(identifiers),
            RunDelivery.mode == "shared",
            RunDelivery.target_path.is_not(None),
        )
    ):
        anchor = Path(root.root_path)
        try:
            relative = Path(delivery.target_path).relative_to(anchor)
        except ValueError:
            # An invalid recorded destination cannot be attributed to this run.
            locations[delivery.run_id].append((anchor, ".."))
            continue
        locations[delivery.run_id].append((anchor, str(relative)))
        for attempt in range(1, delivery.attempts + 1):
            temporary = relative.with_name(f".{relative.name}.incoming-{attempt}")
            locations[delivery.run_id].append((anchor, str(temporary)))
    return {identifier: measure_files(paths) for identifier, paths in locations.items()}
