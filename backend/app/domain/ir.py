"""The compiled intermediate representation.

Immutable, self-contained, and versioned. A run points at a revision and reads
its IR; it never re-reads the source document and never re-resolves a
component. That is what makes a revision reproducible even if a component
library changes afterwards (ADR 0026).

``IR_VERSION`` is stored with every revision so a later release can tell
whether it is able to execute what an earlier one compiled. A run never
recompiles: compatibility is a read-side decision.
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import DeliveryMode, InputSourceMode

IR_VERSION = "1.0"


class _IR(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


Severity = Literal["error", "warning"]


class Diagnostic(_IR):
    """One compilation problem, located.

    The compiler collects these rather than raising on the first, so an author
    fixing a document sees every problem at once.
    """

    severity: Severity
    code: str = Field(max_length=64)
    message: str = Field(max_length=2048)
    # Dotted path into the document, e.g. "stages.fit.inputs.raw_data".
    location: str = Field(default="", max_length=512)
    # Which matrix row this applies to, when the problem is row-specific.
    variant: dict[str, Any] | None = None

    def __str__(self) -> str:  # pragma: no cover - trivial
        where = f" at {self.location}" if self.location else ""
        return f"[{self.code}]{where}: {self.message}"


class CompiledStep(_IR):
    """One Python call with its parameters fully resolved.

    Parameters may still contain ``{item.*}`` templates: those resolve when the
    fan-out is enumerated at run creation, not at compile time.
    """

    name: str
    package: str
    method: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    # Payload names still referenced after this step runs.
    #
    # Computed by liveness analysis over the stage: the compiler knows which
    # results later steps name, so the runner can release the rest. Without
    # it a stage holds every intermediate until it finishes, and a step that
    # returns a path instead of a DataFrame saves nothing.
    retain: list[str] = Field(default_factory=list)
    # True when any parameter still holds a deferred reference.
    has_deferred: bool = False


class CompiledOutput(_IR):
    key: str
    path: str
    delivery: list[DeliveryMode]
    retention_days: int | None = None
    optional: bool = False
    has_deferred: bool = False


class CompiledFanOut(_IR):
    type: Literal["none", "mapping_file", "folders", "patterns"]
    mapping: str | None = None
    data_dir: str | None = None
    raw_pattern: str | None = None
    meta_pattern: str | None = None


class ComponentPin(_IR):
    """A component as it stood at compile time.

    The digest is over the resolved step list, so an identical graph pins
    identically and a changed library cannot alter an existing revision.
    """

    alias: str
    library: str
    graph: str
    digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class CompiledStage(_IR):
    """One stage of one matrix row."""

    key: str
    """Unique within the revision: stage name plus the matrix row, when there
    is a matrix. This is what task keys are built from."""

    name: str
    variant: dict[str, Any] | None = None
    needs: list[str] = Field(default_factory=list)
    fanout: CompiledFanOut
    inputs: dict[str, Any] = Field(default_factory=dict)
    steps: list[CompiledStep]
    outputs: list[CompiledOutput] = Field(default_factory=list)
    task_class: str = "standard"
    component: ComponentPin | None = None

    @property
    def is_fanned_out(self) -> bool:
        return self.fanout.type != "none"


class CompiledInput(_IR):
    """One public input the run must supply."""

    key: str
    sources: list[InputSourceMode]
    accept: Literal["file", "directory", "value"]
    type_ref: str | None = None
    help: str | None = None
    required: bool = True


class CompiledPipeline(_IR):
    """The whole compiled artefact."""

    ir_version: str = IR_VERSION
    pipeline: str
    title: str | None = None
    description: str | None = None
    inputs: list[CompiledInput] = Field(default_factory=list)
    stages: list[CompiledStage]
    components: list[ComponentPin] = Field(default_factory=list)
    # Stable identity of the graph. Identical source compiles to an identical
    # hash, so the compiler can skip rebuilding and a test can assert
    # determinism.
    graph_hash: str = Field(default="", pattern=r"^(sha256:[0-9a-f]{64})?$")

    def with_hash(self) -> CompiledPipeline:
        """Return a copy carrying the hash of its own content."""
        body = self.model_dump(mode="json", exclude={"graph_hash"})
        encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        digest = hashlib.sha256(encoded).hexdigest()
        return self.model_copy(update={"graph_hash": f"sha256:{digest}"})

    @property
    def stage_keys(self) -> tuple[str, ...]:
        return tuple(stage.key for stage in self.stages)

    def stage(self, key: str) -> CompiledStage | None:
        for stage in self.stages:
            if stage.key == key:
                return stage
        return None


class CompilationResult(_IR):
    """What the compiler returns: an artefact, diagnostics, or both."""

    pipeline: CompiledPipeline | None = None
    diagnostics: list[Diagnostic] = Field(default_factory=list)

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == "error"]

    @property
    def warnings(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == "warning"]

    @property
    def ok(self) -> bool:
        return self.pipeline is not None and not self.errors

    def summary(self) -> str:
        if self.ok:
            assert self.pipeline is not None
            return f"compiled {len(self.pipeline.stages)} stage(s), {len(self.warnings)} warning(s)"
        return f"{len(self.errors)} error(s), {len(self.warnings)} warning(s)"


ComponentResolver = Annotated[Any, "Callable[[str, str], list[Step]] | None"]
