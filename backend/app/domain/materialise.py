"""Run materialisation: a compiled pipeline plus submitted values become tasks.

This is where the deferred half of compilation is finished. The compiler
resolves everything it can and leaves ``{item.*}`` alone, because the item list
does not exist until a fan-out source is enumerated. Materialisation enumerates
those sources, renders what is left, and emits one task plan per stage per
item.

Enumeration is injected rather than performed here, so the domain layer stays
free of the filesystem and the whole thing is testable without one.

The two jobs it does that are easy to get wrong:

* **Required inputs are checked and coerced before anything is built.** Real
  submissions arrive as strings -- ``{"n_samples": "200", "seed": "42"}``
  against a library declaring integers -- and a value that reaches a science
  function as the wrong type is a defect the platform should have caught.
* **Dependencies are expanded conservatively.** When a stage depends on a
  fanned-out stage, every task of the dependent waits for *all* tasks of the
  dependency. See :func:`_task_dependencies` for why.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.domain.enums import TaskClass
from app.domain.errors import ExpressionError
from app.domain.ir import (
    CompiledFanOut,
    CompiledPipeline,
    CompiledStage,
    Diagnostic,
)
from app.domain.references import ResolutionContext, render_tree

FanOutEnumerator = Callable[[CompiledFanOut], list[dict[str, Any]]]
"""Resolves a fan-out source to its items.

An item is a mapping exposing ``raw``, ``meta`` and ``stem`` as appropriate for
its kind. Injected so materialisation never touches a filesystem itself.
"""


@dataclass(frozen=True, slots=True)
class ResourceRequest:
    """What a task asks the scheduler for."""

    task_class: str
    cpu_millicores: int
    memory_bytes: int
    wall_time_seconds: int
    exclusive: bool = False


GIB = 1024**3

DEFAULT_RESOURCES: dict[str, ResourceRequest] = {
    TaskClass.SMALL: ResourceRequest(TaskClass.SMALL, 500, 1 * GIB, 15 * 60),
    TaskClass.STANDARD: ResourceRequest(TaskClass.STANDARD, 1000, 2 * GIB, 6 * 3600),
    TaskClass.LARGE: ResourceRequest(TaskClass.LARGE, 4000, 16 * GIB, 24 * 3600),
    TaskClass.EXCLUSIVE: ResourceRequest(
        TaskClass.EXCLUSIVE, 4000, 16 * GIB, 24 * 3600, exclusive=True
    ),
}
"""Conventional profiles. A deployment overrides them; the scheduler reads the
per-task numbers, not the class name."""


@dataclass(frozen=True, slots=True)
class TaskPlan:
    """One executable unit of a run."""

    task_key: str
    stage_key: str
    stage_name: str
    variant: dict[str, Any] | None
    item: dict[str, Any] | None
    steps: list[dict[str, Any]]
    inputs: dict[str, Any]
    outputs: list[dict[str, Any]]
    resources: ResourceRequest
    needs: tuple[str, ...] = ()


@dataclass(slots=True)
class MaterialisationResult:
    tasks: list[TaskPlan] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == "error"]

    @property
    def ok(self) -> bool:
        return not self.errors


def _coerce(value: Any, accept: str, key: str) -> Any:
    """Coerce a submitted value to the declared shape.

    Submissions arrive from HTML forms, so numbers arrive as strings. Coercing
    here, and failing loudly, is what stops a string reaching a science
    function that expected a number.
    """
    if accept in {"file", "directory"}:
        if not isinstance(value, str) or not value:
            raise ValueError(f"'{key}' must be a path")
        return value
    return value


def coerce_value(value: Any, target: str, key: str) -> Any:
    """Coerce one scalar to ``integer``, ``number``, ``boolean`` or ``string``."""
    if target == "integer":
        if isinstance(value, bool):
            raise ValueError(f"'{key}': expected an integer, got a boolean")
        try:
            coerced = int(str(value).strip())
        except (TypeError, ValueError):
            raise ValueError(f"'{key}': '{value}' is not an integer") from None
        return coerced
    if target == "number":
        try:
            return float(str(value).strip())
        except (TypeError, ValueError):
            raise ValueError(f"'{key}': '{value}' is not a number") from None
    if target == "boolean":
        text = str(value).strip().lower()
        if text in {"true", "1", "yes", "on"}:
            return True
        if text in {"false", "0", "no", "off"}:
            return False
        raise ValueError(f"'{key}': '{value}' is not a boolean")
    return value


def _task_dependencies(
    stage: CompiledStage, tasks_by_stage: Mapping[str, list[str]]
) -> tuple[str, ...]:
    """Expand stage dependencies into task dependencies.

    Conservative by design: every task of a dependent stage waits for **all**
    tasks of the stage it needs.

    Pairing them item-by-item would be more parallel, but only correct when
    both stages fan out over the same source in the same order, which the
    format does not guarantee and the real pipelines do not do -- there, a
    collation stage consumes the whole set of folders an upstream stage
    produced. Waiting for all of them is right for that shape, and merely slow
    for the other. Being slow is recoverable; starting a task whose input does
    not exist yet is not.
    """
    dependencies: list[str] = []
    for needed in stage.needs:
        dependencies.extend(tasks_by_stage.get(needed, []))
    return tuple(dependencies)


def materialise(
    pipeline: CompiledPipeline,
    values: Mapping[str, Any],
    *,
    enumerate_fanout: FanOutEnumerator | None = None,
    resources: Mapping[str, ResourceRequest] | None = None,
) -> MaterialisationResult:
    """Build the task plan for one run."""
    result = MaterialisationResult()
    profiles = dict(resources or DEFAULT_RESOURCES)

    # --- inputs ---------------------------------------------------------
    supplied: dict[str, Any] = {}
    for declared in pipeline.inputs:
        if declared.key not in values:
            if declared.required:
                result.diagnostics.append(
                    Diagnostic(
                        severity="error",
                        code="input.missing",
                        message=f"'{declared.key}' is required but was not supplied.",
                        location=f"inputs.{declared.key}",
                    )
                )
            continue
        try:
            supplied[declared.key] = _coerce(values[declared.key], declared.accept, declared.key)
        except ValueError as error:
            result.diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="input.invalid",
                    message=str(error),
                    location=f"inputs.{declared.key}",
                )
            )

    unexpected = set(values) - {declared.key for declared in pipeline.inputs}
    for key in sorted(unexpected):
        result.diagnostics.append(
            Diagnostic(
                severity="warning",
                code="input.unexpected",
                message=f"'{key}' was supplied but this pipeline declares no such input.",
                location=f"inputs.{key}",
            )
        )

    if result.errors:
        return result

    # --- tasks ----------------------------------------------------------
    tasks_by_stage: dict[str, list[str]] = {}

    for stage in pipeline.stages:
        items: list[dict[str, Any] | None]
        if stage.is_fanned_out:
            if enumerate_fanout is None:
                result.diagnostics.append(
                    Diagnostic(
                        severity="error",
                        code="fanout.no_enumerator",
                        message=(
                            f"Stage '{stage.key}' fans out, but no enumerator was "
                            "provided to resolve its items."
                        ),
                        location=f"stages.{stage.name}.fanout",
                    )
                )
                continue
            try:
                enumerated = enumerate_fanout(_rendered_fanout(stage, supplied))
            except Exception as error:
                result.diagnostics.append(
                    Diagnostic(
                        severity="error",
                        code="fanout.unresolvable",
                        message=f"Stage '{stage.key}': {error}",
                        location=f"stages.{stage.name}.fanout",
                    )
                )
                continue
            if not enumerated:
                result.diagnostics.append(
                    Diagnostic(
                        severity="error",
                        code="fanout.empty",
                        message=(
                            f"Stage '{stage.key}' fans out but its source produced no "
                            "items, so the run would do nothing."
                        ),
                        location=f"stages.{stage.name}.fanout",
                    )
                )
                continue
            items = list(enumerated)
        else:
            items = [None]

        keys: list[str] = []
        for index, item in enumerate(items):
            plan = _plan_task(
                stage=stage,
                item=item,
                index=index,
                supplied=supplied,
                profiles=profiles,
                result=result,
            )
            if plan is not None:
                result.tasks.append(plan)
                keys.append(plan.task_key)
        tasks_by_stage[stage.key] = keys

    # --- dependencies ---------------------------------------------------
    #
    # Indexed rather than searched, and not asserted: a task whose stage is
    # missing would be an internal invariant violation, and an assert can be
    # stripped under -O. It gets no dependencies and a diagnostic instead.
    by_key = {stage.key: stage for stage in pipeline.stages}
    linked: list[TaskPlan] = []
    for plan in result.tasks:
        owning = by_key.get(plan.stage_key)
        if owning is None:
            result.diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="internal.orphan_task",
                    message=(
                        f"Task '{plan.task_key}' references stage "
                        f"'{plan.stage_key}', which the compiled pipeline does "
                        "not define."
                    ),
                    location="stages",
                )
            )
            continue
        needs = _task_dependencies(owning, tasks_by_stage)
        linked.append(
            TaskPlan(
                task_key=plan.task_key,
                stage_key=plan.stage_key,
                stage_name=plan.stage_name,
                variant=plan.variant,
                item=plan.item,
                steps=plan.steps,
                inputs=plan.inputs,
                outputs=plan.outputs,
                resources=plan.resources,
                needs=needs,
            )
        )
    result.tasks = linked
    return result


def _rendered_fanout(stage: CompiledStage, supplied: Mapping[str, Any]) -> CompiledFanOut:
    """Substitute any remaining public-input references in the fan-out source."""
    context = ResolutionContext(variables=dict(supplied), variant=stage.variant)
    fields = stage.fanout.model_dump(exclude={"type"})
    rendered = {
        key: (render_tree(value, context) if isinstance(value, str) else value)
        for key, value in fields.items()
    }
    return CompiledFanOut(type=stage.fanout.type, **rendered)


def _plan_task(
    *,
    stage: CompiledStage,
    item: dict[str, Any] | None,
    index: int,
    supplied: Mapping[str, Any],
    profiles: Mapping[str, ResourceRequest],
    result: MaterialisationResult,
) -> TaskPlan | None:
    suffix = ""
    if item is not None:
        label = item.get("stem") or item.get("name")
        suffix = f":{label}" if isinstance(label, str) and label else f":{index}"
    task_key = f"{stage.key}{suffix}"

    context = ResolutionContext(
        variables=dict(supplied),
        variant=stage.variant,
        item=item,
        in_fanout_stage=item is not None,
    )

    def finish(value: Any, location: str) -> Any:
        try:
            return render_tree(value, context)
        except ExpressionError as error:
            result.diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="reference.unresolved",
                    message=error.message,
                    location=location,
                    variant=stage.variant,
                )
            )
            return value

    steps = [
        {
            "name": step.name,
            "package": step.package,
            "method": step.method,
            "parameters": finish(
                step.parameters, f"stages.{stage.name}.steps.{step.name}.parameters"
            ),
            # Carried from the compiler's liveness analysis so the runner can
            # release intermediates as soon as nothing refers to them.
            "retain": step.retain,
        }
        for step in stage.steps
    ]
    inputs = finish(stage.inputs, f"stages.{stage.name}.inputs")
    outputs = [
        {
            "key": output.key,
            "path": finish(output.path, f"stages.{stage.name}.outputs.{output.key}"),
            "delivery": [mode.value for mode in output.delivery],
            "shared_root": output.shared_root,
            "optional": output.optional,
            "retention_days": output.retention_days,
        }
        for output in stage.outputs
    ]

    profile = profiles.get(stage.task_class) or DEFAULT_RESOURCES[TaskClass.STANDARD]
    return TaskPlan(
        task_key=task_key,
        stage_key=stage.key,
        stage_name=stage.name,
        variant=stage.variant,
        item=item,
        steps=steps,
        inputs=inputs,
        outputs=outputs,
        resources=profile,
    )


def mapping_file_items(mapping: Mapping[str, str]) -> list[dict[str, Any]]:
    """Build fan-out items from a raw -> metadata mapping.

    ``stem`` is the raw filename without its extension, which is what the
    existing pipelines use to name per-experiment output directories.
    """
    items: list[dict[str, Any]] = []
    for raw, meta in mapping.items():
        stem = raw.rsplit("/", 1)[-1]
        if "." in stem:
            stem = stem.rsplit(".", 1)[0]
        items.append({"raw": raw, "meta": meta, "stem": stem})
    return items


def folder_items(names: Sequence[str]) -> list[dict[str, Any]]:
    """Build fan-out items from a list of folder names."""
    return [{"stem": name, "name": name, "path": name} for name in names]
