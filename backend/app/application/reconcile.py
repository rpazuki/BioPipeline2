"""Does the database still describe the disks?

Everything else in this system is written so that the two cannot drift: bytes
are written before the row that promises them, and the row survives the bytes
when they go. This is the check that the discipline held -- after a restore,
after a crash, after an operator moved something by hand.

Two kinds of drift, and they are not equally serious.

**Missing bytes are a lie.** A row that says a result is downloadable when the
file is gone is the failure that matters: somebody clicks a link and the
platform, not the disk, is what let them down. Phase 9's acceptance is that a
restored deployment reports none of these.

**Orphans are only waste.** A directory no row points at costs disk and
nothing else. A backup taken database-first and artifacts-second produces them
by design, which is why a restore drill is *expected* to end with orphans and
must not be judged a failure for it.

Run this on the host that holds the roots. Artifact and environment roots are
usually shared; a workspace root is not, so a workspace is checked for waste
only and never for absence -- a workspace is an execution convenience, not a
record of anything (ADR 0012).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.infrastructure.reclaim import OutsideRoot, remove_within, size_of

ARTIFACT = "artifact"
GENERATION = "generation"
UPLOAD = "upload"
WORKSPACE = "workspace"

MISSING = "missing"
ORPHAN = "orphan"


@dataclass(frozen=True, slots=True)
class Finding:
    """One disagreement between a table and a disk."""

    kind: str
    trouble: str
    reference: str
    detail: str
    path: str = ""
    size_bytes: int = 0

    def __str__(self) -> str:
        size = f" ({self.size_bytes / 1024**2:.1f} MiB)" if self.size_bytes else ""
        return f"{self.kind} {self.trouble}: {self.reference} -- {self.detail}{size}"


@dataclass(frozen=True, slots=True)
class Reconciliation:
    findings: tuple[Finding, ...] = ()
    inspected: Mapping[str, int] = field(default_factory=dict)

    @property
    def missing(self) -> tuple[Finding, ...]:
        return tuple(item for item in self.findings if item.trouble == MISSING)

    @property
    def orphans(self) -> tuple[Finding, ...]:
        return tuple(item for item in self.findings if item.trouble == ORPHAN)

    @property
    def reclaimable_bytes(self) -> int:
        return sum(item.size_bytes for item in self.orphans)

    def summary(self) -> str:
        counts = ", ".join(f"{count} {name}" for name, count in sorted(self.inspected.items()))
        if not self.findings:
            return f"nothing to report; inspected {counts}"
        freed = self.reclaimable_bytes / 1024**3
        return (
            f"{len(self.missing)} missing, {len(self.orphans)} orphan "
            f"({freed:.2f} GiB reclaimable); inspected {counts}"
        )


def _directories(root: Path) -> Iterator[Path]:
    if not root.is_dir():
        return
    for child in sorted(root.iterdir()):
        if child.is_dir() and not child.is_symlink():
            yield child


def _as_uuid(name: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(name)
    except ValueError:
        return None


# --- the checks ------------------------------------------------------------


def _artifacts(session: Session, root: Path) -> Iterator[Finding]:
    """Rows that promise bytes, and directories no row claims."""
    live = session.execute(
        text(
            "SELECT id, run_id, storage_key FROM artifacts "
            "WHERE deleted_at IS NULL AND purged_at IS NULL"
        )
    ).all()
    keys = {row.storage_key for row in live}
    for row in live:
        if not (root / row.storage_key).exists():
            yield Finding(
                kind=ARTIFACT,
                trouble=MISSING,
                reference=str(row.id),
                detail=f"no bytes at '{row.storage_key}'",
            )

    claimed_runs = {str(row.run_id) for row in live if row.run_id}
    for directory in _directories(root / "runs"):
        if directory.name in claimed_runs:
            continue
        yield Finding(
            kind=ARTIFACT,
            trouble=ORPHAN,
            reference=f"runs/{directory.name}",
            detail="no live artifact belongs to this run",
            path=str(directory),
            size_bytes=size_of(directory),
        )

    # `uploads/<id>/<filename>` for what an upload became, and
    # `uploads/staging/<id>` for one still being received.
    open_uploads = {
        str(row.id)
        for row in session.execute(text("SELECT id FROM uploads WHERE status = 'open'")).all()
    }
    for directory in _directories(root / "uploads"):
        if directory.name == "staging":
            continue
        prefix = f"uploads/{directory.name}/"
        if any(key.startswith(prefix) for key in keys):
            continue
        yield Finding(
            kind=UPLOAD,
            trouble=ORPHAN,
            reference=f"uploads/{directory.name}",
            detail="no live artifact was made from this upload",
            path=str(directory),
            size_bytes=size_of(directory),
        )

    staging = root / "uploads" / "staging"
    if staging.is_dir():
        for child in sorted(staging.iterdir()):
            if child.name in open_uploads:
                continue
            yield Finding(
                kind=UPLOAD,
                trouble=ORPHAN,
                reference=f"uploads/staging/{child.name}",
                detail="no upload is still being received into this file",
                path=str(child),
                size_bytes=size_of(child),
            )


def _generations(session: Session, root: Path) -> Iterator[Finding]:
    """Environment builds: rows whose directory is gone, and the reverse.

    The second half is what the janitor cannot see. It removes what rows
    name, so a directory left by a build that died before recording its path
    is invisible to it and would sit there for ever.
    """
    rows = session.execute(
        text(
            "SELECT id, environment_id, generation_path, purged_at "
            "FROM environment_generations WHERE generation_path <> ''"
        )
    ).all()
    known = {str(row.id): row for row in rows}
    for row in rows:
        if row.purged_at is not None:
            continue
        if not Path(row.generation_path).is_dir():
            yield Finding(
                kind=GENERATION,
                trouble=MISSING,
                reference=str(row.id),
                detail=f"no directory at '{row.generation_path}'",
            )

    for environment in _directories(root):
        for directory in _directories(environment):
            recorded = known.get(directory.name)
            if recorded is not None and recorded.purged_at is None:
                continue
            reason = (
                "the row says this was already reclaimed"
                if recorded is not None
                else "no generation row points here"
            )
            yield Finding(
                kind=GENERATION,
                trouble=ORPHAN,
                reference=f"{environment.name}/{directory.name}",
                detail=reason,
                path=str(directory),
                size_bytes=size_of(directory),
            )


def _workspaces(session: Session, root: Path) -> Iterator[Finding]:
    """Scratch space no run is using.

    Waste only. A workspace that is gone is the janitor working, not a record
    lost, so absence is never reported here.
    """
    live = {
        str(row.run_id)
        for row in session.execute(
            text("SELECT run_id FROM workspaces WHERE status = 'active' AND deleted_at IS NULL")
        ).all()
    }
    for directory in _directories(root):
        if directory.name in live or _as_uuid(directory.name) is None:
            continue
        yield Finding(
            kind=WORKSPACE,
            trouble=ORPHAN,
            reference=directory.name,
            detail="no active workspace belongs to this run",
            path=str(directory),
            size_bytes=size_of(directory),
        )


def reconcile(
    session: Session,
    *,
    artifact_root: Path | str,
    environment_root: Path | str,
    workspace_root: Path | str,
) -> Reconciliation:
    """Compare every table that names a path against the paths it names."""
    artifacts = Path(artifact_root)
    environments = Path(environment_root)
    workspaces = Path(workspace_root)

    findings = [
        *_artifacts(session, artifacts),
        *_generations(session, environments),
        *_workspaces(session, workspaces),
    ]
    inspected = {
        "artifact rows": int(
            session.execute(
                text(
                    "SELECT count(*) FROM artifacts WHERE deleted_at IS NULL AND purged_at IS NULL"
                )
            ).scalar_one()
        ),
        "generation rows": int(
            session.execute(text("SELECT count(*) FROM environment_generations")).scalar_one()
        ),
        "workspace rows": int(
            session.execute(text("SELECT count(*) FROM workspaces")).scalar_one()
        ),
    }
    return Reconciliation(findings=tuple(findings), inspected=inspected)


def reclaim_orphans(
    findings: Iterable[Finding],
    *,
    artifact_root: Path | str,
    environment_root: Path | str,
    workspace_root: Path | str,
) -> tuple[int, int, tuple[str, ...]]:
    """Remove the waste. Returns (removed, bytes freed, refused paths).

    Only orphans: a *missing* finding is a row whose bytes are already gone,
    and there is nothing there to remove. Nothing here writes to the database
    -- an operator reclaiming disk must not also be silently rewriting the
    record of what happened.
    """
    roots = {
        ARTIFACT: Path(artifact_root),
        UPLOAD: Path(artifact_root),
        GENERATION: Path(environment_root),
        WORKSPACE: Path(workspace_root),
    }
    removed = 0
    freed = 0
    refused: list[str] = []
    for finding in findings:
        if finding.trouble != ORPHAN or not finding.path:
            continue
        try:
            if remove_within(finding.path, root=roots[finding.kind]):
                removed += 1
                freed += finding.size_bytes
        except OutsideRoot:
            refused.append(finding.path)
        except OSError:
            refused.append(finding.path)
    return removed, freed, tuple(refused)
