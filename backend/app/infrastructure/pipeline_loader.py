"""Load authoring documents and component libraries from YAML.

The only place the compiler touches a filesystem. Kept out of the domain layer
so compilation stays pure and testable, and so component resolution can later
be pointed at the database instead of a directory without changing the
compiler.

Path containment is enforced here: a component library reference is
author-supplied text, and a pipeline that imports ``../../etc/passwd`` must be
refused rather than read.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError as SchemaError

from app.domain.authoring import ComponentLibrary, PipelineDocument
from app.domain.errors import ValidationFailed


class LibraryNotFound(ValidationFailed):
    code = "component.library_not_found"


def parse_document(text: str) -> PipelineDocument:
    """Parse and structurally validate an authoring document.

    Every rejection leaves here as a :class:`ValidationFailed` carrying located
    problems. A misspelled key is the single most ordinary thing an author
    does, and letting Pydantic's own error escape turned that into an
    unhandled exception -- a 500 from the endpoint whose entire purpose is to
    say what is wrong with the document.
    """
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise ValidationFailed(f"Document is not valid YAML: {error}") from error
    if not isinstance(raw, dict):
        raise ValidationFailed("Document must be a mapping at the top level.")
    try:
        return PipelineDocument.model_validate(raw)
    except SchemaError as error:
        raise ValidationFailed(
            "The document is not a valid pipeline definition.",
            details={"errors": _located(error)},
        ) from error


def _located(error: SchemaError) -> list[dict[str, str]]:
    """Pydantic's errors as the `{path, message}` pairs the API reports.

    The path is dotted rather than a tuple so it reads as a position in the
    document -- `stages.0.steps.1.params` -- which is what makes a message an
    author can act on rather than one they have to go hunting with.
    """
    return [
        {
            "path": ".".join(str(part) for part in item["loc"]),
            "message": item["msg"],
        }
        for item in error.errors()
    ]


def parse_library(text: str) -> ComponentLibrary:
    """Parse a component library.

    Accepts the shape this project already uses -- a ``pipelines:`` list of
    single-key mappings, each a named graph -- as well as a plain
    ``graphs:`` mapping.
    """
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise ValidationFailed(f"Library is not valid YAML: {error}") from error
    if not isinstance(raw, dict):
        raise ValidationFailed("Component library must be a mapping at the top level.")

    if "graphs" in raw:
        try:
            return ComponentLibrary.model_validate(raw)
        except SchemaError as error:
            raise ValidationFailed(
                "The component library is not valid.", details={"errors": _located(error)}
            ) from error

    if "pipelines" in raw:
        graphs: dict[str, Any] = {}
        entries = raw["pipelines"]
        if not isinstance(entries, list):
            raise ValidationFailed("'pipelines' must be a list of named graphs.")
        for entry in entries:
            if not isinstance(entry, dict) or len(entry) != 1:
                raise ValidationFailed(
                    "Each entry under 'pipelines' must be a single-key mapping naming one graph."
                )
            ((name, body),) = entry.items()
            if name in graphs:
                raise ValidationFailed(f"Component library defines '{name}' twice.")
            graphs[name] = _steps_from_processes(name, body)
        try:
            return ComponentLibrary(graphs=graphs)
        except SchemaError as error:
            raise ValidationFailed(
                "The component library is not valid.", details={"errors": _located(error)}
            ) from error

    raise ValidationFailed("Component library must define 'graphs' or 'pipelines'.")


def _steps_from_processes(graph: str, body: Any) -> list[dict[str, Any]]:
    """Convert this project's ``Processes:`` block into step definitions."""
    if not isinstance(body, dict):
        raise ValidationFailed(f"Graph '{graph}' must be a mapping.")
    processes = body.get("Processes") or body.get("processes") or []
    if not isinstance(processes, list):
        raise ValidationFailed(f"Graph '{graph}': 'Processes' must be a list.")
    steps: list[dict[str, Any]] = []
    for entry in processes:
        if not isinstance(entry, dict) or len(entry) != 1:
            raise ValidationFailed(f"Graph '{graph}': each process must be a single-key mapping.")
        ((name, spec),) = entry.items()
        if not isinstance(spec, dict):
            raise ValidationFailed(f"Graph '{graph}': process '{name}' must be a mapping.")
        missing = {"package", "method"} - set(spec)
        if missing:
            raise ValidationFailed(
                f"Graph '{graph}': process '{name}' is missing {', '.join(sorted(missing))}."
            )
        steps.append(
            {
                "name": name,
                "package": spec["package"],
                "method": spec["method"],
                "parameters": spec.get("parameters") or {},
            }
        )
    if not steps:
        raise ValidationFailed(f"Graph '{graph}' defines no processes.")
    return steps


class DirectoryLibraryLoader:
    """Resolves component libraries from a directory, with containment.

    ``root`` is the only place libraries may come from. A reference that
    escapes it is refused, because the reference is author-supplied text.
    """

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).resolve()

    def __call__(self, reference: str) -> ComponentLibrary:
        candidate = (self.root / reference).resolve()
        if not candidate.is_relative_to(self.root):
            raise LibraryNotFound(
                f"Component library '{reference}' resolves outside the library root.",
                details={"reference": reference},
            )
        if not candidate.is_file():
            raise LibraryNotFound(
                f"Component library '{reference}' does not exist.",
                details={"reference": reference},
            )
        return parse_library(candidate.read_text())
