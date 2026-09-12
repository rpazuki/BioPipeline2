"""The task entry-point contract (G20).

This is the boundary between the platform and scientific code. The plan keeps
science packages external *and* moves execution into containers, but never said
how a workflow names a callable across that gap. This module is that contract,
expressed as data.

The shape deliberately mirrors the current system's ``TASK.json`` subprocess
convention, so an existing science function is adapted rather than rewritten.

**Protocol**

1. The worker writes a :class:`TaskSpec` to ``/work/.bp/task.json``.
2. The worker starts the container. The image's entry point reads that file,
   runs **every step of the stage in order, sharing one payload**, and writes
   a :class:`TaskResult` to ``/work/.bp/result.json``.
3. The container exits. Exit code 0 with a valid result means success; any
   other exit code, or a missing or invalid result, means failure.
4. The worker validates every declared output against
   :class:`OutputDeclaration` before promoting anything to an artifact.

**Versioning.** ``contract_version`` is checked by both sides. A task image
declares which versions it supports; the worker refuses to launch on a
mismatch rather than producing undefined behaviour. Never change the meaning
of a field without incrementing it.

**What the container may assume**

* The workspace is mounted read-write at ``/work``.
* ``/work/inputs`` holds materialised inputs; ``/work/outputs`` is where
  declared outputs must be written; ``/work/.bp`` is platform-owned.
* No outbound network unless the workflow revision explicitly requested it.
* Only the environment variables listed in :attr:`TaskSpec.environment`, plus
  ``BP_TASK_SPEC``, ``BP_RESULT_PATH``, and ``BP_WORKSPACE``. The worker
  scrubs everything else, so no platform credential is ever visible.
* The process may run as a non-root user with a read-only root filesystem.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator

CONTRACT_VERSION = "2.0"
"""Version of this contract. Bump on any breaking change to the shapes below.

**2.0** replaced a single ``callable_ref`` with a list of ``steps`` executed in
one container. Version 1.0 ran one container per step, which cannot work: a
pipeline stage passes live Python objects between its steps -- DataFrames, and
in the FBA pipelines a ``cobra.Model`` -- and a fresh process has none of them.
Nothing had been deployed on 1.0, but the version is incremented anyway,
because a contract that quietly redefines itself is worse than one that breaks
loudly.
"""

SUPPORTED_CONTRACT_VERSIONS = frozenset({"2.0"})

WORKSPACE_ROOT = "/work"
PLATFORM_DIR = "/work/.bp"
INPUTS_DIR = "/work/inputs"
OUTPUTS_DIR = "/work/outputs"
TASK_SPEC_PATH = "/work/.bp/task.json"
TASK_RESULT_PATH = "/work/.bp/result.json"

MAX_PATH_LENGTH = 1024


def validate_relative_path(value: str) -> str:
    """Reject anything that is not a plain workspace-relative path.

    Expressed as code rather than a regular expression because containment is
    the rule that keeps a task inside its workspace, and it must be obvious
    what it rejects: absolute paths, Windows drive letters and UNC paths, ``..``
    as a *segment* (not merely as a substring), NUL bytes, and backslashes,
    which some tooling treats as a separator.
    """
    if not value:
        raise ValueError("path must not be empty")
    if len(value) > MAX_PATH_LENGTH:
        raise ValueError(f"path exceeds {MAX_PATH_LENGTH} characters")
    if "\x00" in value:
        raise ValueError("path must not contain a NUL byte")
    if "\\" in value:
        raise ValueError("path must use '/' as its separator")
    if value.startswith("/"):
        raise ValueError("path must be relative to the workspace, not absolute")
    if re.match(r"^[A-Za-z]:", value):
        raise ValueError("path must not carry a drive letter")
    segments = value.split("/")
    if any(segment == ".." for segment in segments):
        raise ValueError("path must not contain a '..' segment")
    if any(segment == "" for segment in segments[:-1]):
        raise ValueError("path must not contain an empty segment")
    return value


RelativePath = Annotated[str, AfterValidator(validate_relative_path)]
Identifier = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_-]*$", max_length=128)]


class _Strict(BaseModel):
    """Reject unknown fields in both directions.

    A task image sending a field the platform does not know, or vice versa, is
    a version mismatch and must fail loudly rather than be ignored.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)


class CallableRef(_Strict):
    """How a task names the science code to run.

    ``python_callable`` is the direct successor to the current system's
    ``labUtils.*`` import-by-name: the image's entry point imports ``module``
    and calls ``attribute``. ``command`` covers tools that are not Python.
    """

    kind: Literal["python_callable", "command"]
    module: str | None = Field(default=None, max_length=512)
    attribute: str | None = Field(default=None, max_length=256)
    command: list[str] | None = Field(default=None, max_length=256)

    @field_validator("module", "attribute")
    @classmethod
    def _no_relative_import(cls, value: str | None) -> str | None:
        if value is not None and (value.startswith(".") or " " in value):
            raise ValueError("must be an absolute dotted name with no spaces")
        return value

    def model_post_init(self, _context: Any) -> None:
        if self.kind == "python_callable":
            if not self.module or not self.attribute:
                raise ValueError("python_callable requires both 'module' and 'attribute'")
        elif not self.command:
            raise ValueError("command requires a non-empty 'command' list")


class StepSpec(_Strict):
    """One call in a stage's graph.

    Steps run in order inside a single container, sharing a payload. A
    parameter whose value matches an earlier step's name receives that step's
    **return value** -- the live object, not a copy and not a path -- which is
    what lets a stage pass a DataFrame from one call to the next.

    A step may instead return a path it has written to. Nothing special is
    needed for that: the value lands in the payload like any other, and the
    next step receives the string and opens it. That is how a stage handling
    data too large to hold in memory is written.
    """

    name: Identifier
    callable_ref: CallableRef
    parameters: dict[str, Any] = Field(default_factory=dict)
    # Payload names still needed after this step returns. Anything not listed
    # is dropped as soon as this step finishes.
    #
    # Without this the payload holds every intermediate result for the whole
    # stage, so returning a path from a later step would not release an
    # earlier step's DataFrame and the memory saving would be imaginary.
    retain: list[str] = Field(default_factory=list)


class InputBinding(_Strict):
    """One materialised input, as the container sees it."""

    key: Identifier
    kind: Literal["file", "directory", "value"]
    path: RelativePath | None = None
    value: Any = None

    def model_post_init(self, _context: Any) -> None:
        if self.kind in {"file", "directory"} and not self.path:
            raise ValueError(f"input '{self.key}' of kind {self.kind} requires a path")
        if self.kind == "value" and self.path is not None:
            raise ValueError(f"input '{self.key}' of kind value must not carry a path")


class OutputDeclaration(_Strict):
    """An output the task must produce, checked by the worker after exit.

    Declaring outputs up front is what makes a run auditable: the worker knows
    what to look for, and a task that exits 0 without producing them fails.
    """

    key: Identifier
    kind: Literal["file", "directory"]
    path: RelativePath
    required: bool = True
    min_bytes: int = Field(default=0, ge=0)


class ResourceLimits(_Strict):
    cpu_millicores: int = Field(gt=0, le=256_000)
    memory_bytes: int = Field(gt=0)
    wall_time_seconds: int = Field(gt=0, le=60 * 60 * 24 * 14)
    max_processes: int = Field(default=512, gt=0)
    network: Literal["none", "egress"] = "none"


class TaskSpec(_Strict):
    """What the platform hands a task container. Written to ``task.json``."""

    contract_version: str = CONTRACT_VERSION
    task_id: str
    run_id: str
    attempt: int = Field(ge=1)
    stage_key: Identifier
    task_key: str = Field(max_length=256)

    steps: list[StepSpec] = Field(min_length=1)
    inputs: list[InputBinding] = Field(default_factory=list)
    outputs: list[OutputDeclaration] = Field(default_factory=list)

    workspace_root: str = WORKSPACE_ROOT
    inputs_dir: str = INPUTS_DIR
    outputs_dir: str = OUTPUTS_DIR
    environment: dict[str, str] = Field(default_factory=dict)
    limits: ResourceLimits

    @field_validator("contract_version")
    @classmethod
    def _supported(cls, value: str) -> str:
        if value not in SUPPORTED_CONTRACT_VERSIONS:
            raise ValueError(
                f"unsupported contract version '{value}'; "
                f"this build supports {sorted(SUPPORTED_CONTRACT_VERSIONS)}"
            )
        return value

    @field_validator("inputs")
    @classmethod
    def _unique_input_keys(cls, value: list[InputBinding]) -> list[InputBinding]:
        keys = [binding.key for binding in value]
        if len(keys) != len(set(keys)):
            raise ValueError("input keys must be unique")
        return value

    @field_validator("steps")
    @classmethod
    def _unique_step_names(cls, value: list[StepSpec]) -> list[StepSpec]:
        names = [step.name for step in value]
        if len(names) != len(set(names)):
            raise ValueError("step names must be unique within a task")
        return value

    @field_validator("outputs")
    @classmethod
    def _unique_output_keys(cls, value: list[OutputDeclaration]) -> list[OutputDeclaration]:
        keys = [declaration.key for declaration in value]
        if len(keys) != len(set(keys)):
            raise ValueError("output keys must be unique")
        return value

    @field_validator("environment")
    @classmethod
    def _no_secret_shaped_names(cls, value: dict[str, str]) -> dict[str, str]:
        """Defence in depth against leaking a platform credential into a task.

        The worker builds this dict from an allowlist; this check exists so a
        mistake there fails a test rather than reaching a container.
        """
        banned = ("PASSWORD", "SECRET", "TOKEN", "API_KEY", "DATABASE_URL", "DSN")
        for name in value:
            upper = name.upper()
            if any(marker in upper for marker in banned):
                raise ValueError(f"environment variable '{name}' looks like a credential")
        return value


class OutputReport(_Strict):
    """What the task says it produced. The worker verifies it independently."""

    key: Identifier
    path: RelativePath
    size_bytes: int | None = Field(default=None, ge=0)
    checksum_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class TaskError(_Strict):
    """Structured failure detail.

    Distinguishing a validation failure from a crash is what lets the UI tell a
    researcher "your sample sheet is malformed" instead of "exit code 1".
    """

    code: str = Field(max_length=128)
    message: str = Field(max_length=4096)
    kind: Literal["input_invalid", "science_error", "resource_exhausted", "internal"] = "internal"
    details: dict[str, Any] = Field(default_factory=dict)


class TaskResult(_Strict):
    """What a task container reports back. Written to ``result.json``."""

    contract_version: str = CONTRACT_VERSION
    task_id: str
    attempt: int = Field(ge=1)
    status: Literal["succeeded", "failed"]
    outputs: list[OutputReport] = Field(default_factory=list)
    error: TaskError | None = None
    metrics: dict[str, float] = Field(default_factory=dict)

    @field_validator("contract_version")
    @classmethod
    def _supported(cls, value: str) -> str:
        if value not in SUPPORTED_CONTRACT_VERSIONS:
            raise ValueError(f"unsupported contract version '{value}'")
        return value

    def model_post_init(self, _context: Any) -> None:
        if self.status == "failed" and self.error is None:
            raise ValueError("a failed result must carry an error")
        if self.status == "succeeded" and self.error is not None:
            raise ValueError("a succeeded result must not carry an error")


class OutputVerification(_Strict):
    """The worker's own verdict on a declared output."""

    key: str
    present: bool
    satisfied: bool
    reason: str | None = None


def verify_outputs(
    declarations: list[OutputDeclaration],
    observed: dict[str, int | None],
) -> list[OutputVerification]:
    """Check declared outputs against what is actually on disk.

    ``observed`` maps an output key to its size in bytes, or ``None`` when the
    path does not exist. The task's own report is never trusted for this: the
    worker stats the workspace itself.
    """
    verdicts: list[OutputVerification] = []
    for declaration in declarations:
        size = observed.get(declaration.key)
        if size is None:
            verdicts.append(
                OutputVerification(
                    key=declaration.key,
                    present=False,
                    satisfied=not declaration.required,
                    reason=None if not declaration.required else "declared output was not produced",
                )
            )
            continue
        if size < declaration.min_bytes:
            verdicts.append(
                OutputVerification(
                    key=declaration.key,
                    present=True,
                    satisfied=False,
                    reason=f"output is {size} bytes, below the declared minimum "
                    f"of {declaration.min_bytes}",
                )
            )
            continue
        verdicts.append(OutputVerification(key=declaration.key, present=True, satisfied=True))
    return verdicts
