"""Publication bindings: exposing a value inside a pipeline as a form control.

A pipeline revision is immutable and may be shared by several publications, so
a publication cannot edit one. What it can do is say "this parameter, in this
step, of this stage, is a field the researcher fills in" — and at run creation
the submitted values plus those bindings produce a **new task plan**, leaving
the revision untouched (ADR 0031).

Two things about this are easy to get wrong.

**A binding names a stage, not a stage key.** With a matrix, one stage `fit`
compiles into `fit:no_replicates` and `fit:replicates`. An admin exposing "the
moving window of the fit stage" means both of them; binding to a key would mean
one matrix row silently keeps the old value, which is precisely the class of
silent wrongness this project exists to prevent.

**`default_value` can only name a public input.** A default that is not
`$WILL_PROVIDE$` is substituted into step parameters at compile time — by the
time there is an IR to bind against, `{od600_col}` is gone and the literal
`od600` is in its place. Binding to it could not take effect, so it is refused
at publish time with a message saying where the value actually lives. Nothing
is lost: that value is reachable as a `step_parameter` binding, at the
coordinate where it really exists.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import BindingTarget
from app.domain.ir import CompiledPipeline, CompiledStage, CompiledStep, Diagnostic


class FieldBinding(BaseModel):
    """Where one publication field reaches into a pipeline revision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(max_length=128)
    """The publication field's own key: what a submission is keyed by."""

    target: BindingTarget
    stage: str | None = Field(default=None, max_length=128)
    step: str | None = Field(default=None, max_length=128)
    binding_key: str = Field(max_length=128)
    value_type: str | None = Field(default=None, max_length=32)

    def where(self) -> str:
        """The binding as a dotted location, for a diagnostic."""
        parts = [part for part in (self.stage, self.step, self.binding_key) if part]
        return ".".join(parts)


def _type_of(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "string"


def _stages_named(pipeline: CompiledPipeline, name: str) -> list[CompiledStage]:
    """Every compiled stage a stage name covers — one per matrix row."""
    return [stage for stage in pipeline.stages if stage.name == name]


def _step_named(stage: CompiledStage, name: str) -> CompiledStep | None:
    return next((step for step in stage.steps if step.name == name), None)


# --- validation, at publish time -------------------------------------------


def validate_bindings(pipeline: CompiledPipeline, bindings: list[FieldBinding]) -> list[Diagnostic]:
    """Check every binding against the compiled IR.

    Publish-time, and fatal: a binding naming a stage, step, parameter or input
    that does not exist is a form control wired to nothing, and discovering
    that at run time means a researcher fills in a field that is silently
    ignored.
    """
    diagnostics: list[Diagnostic] = []
    seen: set[str] = set()

    for binding in bindings:
        if binding.key in seen:
            diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="binding.duplicate_field",
                    message=f"Two fields both use the key '{binding.key}'.",
                    location=binding.key,
                )
            )
        seen.add(binding.key)
        diagnostics.extend(_validate_one(pipeline, binding))

    return diagnostics


def _validate_one(pipeline: CompiledPipeline, binding: FieldBinding) -> list[Diagnostic]:
    def error(code: str, message: str) -> list[Diagnostic]:
        return [Diagnostic(severity="error", code=code, message=message, location=binding.where())]

    if binding.target == BindingTarget.DEFAULT_VALUE:
        public = {declared.key for declared in pipeline.inputs}
        if binding.binding_key not in public:
            return error(
                "binding.not_a_public_input",
                f"'{binding.binding_key}' is not an input this pipeline asks for. "
                "A default that is not $WILL_PROVIDE$ is substituted when the "
                "pipeline is compiled, so binding to it would have no effect; "
                "bind to the step parameter that uses it instead." + _suggest(sorted(public)),
            )
        return []

    if binding.stage is None:
        return error("binding.stage_required", f"A {binding.target} binding must name a stage.")

    stages = _stages_named(pipeline, binding.stage)
    if not stages:
        return error(
            "binding.stage_not_found",
            f"No stage called '{binding.stage}'."
            + _suggest(sorted({stage.name for stage in pipeline.stages})),
        )

    if binding.target == BindingTarget.STEP_PARAMETER:
        if binding.step is None:
            return error("binding.step_required", "A step_parameter binding must name a step.")
        # Every matrix row must carry the target. A matrix that selects a
        # different component per row can have a step in one row and not the
        # other, and a field that silently applies to half a run is worse than
        # one that is refused.
        for stage in stages:
            step = _step_named(stage, binding.step)
            if step is None:
                return error(
                    "binding.step_not_found",
                    f"Stage '{stage.key}' has no step called '{binding.step}'."
                    + _suggest([existing.name for existing in stage.steps]),
                )
            if binding.binding_key not in step.parameters:
                return error(
                    "binding.parameter_not_found",
                    f"Step '{binding.step}' of stage '{stage.key}' takes no "
                    f"parameter '{binding.binding_key}'." + _suggest(sorted(step.parameters)),
                )
        return []

    if binding.target == BindingTarget.STAGE_INPUT:
        for stage in stages:
            if binding.binding_key not in stage.inputs:
                return error(
                    "binding.input_not_found",
                    f"Stage '{stage.key}' has no input '{binding.binding_key}'."
                    + _suggest(sorted(stage.inputs)),
                )
        return []

    if binding.target == BindingTarget.STAGE_OUTPUT:
        for stage in stages:
            keys = {output.key for output in stage.outputs}
            if binding.binding_key not in keys:
                return error(
                    "binding.output_not_found",
                    f"Stage '{stage.key}' declares no output '{binding.binding_key}'."
                    + _suggest(sorted(keys)),
                )
        # Accepted and recorded, but nothing reads it yet: `delivery_policy` is
        # stored on the field and no delivery consults it. Said out loud rather
        # than left to be discovered, because a control that silently does
        # nothing is the exact failure the rest of this module prevents.
        return [
            Diagnostic(
                severity="warning",
                code="binding.output_destination_not_applied",
                message=(
                    f"'{binding.key}' binds an output destination. The binding is stored, "
                    "but delivery does not read it yet, so this field will not change "
                    "where anything is written."
                ),
                location=binding.where(),
            )
        ]

    return error("binding.unknown_target", f"Unknown binding target '{binding.target}'.")


def _suggest(candidates: list[str]) -> str:
    """What the author could have meant.

    A validation message that says only "not found" makes somebody go and read
    the pipeline; naming what is there usually makes the mistake obvious.
    """
    if not candidates:
        return " There are none to choose from."
    shown = ", ".join(f"'{candidate}'" for candidate in candidates[:8])
    more = "" if len(candidates) <= 8 else f", and {len(candidates) - 8} more"
    return f" Available: {shown}{more}."


def infer_value_types(
    pipeline: CompiledPipeline, bindings: list[FieldBinding]
) -> dict[str, str | None]:
    """The type the IR currently holds at each binding's target.

    Recorded on the publication field so a later incompatibility is detectable
    rather than silent (ADR 0031 rule 3) — if a new pipeline revision changes a
    parameter from a number to a path, the publication that fed it a number can
    be told rather than failing inside a container.
    """
    types: dict[str, str | None] = {}
    for binding in bindings:
        types[binding.key] = _type_at(pipeline, binding)
    return types


def infer_type_schemas(
    pipeline: CompiledPipeline, bindings: list[FieldBinding]
) -> dict[str, dict[str, Any] | None]:
    """The frozen type at each binding's target, where there is one.

    Only a `default_value` binding can carry one: that is the target that
    feeds a declared public input, and a public input is the only thing a
    document can attach a `type_ref` to. A step parameter takes whatever the
    step takes, which the platform has no declaration for.
    """
    schemas: dict[str, dict[str, Any] | None] = {}
    for binding in bindings:
        if binding.target != BindingTarget.DEFAULT_VALUE:
            schemas[binding.key] = None
            continue
        declared = next((item for item in pipeline.inputs if item.key == binding.binding_key), None)
        schemas[binding.key] = declared.type_schema if declared else None
    return schemas


def _type_at(pipeline: CompiledPipeline, binding: FieldBinding) -> str | None:
    if binding.target == BindingTarget.DEFAULT_VALUE:
        declared = next((item for item in pipeline.inputs if item.key == binding.binding_key), None)
        return declared.accept if declared else None

    stages = _stages_named(pipeline, binding.stage or "")
    if not stages:
        return None
    stage = stages[0]

    if binding.target == BindingTarget.STEP_PARAMETER:
        step = _step_named(stage, binding.step or "")
        if step is None or binding.binding_key not in step.parameters:
            return None
        return _type_of(step.parameters[binding.binding_key])

    if binding.target == BindingTarget.STAGE_INPUT:
        if binding.binding_key not in stage.inputs:
            return None
        return _type_of(stage.inputs[binding.binding_key])

    if binding.target == BindingTarget.STAGE_OUTPUT:
        return "directory"

    return None


# --- application, at run creation ------------------------------------------


class BoundSubmission(BaseModel):
    """What a submission becomes once its bindings are applied."""

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    pipeline: CompiledPipeline
    """The revision's IR with every non-input binding applied. In memory only:
    the stored revision is never touched, and may be shared with other
    publications."""

    values: dict[str, Any] = Field(default_factory=dict)
    """Values for the pipeline's own public inputs, keyed as the compiler
    named them — what `materialise` consumes."""


def apply_bindings(
    pipeline: CompiledPipeline,
    bindings: list[FieldBinding],
    submitted: dict[str, Any],
) -> BoundSubmission:
    """Produce the plan a submission actually runs.

    Only bindings the submission supplied a value for are applied; a field the
    researcher left blank leaves the pipeline's own value in place, which is
    what a default on a form means.
    """
    values: dict[str, Any] = {}
    # stage name -> step name -> parameter -> value
    step_overrides: dict[str, dict[str, dict[str, Any]]] = {}
    input_overrides: dict[str, dict[str, Any]] = {}

    for binding in bindings:
        if binding.key not in submitted:
            continue
        value = submitted[binding.key]

        if binding.target == BindingTarget.DEFAULT_VALUE:
            values[binding.binding_key] = value
        elif binding.target == BindingTarget.STEP_PARAMETER and binding.stage and binding.step:
            step_overrides.setdefault(binding.stage, {}).setdefault(binding.step, {})[
                binding.binding_key
            ] = value
        elif binding.target == BindingTarget.STAGE_INPUT and binding.stage:
            input_overrides.setdefault(binding.stage, {})[binding.binding_key] = value
        # stage_output bindings choose a destination, which the delivery plan
        # reads from the publication field rather than from the IR.

    if not step_overrides and not input_overrides:
        return BoundSubmission(pipeline=pipeline, values=values)

    stages = [
        _with_overrides(
            stage,
            steps=step_overrides.get(stage.name, {}),
            inputs=input_overrides.get(stage.name, {}),
        )
        for stage in pipeline.stages
    ]
    # `with_hash()` is deliberately not called: this plan is derived from a
    # revision and a submission, and giving it a graph hash would suggest it is
    # a revision of its own.
    return BoundSubmission(pipeline=pipeline.model_copy(update={"stages": stages}), values=values)


def _with_overrides(
    stage: CompiledStage,
    *,
    steps: dict[str, dict[str, Any]],
    inputs: dict[str, Any],
) -> CompiledStage:
    if not steps and not inputs:
        return stage

    update: dict[str, Any] = {}
    if inputs:
        update["inputs"] = {**stage.inputs, **inputs}
    if steps:
        update["steps"] = [
            step.model_copy(update={"parameters": {**step.parameters, **steps[step.name]}})
            if step.name in steps
            else step
            for step in stage.steps
        ]
    return stage.model_copy(update=update)


# --- what an editor may offer ----------------------------------------------


class BindableTarget(BaseModel):
    """One place in a pipeline a publication field could be attached."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    target: BindingTarget
    stage: str | None = None
    step: str | None = None
    key: str
    value_type: str | None = None
    current_value: Any = None
    """What the pipeline uses today. An admin choosing what to expose needs to
    see the value they are about to let somebody change."""


def _is_template(value: Any) -> bool:
    """True when a value is still the pipeline's own plumbing.

    A stage input of `"{data_root}/{item.raw}"` is how fan-out addresses one
    item of many. Letting a publication replace it with a fixed path would make
    every fanned-out task read the same file — a run that looks right and
    analyses one experiment twelve times.
    """
    return isinstance(value, str) and "{" in value


def _payload_names(stage: CompiledStage, before: int) -> set[str]:
    """What a parameter value could be naming instead of holding.

    The runner resolves a parameter whose value matches a payload key to that
    key's value: `df: df_parsed` hands the previous step's DataFrame over, and
    `raw_data: raw_data` passes the stage input. They are the pipeline's
    plumbing written as strings, and the payload holds the stage's inputs plus
    every step that has already run.
    """
    return set(stage.inputs) | {step.name for step in stage.steps[:before]}


def bindable_targets(pipeline: CompiledPipeline) -> list[BindableTarget]:
    """Everything a publication field could bind to, and nothing else.

    Computed under the same rules `validate_bindings` enforces, so an editor
    built on this cannot offer a binding that would then be refused: a target
    is listed only when it exists in **every** matrix row of its stage, and
    templated values are left out entirely.

    Two further kinds are left out because they are the pipeline's plumbing
    rather than its knobs: templated values, and parameters whose value names a
    stage input or an earlier step, which is how a step receives the previous
    one's result.

    Output destinations are not offered either. They are a valid binding target
    in the model, but delivery does not read them yet, and offering a control
    that does nothing is worse than offering none.
    """
    targets: list[BindableTarget] = [
        BindableTarget(
            target=BindingTarget.DEFAULT_VALUE,
            key=declared.key,
            value_type=declared.accept,
        )
        for declared in pipeline.inputs
    ]

    by_name: dict[str, list[CompiledStage]] = {}
    for stage in pipeline.stages:
        by_name.setdefault(stage.name, []).append(stage)

    for name, rows in by_name.items():
        first = rows[0]

        for key, value in sorted(first.inputs.items()):
            if _is_template(value):
                continue
            if not all(key in row.inputs and not _is_template(row.inputs[key]) for row in rows):
                continue
            targets.append(
                BindableTarget(
                    target=BindingTarget.STAGE_INPUT,
                    stage=name,
                    key=key,
                    value_type=_type_of(value),
                    current_value=value,
                )
            )

        for index, step in enumerate(first.steps):
            plumbing = _payload_names(first, index)
            for key, value in sorted(step.parameters.items()):
                if _is_template(value):
                    continue
                # `df: df_parsed` is how a step receives the previous step's
                # DataFrame. Offering it as a form control would let somebody
                # replace a live object with whatever they typed, and the
                # failure would surface deep inside a container as a method
                # missing from a string.
                if isinstance(value, str) and value in plumbing:
                    continue
                if not all(
                    (found := _step_named(row, step.name)) is not None
                    and key in found.parameters
                    and not _is_template(found.parameters[key])
                    for row in rows
                ):
                    continue
                targets.append(
                    BindableTarget(
                        target=BindingTarget.STEP_PARAMETER,
                        stage=name,
                        step=step.name,
                        key=key,
                        value_type=_type_of(value),
                        current_value=value,
                    )
                )

    return targets
