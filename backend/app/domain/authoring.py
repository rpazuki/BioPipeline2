"""The pipeline authoring document.

Structural validation only: shapes, names, and the invariants that can be
checked without resolving references. Semantic validation — do the references
resolve, does the graph have a cycle, does a component exist — belongs to the
compiler, which reports diagnostics rather than raising on the first problem.

The shape follows what the existing job definitions already do, with one
authoring level instead of two (ADR 0026)::

    pipeline: od600_growth_rates
    components:
      growth: {library: components/growth_rates.yaml, graph: "{variant.graph}"}
    variables:
      variant:
        - {name: no_replicates, graph: growth_rate_fit_pipeline, group_cols: well}
    defaults:
      data_root: $WILL_PROVIDE$
      od600_col: od600
    stages:
      - name: fit
        fanout: {type: mapping_file, mapping: "{mapping_yaml}"}
        inputs: {raw_data: "{data_root}/{item.raw}"}
        uses: growth
        outputs:
          results: {path: "{data_root}/processed/{item.stem}", delivery: [download]}
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.enums import DeliveryMode, InputSourceMode

PROVIDED_SENTINEL = "$WILL_PROVIDE$"
"""Marks a default the researcher must supply. Carried over from the current
system, where it is how a job declares its public inputs."""

Name = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_-]*$", max_length=128)]


class _Doc(BaseModel):
    """Reject unknown keys.

    A misspelled key that is silently ignored is the same class of defect as an
    unresolved reference: the author believes they configured something and did
    not. See the 23% finding in ADR 0027.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)


class ComponentRef(_Doc):
    """A reusable graph imported from a component library.

    ``graph`` may be templated. In the real job definitions the graph is chosen
    by a matrix variable (``pipeline: "{variant.pipeline}"``), which is why
    component resolution must happen *after* matrix expansion and why every
    selectable graph has to be enumerable at compile time (ADR 0026).
    """

    library: str = Field(max_length=512)
    graph: str = Field(max_length=256)


class Step(_Doc):
    """One Python call."""

    name: Name
    package: str = Field(max_length=512)
    method: str = Field(max_length=256)
    parameters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("package", "method")
    @classmethod
    def _absolute_dotted_name(cls, value: str) -> str:
        if value.startswith(".") or " " in value:
            raise ValueError("must be an absolute dotted name with no spaces")
        return value


class FanOut(_Doc):
    """How a stage expands into several tasks.

    The three kinds observed in real job definitions, plus ``none``. Items
    expose ``raw``, ``meta`` and ``stem``; ``{item.*}`` resolves only at run
    materialisation, because the item list does not exist until the source is
    enumerated.
    """

    type: Literal["none", "mapping_file", "folders", "patterns"] = "none"
    # mapping_file: a YAML of raw -> meta filename pairs.
    mapping: str | None = Field(default=None, max_length=1024)
    # folders and patterns: the directory to enumerate.
    data_dir: str | None = Field(default=None, max_length=1024)
    # patterns: globs paired by position.
    raw_pattern: str | None = Field(default=None, max_length=256)
    meta_pattern: str | None = Field(default=None, max_length=256)

    def model_post_init(self, _context: Any) -> None:
        required = {
            "none": (),
            "mapping_file": ("mapping",),
            "folders": ("data_dir",),
            "patterns": ("data_dir", "raw_pattern"),
        }[self.type]
        for field in required:
            if getattr(self, field) is None:
                raise ValueError(f"fanout type '{self.type}' requires '{field}'")

    @property
    def is_deferred(self) -> bool:
        """True when the item list can only be known during a run."""
        return self.type != "none"


class OutputSpec(_Doc):
    """A declared output and where it may go."""

    path: str = Field(max_length=1024)
    delivery: list[DeliveryMode] = Field(default_factory=lambda: [DeliveryMode.DOWNLOAD])
    # Which allowlisted shared-storage root a `shared` delivery goes to.
    # Required whenever `shared` is declared: an output cannot be delivered
    # somewhere unspecified, and finding that out at run time rather than at
    # compile time is exactly the class of surprise this format exists to
    # prevent.
    shared_root: str | None = Field(default=None, max_length=128)
    retention_days: int | None = Field(default=None, gt=0)
    optional: bool = False

    def model_post_init(self, _context: Any) -> None:
        if DeliveryMode.SHARED in self.delivery and not self.shared_root:
            raise ValueError("an output delivered to shared storage must name 'shared_root'")


class Stage(_Doc):
    """One step in the pipeline: a graph of calls, optionally fanned out."""

    name: Name
    needs: list[Name] = Field(default_factory=list)
    fanout: FanOut = Field(default_factory=FanOut)
    inputs: dict[str, str] = Field(default_factory=dict)
    # Exactly one of `uses` (a component) or `steps` (inline).
    uses: Name | None = None
    steps: list[Step] = Field(default_factory=list)
    # Overrides applied to a component's steps: step name -> parameter -> value.
    step_parameters: dict[str, dict[str, Any]] = Field(default_factory=dict)
    outputs: dict[str, OutputSpec] = Field(default_factory=dict)
    task_class: Literal["small", "standard", "large", "exclusive"] = "standard"

    def model_post_init(self, _context: Any) -> None:
        if bool(self.uses) == bool(self.steps):
            raise ValueError(f"stage '{self.name}' must declare exactly one of 'uses' or 'steps'")
        if self.step_parameters and not self.uses:
            raise ValueError(
                f"stage '{self.name}': 'step_parameters' overrides a component's steps, "
                "so it is only meaningful with 'uses'"
            )
        seen: set[str] = set()
        for step in self.steps:
            if step.name in seen:
                raise ValueError(f"stage '{self.name}' has duplicate step '{step.name}'")
            seen.add(step.name)
        if self.name in self.needs:
            raise ValueError(f"stage '{self.name}' cannot depend on itself")


class InputPolicy(_Doc):
    """How a public input may be supplied."""

    sources: list[InputSourceMode] = Field(default_factory=lambda: [InputSourceMode.UPLOAD])
    accept: Literal["file", "directory", "value"] = "value"
    type_ref: str | None = Field(default=None, max_length=128)
    help: str | None = Field(default=None, max_length=2048)


class PipelineDocument(_Doc):
    """A complete authoring document."""

    pipeline: Name
    title: str | None = Field(default=None, max_length=256)
    description: str | None = Field(default=None, max_length=4096)
    components: dict[Name, ComponentRef] = Field(default_factory=dict)
    # Matrix: each key maps to a list of rows. The cross product is expanded.
    variables: dict[Name, list[Any]] = Field(default_factory=dict)
    defaults: dict[Name, Any] = Field(default_factory=dict)
    # Policy for defaults marked $WILL_PROVIDE$.
    inputs: dict[Name, InputPolicy] = Field(default_factory=dict)
    stages: list[Stage] = Field(min_length=1)

    @field_validator("stages")
    @classmethod
    def _unique_stage_names(cls, value: list[Stage]) -> list[Stage]:
        seen: set[str] = set()
        for stage in value:
            if stage.name in seen:
                raise ValueError(f"duplicate stage name '{stage.name}'")
            seen.add(stage.name)
        return value

    @field_validator("variables")
    @classmethod
    def _matrix_rows_are_uniform(cls, value: dict[str, list[Any]]) -> dict[str, list[Any]]:
        """Every row of a matrix must define the same attributes.

        A row missing an attribute the others have is what produced the
        unresolved `{variant.group_cols_2}` in 23% of real task specs. Caught
        here, at authoring time, rather than at substitution.
        """
        for key, rows in value.items():
            if not rows:
                raise ValueError(f"matrix variable '{key}' has no rows")
            mappings = [row for row in rows if isinstance(row, dict)]
            if not mappings:
                continue
            if len(mappings) != len(rows):
                raise ValueError(f"matrix variable '{key}' mixes mappings with plain values")
            expected = set(mappings[0])
            for index, row in enumerate(mappings[1:], start=1):
                missing = expected - set(row)
                extra = set(row) - expected
                if missing or extra:
                    detail = []
                    if missing:
                        detail.append(f"missing {sorted(missing)}")
                    if extra:
                        detail.append(f"unexpected {sorted(extra)}")
                    raise ValueError(
                        f"matrix variable '{key}' row {index} is not uniform: "
                        f"{', '.join(detail)}. Every row must define the same attributes."
                    )
        return value

    @property
    def provided_inputs(self) -> tuple[str, ...]:
        """Defaults marked ``$WILL_PROVIDE$``: the public input contract."""
        return tuple(key for key, value in self.defaults.items() if value == PROVIDED_SENTINEL)


class ComponentLibrary(_Doc):
    """A file of reusable named graphs."""

    graphs: dict[Name, list[Step]] = Field(min_length=1)
