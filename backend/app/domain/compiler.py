"""The pipeline compiler.

Turns an authoring document into an immutable, self-contained IR, or into a
list of located diagnostics. It never raises on the first problem: an author
fixing a document should see everything at once.

Order matters, and one step is ordered the way it is for a reason:

1. Structural validation (done by :mod:`app.domain.authoring`).
2. Reserved-name and public-input checks.
3. **Matrix expansion.**
4. **Component resolution — after the matrix**, because in real job
   definitions the graph is chosen by a matrix variable
   (``graph: "{variant.pipeline}"``). Every graph the matrix can select must
   be enumerable and is pinned by digest (ADR 0026).
5. Reference resolution, leaving ``{item.*}`` deferred.
6. Graph validation: dependencies exist, no cycles.
7. Hash.

The rules that exist because of real defects:

* An **unresolvable reference is an error**, never an empty string. 509 of
  2,178 real task specifications carried one through into a task.
* An **override naming a step that does not exist is an error**. That was the
  second silent failure; combined with the first, a typo produced a run that
  reported success and quietly did nothing.
"""

from __future__ import annotations

import hashlib
import itertools
import json
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from app.domain.authoring import (
    PROVIDED_SENTINEL,
    ComponentLibrary,
    PipelineDocument,
    Stage,
    Step,
)
from app.domain.errors import ExpressionError
from app.domain.ir import (
    CompilationResult,
    CompiledFanOut,
    CompiledInput,
    CompiledOutput,
    CompiledPipeline,
    CompiledStage,
    CompiledStep,
    ComponentPin,
    Diagnostic,
)
from app.domain.references import (
    RESERVED_ROOTS,
    ResolutionContext,
    parse,
    render,
    render_tree,
)
from app.domain.types import TypeError_, parse_definitions, resolve

LibraryLoader = Callable[[str], ComponentLibrary]
"""Resolves a library path to its graphs. Injected so the compiler stays pure
and testable: no filesystem, no database."""

MAX_MATRIX_ROWS = 512
"""A matrix that expands beyond this is almost certainly a mistake, and it
would materialise thousands of tasks."""


class _Collector:
    def __init__(self) -> None:
        self.diagnostics: list[Diagnostic] = []

    def error(self, code: str, message: str, location: str = "", **extra: Any) -> None:
        self.diagnostics.append(
            Diagnostic(severity="error", code=code, message=message, location=location, **extra)
        )

    def warn(self, code: str, message: str, location: str = "", **extra: Any) -> None:
        self.diagnostics.append(
            Diagnostic(severity="warning", code=code, message=message, location=location, **extra)
        )

    @property
    def failed(self) -> bool:
        return any(d.severity == "error" for d in self.diagnostics)


def _matrix_rows(variables: Mapping[str, list[Any]]) -> list[dict[str, Any]]:
    """Expand the cross product of the matrix.

    With no variables there is exactly one implicit row, so the rest of the
    compiler has a single code path.
    """
    if not variables:
        return [{}]
    keys = sorted(variables)
    combos = itertools.product(*(variables[key] for key in keys))
    return [dict(zip(keys, combo, strict=True)) for combo in combos]


def _flatten_variant(row: Mapping[str, Any]) -> dict[str, Any]:
    """Flatten a matrix row into the `{variant.*}` namespace.

    A single-variable matrix whose rows are mappings exposes their keys
    directly, which is what the real job definitions expect from
    `{variant.group_cols}`. Several variables expose each by name.
    """
    if len(row) == 1:
        (value,) = row.values()
        if isinstance(value, Mapping):
            return dict(value)
    flattened: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, Mapping):
            flattened.update(value)
        else:
            flattened[key] = value
    return flattened


def _variant_suffix(row: Mapping[str, Any]) -> str:
    """A stable, readable key fragment for a matrix row."""
    if not row:
        return ""
    flat = _flatten_variant(row)
    label = flat.get("name")
    if isinstance(label, str) and label:
        return label
    encoded = json.dumps(flat, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()[:8]


def _digest(steps: Iterable[Step]) -> str:
    body = [step.model_dump(mode="json") for step in steps]
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _detect_cycle(edges: Mapping[str, list[str]]) -> list[str] | None:
    """Return a cycle as a path, or None. Iterative, so a deep graph is safe."""
    WHITE, GREY, BLACK = 0, 1, 2
    colour = dict.fromkeys(edges, WHITE)
    for start in edges:
        if colour[start] != WHITE:
            continue
        stack: list[tuple[str, list[str]]] = [(start, [start])]
        while stack:
            node, path = stack.pop()
            if colour.get(node) == GREY:
                colour[node] = BLACK
                continue
            colour[node] = GREY
            stack.append((node, path))
            for nxt in edges.get(node, []):
                if colour.get(nxt) == GREY:
                    return [*path, nxt]
                if colour.get(nxt, WHITE) == WHITE:
                    stack.append((nxt, [*path, nxt]))
    return None


def compile_pipeline(
    document: PipelineDocument,
    *,
    load_library: LibraryLoader | None = None,
    provided: Mapping[str, Any] | None = None,
) -> CompilationResult:
    """Compile a document into an IR, or into diagnostics.

    ``provided`` supplies values for ``$WILL_PROVIDE$`` inputs. At authoring
    time it is empty, and those inputs are left as declared public inputs
    rather than resolved; a compile preview may pass sample values.
    """
    collected = _Collector()
    supplied = dict(provided or {})

    # --- names ---------------------------------------------------------
    #
    # Only defaults can shadow a namespace root. A *matrix variable* named
    # `variant` is idiomatic -- it is what the real job definitions call it --
    # because matrix variables populate the `{variant.*}` namespace rather
    # than the flat `{name}` one, so their names cannot clash.
    for name in document.defaults:
        if name in RESERVED_ROOTS:
            collected.error(
                "name.reserved",
                f"'{name}' is a reserved namespace root and cannot be the name of "
                f"a default. Referencing it would be ambiguous with '{{{name}.*}}'.",
                location=f"defaults.{name}",
            )

    public_inputs = set(document.provided_inputs)
    for key in document.inputs:
        if key not in public_inputs:
            collected.warn(
                "input.not_provided",
                f"'{key}' has an input policy but its default is not "
                f"{PROVIDED_SENTINEL}, so nothing will ask for it.",
                location=f"inputs.{key}",
            )

    # --- matrix --------------------------------------------------------
    rows = _matrix_rows(document.variables)
    if len(rows) > MAX_MATRIX_ROWS:
        collected.error(
            "matrix.too_large",
            f"The matrix expands to {len(rows)} rows; the maximum is {MAX_MATRIX_ROWS}.",
            location="variables",
        )
        return CompilationResult(diagnostics=collected.diagnostics)

    # --- stages, per matrix row ----------------------------------------
    compiled_stages: list[CompiledStage] = []
    pins: dict[str, ComponentPin] = {}

    for row in rows:
        variant = _flatten_variant(row) if row else None
        suffix = _variant_suffix(row)
        for stage in document.stages:
            compiled = _compile_stage(
                document=document,
                stage=stage,
                variant=variant,
                suffix=suffix,
                supplied=supplied,
                public_inputs=public_inputs,
                load_library=load_library,
                pins=pins,
                collected=collected,
            )
            if compiled is not None:
                compiled_stages.append(compiled)

    # --- graph ---------------------------------------------------------
    _validate_graph(document, compiled_stages, collected)

    # --- types ---------------------------------------------------------
    #
    # Resolved here, at compile time, so an input naming a type nobody defined
    # fails the compile rather than the submission. The same rule bindings
    # follow: a reference to something that does not exist is a mistake the
    # author can still fix, and finding it later means finding it in front of
    # a researcher.
    schemas = _resolve_types(document, collected)

    if collected.failed:
        return CompilationResult(diagnostics=collected.diagnostics)

    inputs = [
        CompiledInput(
            key=key,
            sources=(policy.sources if (policy := document.inputs.get(key)) else []),
            accept=(policy.accept if (policy := document.inputs.get(key)) else "value"),
            type_ref=(policy.type_ref if (policy := document.inputs.get(key)) else None),
            type_schema=schemas.get(key),
            help=(policy.help if (policy := document.inputs.get(key)) else None),
        )
        for key in sorted(public_inputs)
    ]

    pipeline = CompiledPipeline(
        pipeline=document.pipeline,
        title=document.title,
        description=document.description,
        inputs=inputs,
        stages=compiled_stages,
        components=sorted(pins.values(), key=lambda pin: (pin.alias, pin.graph)),
    ).with_hash()
    return CompilationResult(pipeline=pipeline, diagnostics=collected.diagnostics)


def _compile_stage(
    *,
    document: PipelineDocument,
    stage: Stage,
    variant: dict[str, Any] | None,
    suffix: str,
    supplied: Mapping[str, Any],
    public_inputs: set[str],
    load_library: LibraryLoader | None,
    pins: dict[str, ComponentPin],
    collected: _Collector,
) -> CompiledStage | None:
    key = f"{stage.name}:{suffix}" if suffix else stage.name
    where = f"stages.{stage.name}"

    # Variables visible to this stage. A $WILL_PROVIDE$ default is a public
    # input; unless a value was supplied it stays unresolved, and referencing
    # it is legal because the run will supply it.
    variables: dict[str, Any] = {}
    deferred: set[str] = set()
    for name, value in document.defaults.items():
        if value != PROVIDED_SENTINEL:
            variables[name] = value
        elif name in supplied:
            variables[name] = supplied[name]
        else:
            # A public input with no value yet. It is a *reference* that
            # survives compilation, not a placeholder string: substituting one
            # here would bake "<data_root>" into the IR and the real value
            # would never reach the task.
            variables[name] = None
            deferred.add(name)

    context = ResolutionContext(
        variables=variables,
        variant=variant,
        item=None,
        in_fanout_stage=stage.fanout.is_deferred,
        deferred=frozenset(deferred),
    )

    def resolve(value: Any, location: str) -> Any:
        """Render now, leaving `{item.*}` for run materialisation.

        Partial rendering matters: a path mixing `{variant.name}` with
        `{item.stem}` must have the matrix row substituted even though the item
        cannot be known yet.
        """
        try:
            return render_tree(value, context, partial=stage.fanout.is_deferred or bool(deferred))
        except ExpressionError as error:
            collected.error(
                "reference.unresolved",
                error.message,
                location=location,
                variant=variant,
            )
            return value

    # --- steps: component or inline ------------------------------------
    steps: list[Step]
    pin: ComponentPin | None = None

    if stage.uses:
        reference = document.components.get(stage.uses)
        if reference is None:
            collected.error(
                "component.unknown",
                f"Stage '{stage.name}' uses component '{stage.uses}', which is not "
                f"declared under 'components'.",
                location=f"{where}.uses",
            )
            return None
        # Resolved AFTER matrix expansion: the graph name may be templated.
        try:
            graph = render(reference.graph, context)
        except ExpressionError as error:
            collected.error(
                "component.unresolvable_selection",
                f"The graph for component '{stage.uses}' cannot be determined at "
                f"compile time: {error.message} Every graph the matrix can select "
                "must be enumerable, so the compiled pipeline stays self-contained.",
                location=f"components.{stage.uses}.graph",
                variant=variant,
            )
            return None
        if not isinstance(graph, str):
            collected.error(
                "component.unresolvable_selection",
                f"The graph for component '{stage.uses}' resolved to "
                f"{type(graph).__name__}; it must be a name.",
                location=f"components.{stage.uses}.graph",
                variant=variant,
            )
            return None
        if load_library is None:
            collected.error(
                "component.no_loader",
                "This pipeline imports components but no component library loader "
                "was provided to the compiler.",
                location=f"{where}.uses",
            )
            return None
        try:
            library = load_library(reference.library)
        except Exception as error:
            collected.error(
                "component.library_unreadable",
                f"Cannot read component library '{reference.library}': {error}",
                location=f"components.{stage.uses}.library",
            )
            return None
        if graph not in library.graphs:
            available = ", ".join(sorted(library.graphs)) or "none"
            collected.error(
                "component.graph_unknown",
                f"Component library '{reference.library}' has no graph '{graph}'. "
                f"It defines: {available}.",
                location=f"components.{stage.uses}.graph",
                variant=variant,
            )
            return None
        steps = list(library.graphs[graph])
        pin = ComponentPin(
            alias=stage.uses,
            library=reference.library,
            graph=graph,
            digest=_digest(steps),
        )
        pins[f"{stage.uses}:{graph}"] = pin

        # Overrides must name a step that exists. This is the second of the two
        # silent failures found in the real data.
        known = {step.name for step in steps}
        for step_name, overrides in stage.step_parameters.items():
            if step_name not in known:
                collected.error(
                    "override.unknown_step",
                    f"Stage '{stage.name}' overrides parameters of step "
                    f"'{step_name}', which graph '{graph}' does not define. It has: "
                    f"{', '.join(sorted(known))}.",
                    location=f"{where}.step_parameters.{step_name}",
                    variant=variant,
                )
                continue
            steps = [
                step.model_copy(update={"parameters": {**step.parameters, **overrides}})
                if step.name == step_name
                else step
                for step in steps
            ]
    else:
        steps = list(stage.steps)

    # --- resolve ------------------------------------------------------
    compiled_steps: list[CompiledStep] = []
    for step in steps:
        parameters = resolve(step.parameters, f"{where}.steps.{step.name}.parameters")
        compiled_steps.append(
            CompiledStep(
                name=step.name,
                package=step.package,
                method=step.method,
                parameters=parameters,
                has_deferred=_has_deferred(parameters),
            )
        )

    compiled_steps = annotate_liveness(compiled_steps, seeded=stage.inputs.keys())

    inputs = resolve(stage.inputs, f"{where}.inputs")
    fanout_fields = resolve(stage.fanout.model_dump(exclude={"type"}), f"{where}.fanout")
    outputs = [
        CompiledOutput(
            key=name,
            path=resolve(spec.path, f"{where}.outputs.{name}.path"),
            delivery=spec.delivery,
            shared_root=spec.shared_root,
            retention_days=spec.retention_days,
            optional=spec.optional,
            has_deferred=_has_deferred(resolve(spec.path, f"{where}.outputs.{name}.path")),
        )
        for name, spec in stage.outputs.items()
    ]

    # A stage that is not fanned out may not reference an item.
    if not stage.fanout.is_deferred:
        for location, value in (
            (f"{where}.inputs", inputs),
            (f"{where}.outputs", [output.path for output in outputs]),
        ):
            if _has_deferred(value):
                collected.error(
                    "reference.item_outside_fanout",
                    f"Stage '{stage.name}' references '{{item.*}}' but declares no "
                    "fanout, so there is no item.",
                    location=location,
                    variant=variant,
                )

    return CompiledStage(
        key=key,
        name=stage.name,
        variant=variant,
        needs=[f"{need}:{suffix}" if suffix else need for need in stage.needs],
        fanout=CompiledFanOut(type=stage.fanout.type, **fanout_fields),
        inputs=inputs,
        steps=compiled_steps,
        outputs=outputs,
        task_class=stage.task_class,
        component=pin,
    )


def _referenced_names(value: Any, candidates: set[str]) -> set[str]:
    """Payload names a parameter tree refers to.

    A scalar equal to a candidate name is a reference, matching how the
    runner resolves parameters. Recurses into lists and mappings, since one
    parameter can gather several upstream results.
    """
    found: set[str] = set()
    if isinstance(value, Mapping):
        for item in value.values():
            found |= _referenced_names(item, candidates)
    elif isinstance(value, list | tuple):
        for item in value:
            found |= _referenced_names(item, candidates)
    else:
        try:
            if value in candidates:
                found.add(value)  # type: ignore[arg-type]
        except TypeError:
            pass
    return found


def annotate_liveness(steps: list[CompiledStep], seeded: Iterable[str] = ()) -> list[CompiledStep]:
    """Record, for each step, which payload names outlive it.

    Walked backwards: a name is live at step *i* if any step after *i* refers
    to it. The last step retains nothing, because nothing follows it to use
    the result.
    """
    names = {step.name for step in steps} | set(seeded)
    live: set[str] = set()
    annotated: list[CompiledStep] = []
    for step in reversed(steps):
        annotated.append(step.model_copy(update={"retain": sorted(live)}))
        # This step's own result is produced here, so it stops being something
        # earlier steps must keep alive; its references start being.
        live.discard(step.name)
        live |= _referenced_names(step.parameters, names)
    return list(reversed(annotated))


def _has_deferred(value: Any) -> bool:
    """True when anything in ``value`` still holds an ``{item.*}`` reference."""
    if isinstance(value, str):
        try:
            return parse(value).has_deferred
        except ExpressionError:
            return False
    if isinstance(value, Mapping):
        return any(_has_deferred(item) for item in value.values())
    if isinstance(value, list | tuple):
        return any(_has_deferred(item) for item in value)
    return False


def _resolve_types(document: PipelineDocument, collected: _Collector) -> dict[str, Any]:
    """Freeze each public input's declared type into a self-contained schema."""
    try:
        definitions = parse_definitions(document.definitions)
    except TypeError_ as error:
        collected.error("type.invalid", error.message, location="definitions")
        return {}

    declared = {key for key, policy in document.inputs.items() if policy.type_ref}
    unused = sorted(set(definitions) - {document.inputs[key].type_ref for key in declared})
    for name in unused:
        collected.warn(
            "type.unused",
            f"'{name}' is defined but no input refers to it.",
            location=f"definitions.{name}",
        )

    schemas: dict[str, Any] = {}
    for key in sorted(declared):
        policy = document.inputs[key]
        reference = str(policy.type_ref)
        if policy.accept != "value":
            collected.error(
                "type.not_a_value",
                f"'{key}' accepts a {policy.accept}, so a type reference does not apply to it.",
                location=f"inputs.{key}.type_ref",
            )
            continue
        try:
            schemas[key] = resolve(reference, definitions)
        except TypeError_ as error:
            collected.error("type.unresolved", error.message, location=f"inputs.{key}.type_ref")
    return schemas


def _validate_graph(
    document: PipelineDocument,
    stages: list[CompiledStage],
    collected: _Collector,
) -> None:
    declared = {stage.name for stage in document.stages}
    for stage in document.stages:
        for need in stage.needs:
            if need not in declared:
                collected.error(
                    "graph.unknown_dependency",
                    f"Stage '{stage.name}' depends on '{need}', which is not "
                    f"defined. Defined stages: {', '.join(sorted(declared))}.",
                    location=f"stages.{stage.name}.needs",
                )

    edges = {stage.name: [n for n in stage.needs if n in declared] for stage in document.stages}
    cycle = _detect_cycle(edges)
    if cycle is not None:
        collected.error(
            "graph.cycle",
            f"Dependency cycle: {' -> '.join(cycle)}.",
            location="stages",
        )

    keys = [stage.key for stage in stages]
    duplicates = {key for key in keys if keys.count(key) > 1}
    if duplicates:
        collected.error(
            "graph.duplicate_stage_key",
            f"Stage keys are not unique after matrix expansion: {sorted(duplicates)}. "
            "Give each matrix row a distinct 'name'.",
            location="variables",
        )
