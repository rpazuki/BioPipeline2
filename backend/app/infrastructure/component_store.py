"""Store component libraries and immutable source snapshots under one directory."""

from __future__ import annotations

import fcntl
import hashlib
import os
import re
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from app.domain.authoring import ComponentLibrary
from app.domain.errors import Conflict, NotFound, ValidationFailed
from app.infrastructure.pipeline_loader import parse_library


def source_digest(source: str) -> str:
    """Identify an exact component source, including comments and whitespace."""
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def validate_source(source: str) -> ComponentLibrary:
    """Validate graph structure and require unique names for nonempty step lists."""
    library = parse_library(source)
    if not library.graphs or any(not steps for steps in library.graphs.values()):
        raise ValidationFailed("Each component graph must contain at least one step.")
    for graph, steps in library.graphs.items():
        if len({step.name for step in steps}) != len(steps):
            raise ValidationFailed(f"Graph '{graph}' contains duplicate step names.")
    return library


class ComponentStore:
    """Manage editable library files and retain their exact saved sources.

    Snapshot references can be used by the existing directory library loader.
    Saving uses a process lock and compares the expected source digest to
    prevent one editor from silently overwriting another editor's changes.
    """

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).resolve()

    def _path(self, reference: str) -> Path:
        candidate = (self.root / reference).resolve()
        if not candidate.is_relative_to(self.root) or candidate == self.root:
            raise ValidationFailed("Component path is outside the component library directory.")
        return candidate

    def _name(self, name: str) -> str:
        path = PurePosixPath(name)
        if (
            not name
            or len(name) > 200
            or "\\" in name
            or path.is_absolute()
            or path.as_posix() != name
            or any(part.startswith(".") for part in path.parts)
            or not re.fullmatch(r"[A-Za-z0-9_./-]+\.ya?ml", name)
        ):
            raise ValidationFailed("Use a relative component filename ending in .yaml or .yml.")
        self._path(name)
        return name

    def _revision_reference(self, name: str, digest: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValidationFailed("Invalid component revision identifier.")
        key = hashlib.sha256(name.encode("utf-8")).hexdigest()
        return f".revisions/{key}/{digest}.yaml"

    def read(self, name: str, revision: str | None = None) -> dict[str, Any]:
        """Read current source or a saved snapshot without importing its Python code."""
        name = self._name(name)
        reference = self._revision_reference(name, revision) if revision else name
        path = self._path(reference)
        if not path.is_file():
            raise NotFound("Component library or revision does not exist.")
        source = path.read_bytes().decode("utf-8")
        digest = source_digest(source)
        if revision and digest != revision:
            raise ValidationFailed("The saved component snapshot failed its integrity check.")
        if revision is None:
            snapshot = self._revision_reference(name, digest)
            if self._path(snapshot).is_file():
                reference = snapshot
        try:
            library = validate_source(source)
            graphs = sorted(library.graphs)
            error = None
        except ValidationFailed as rejected:
            graphs = []
            error = rejected.message
        return {
            "name": name,
            "digest": digest,
            "reference": reference,
            "source_text": source,
            "graphs": graphs,
            "error": error,
        }

    def list(self) -> list[dict[str, Any]]:
        """List current libraries, retaining invalid files for correction in the editor."""
        if not self.root.exists():
            return []
        result = []
        for path in sorted(self.root.rglob("*")):
            name = path.relative_to(self.root).as_posix()
            if any(part.startswith(".") for part in Path(name).parts):
                continue
            if path.suffix in {".yaml", ".yml"} and path.is_file():
                result.append(self.read(name))
        return result

    def revisions(self, name: str) -> list[dict[str, Any]]:
        """List immutable snapshots, including an unsnapshotted current source."""
        current = self.read(name)
        directory = self._path(self._revision_reference(name, current["digest"])).parent
        rows = []
        if directory.exists():
            for path in sorted(
                directory.glob("*.yaml"), key=lambda p: p.stat().st_mtime_ns, reverse=True
            ):
                rows.append(self.read(name, path.stem))
        if not any(row["digest"] == current["digest"] for row in rows):
            rows.insert(0, current)
        return rows

    def _write(self, reference: str, source: str) -> None:
        path = self._path(reference)
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=".component-")
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="") as stream:
                stream.write(source)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _snapshot(self, name: str, source: str) -> str:
        reference = self._revision_reference(name, source_digest(source))
        path = self._path(reference)
        if path.exists():
            if path.read_bytes().decode("utf-8") != source:
                raise Conflict("A saved component snapshot has conflicting contents.")
        else:
            self._write(reference, source)
        return reference

    def save(self, name: str, source: str, expected_digest: str | None) -> dict[str, Any]:
        """Validate and save source, preserving prior versions and refusing stale edits."""
        name = self._name(name)
        validate_source(source)
        self.root.mkdir(parents=True, exist_ok=True)
        with self._path(".component-store.lock").open("a") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            path = self._path(name)
            previous = path.read_bytes().decode("utf-8") if path.is_file() else None
            actual = source_digest(previous) if previous is not None else None
            if actual != expected_digest:
                raise Conflict("This component changed. Reload its source before saving again.")
            if previous is not None:
                self._snapshot(name, previous)
            reference = self._snapshot(name, source)
            self._write(name, source)
        return self.read(name, source_digest(source)) | {"reference": reference}

    def remove(self, name: str, expected_digest: str) -> None:
        """Remove an editable library while retaining its immutable source snapshot."""
        name = self._name(name)
        self.root.mkdir(parents=True, exist_ok=True)
        with self._path(".component-store.lock").open("a") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            path = self._path(name)
            if not path.is_file():
                raise NotFound("Component library does not exist.")
            source = path.read_bytes().decode("utf-8")
            if source_digest(source) != expected_digest:
                raise Conflict("This component changed. Reload it before removing it.")
            self._snapshot(name, source)
            path.unlink()

    def restore_snapshot(self, name: str, revision: str, expected_digest: str | None) -> None:
        """Restore exact retained source after a failed transaction, including invalid drafts."""
        snapshot = self.read(name, revision)
        with self._path(".component-store.lock").open("a") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            path = self._path(name)
            current = path.read_bytes().decode("utf-8") if path.is_file() else None
            actual = source_digest(current) if current is not None else None
            if actual != expected_digest:
                raise Conflict("The component changed before its source could be restored.")
            self._write(name, snapshot["source_text"])
