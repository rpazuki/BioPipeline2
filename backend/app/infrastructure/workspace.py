"""Run workspaces: where a task's inputs, outputs and logs live.

A workspace is an execution convenience, never the source of truth. The
artifact table is. Everything here is disposable and rebuildable from
artifacts, which is what makes retry and TTL cleanup safe.

Path containment is the rule this module exists to enforce. Task specs carry
researcher-influenced paths, and a task must not be able to read or write
outside its own workspace. Containment is checked on the host before the
container starts, and again by the task contract's own validators.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.domain.errors import ValidationFailed

PLATFORM_DIR = ".bp"
INPUTS_DIR = "inputs"
OUTPUTS_DIR = "outputs"
LOGS_DIR = "logs"


class WorkspaceError(ValidationFailed):
    code = "workspace.invalid"


@dataclass(frozen=True, slots=True)
class Workspace:
    """One run's scratch space on the host."""

    run_id: uuid.UUID
    root: Path

    @property
    def platform(self) -> Path:
        return self.root / PLATFORM_DIR

    @property
    def inputs(self) -> Path:
        return self.root / INPUTS_DIR

    @property
    def outputs(self) -> Path:
        return self.root / OUTPUTS_DIR

    @property
    def logs(self) -> Path:
        return self.root / LOGS_DIR

    def resolve(self, relative: str) -> Path:
        """Resolve a workspace-relative path, refusing anything that escapes.

        Checked after resolution, so a symlink pointing outward is caught too:
        ``inputs/link -> /etc`` resolves outside the root and is refused even
        though the literal path looks contained.
        """
        if not relative:
            raise WorkspaceError("Path must not be empty.")
        if os.path.isabs(relative) or relative.startswith("\\"):
            raise WorkspaceError(f"Path '{relative}' must be relative to the workspace.")
        candidate = (self.root / relative).resolve()
        root = self.root.resolve()
        if candidate != root and not candidate.is_relative_to(root):
            raise WorkspaceError(
                f"Path '{relative}' resolves outside the workspace.",
                details={"path": relative},
            )
        return candidate

    def total_bytes(self) -> int:
        """Size on disk, following no symlinks."""
        total = 0
        for path in self.root.rglob("*"):
            if path.is_file() and not path.is_symlink():
                total += path.stat().st_size
        return total


def create_workspace(root: Path | str, run_id: uuid.UUID) -> Workspace:
    """Create the directory layout for a run.

    The path is generated from the run id, never from anything a user
    supplied, so two runs cannot collide and a crafted name cannot escape.
    """
    workspace = Workspace(run_id=run_id, root=Path(root).resolve() / str(run_id))
    for directory in (
        workspace.root,
        workspace.platform,
        workspace.inputs,
        workspace.outputs,
        workspace.logs,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    return workspace


def destroy_workspace(workspace: Workspace) -> None:
    """Remove a workspace and everything in it.

    Idempotent, because the janitor may race with a worker that already
    cleaned up.
    """
    shutil.rmtree(workspace.root, ignore_errors=True)


def checksum(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    """SHA-256 of a file, read in chunks so a large artifact does not have to
    fit in memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class CollectedOutput:
    key: str
    relative_path: str
    size_bytes: int
    checksum_sha256: str | None
    is_directory: bool


def collect_outputs(
    workspace: Workspace, declared: list[dict[str, object]]
) -> tuple[list[CollectedOutput], list[str]]:
    """Stat every declared output and report what is missing.

    The worker does this itself rather than trusting the task's own report.
    A task that exits 0 without producing a required output has failed, and
    only the filesystem can settle that.
    """
    collected: list[CollectedOutput] = []
    missing: list[str] = []
    for entry in declared:
        key = str(entry["key"])
        relative = str(entry["path"])
        optional = bool(entry.get("optional", False))
        try:
            path = workspace.resolve(relative)
        except WorkspaceError:
            missing.append(key)
            continue
        if not path.exists():
            if not optional:
                missing.append(key)
            continue
        if path.is_dir():
            size = sum(
                item.stat().st_size
                for item in path.rglob("*")
                if item.is_file() and not item.is_symlink()
            )
            collected.append(CollectedOutput(key, relative, size, None, is_directory=True))
        else:
            collected.append(
                CollectedOutput(
                    key,
                    relative,
                    path.stat().st_size,
                    checksum(path),
                    is_directory=False,
                )
            )
    return collected, missing
