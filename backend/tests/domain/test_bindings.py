"""Publication bindings, against a real pipeline with a matrix.

The matrix is the point. One stage `fit` compiles into `fit:no_replicates` and
`fit:replicates`, so a binding that names a stage has to reach both — a field
that silently applies to half a run is the failure this project exists to
prevent.
"""

from __future__ import annotations

import pathlib

import pytest

from app.domain.bindings import (
    FieldBinding,
    apply_bindings,
    infer_value_types,
    validate_bindings,
)
from app.domain.compiler import compile_pipeline
from app.infrastructure.pipeline_loader import DirectoryLibraryLoader, parse_document

ROOT = pathlib.Path(__file__).resolve().parents[3]
COMPONENTS = ROOT / "examples/components"


@pytest.fixture(scope="module")
def growth():
    document = parse_document((ROOT / "examples/pipelines/od600_growth_rates.yaml").read_text())
    result = compile_pipeline(document, load_library=DirectoryLibraryLoader(COMPONENTS))
    assert result.ok, [str(d) for d in result.diagnostics]
    return result.pipeline


def codes(diagnostics) -> set[str]:
    return {item.code for item in diagnostics}


def step_parameter(key: str = "window", **overrides) -> FieldBinding:
    return FieldBinding(
        key=key,
        target="step_parameter",
        stage=overrides.pop("stage", "fit"),
        step=overrides.pop("step", "df_fit_max_growth_rate"),
        binding_key=overrides.pop("binding_key", "moving_window_size"),
    )


# --- validation ------------------------------------------------------------


def test_a_binding_to_a_real_step_parameter_is_accepted(growth):
    assert validate_bindings(growth, [step_parameter()]) == []


def test_a_binding_to_a_public_input_is_accepted(growth):
    binding = FieldBinding(key="folder", target="default_value", binding_key="data_root")
    assert validate_bindings(growth, [binding]) == []


def test_a_binding_to_a_baked_in_default_is_refused(growth):
    """`od600_col` is a plain default, substituted when the pipeline compiled.

    Binding to it would have no effect at all, so it fails the publish rather
    than producing a form control wired to nothing.
    """
    binding = FieldBinding(key="column", target="default_value", binding_key="od600_col")
    diagnostics = validate_bindings(growth, [binding])
    assert "binding.not_a_public_input" in codes(diagnostics)
    # And it says where the value actually lives.
    assert "step parameter" in diagnostics[0].message


def test_a_missing_stage_is_refused_and_names_the_alternatives(growth):
    binding = step_parameter(stage="fitt")
    diagnostics = validate_bindings(growth, [binding])
    assert "binding.stage_not_found" in codes(diagnostics)
    assert "'fit'" in diagnostics[0].message


def test_a_missing_step_is_refused(growth):
    diagnostics = validate_bindings(growth, [step_parameter(step="df_fit")])
    assert "binding.step_not_found" in codes(diagnostics)


def test_a_missing_parameter_is_refused(growth):
    diagnostics = validate_bindings(growth, [step_parameter(binding_key="window")])
    assert "binding.parameter_not_found" in codes(diagnostics)
    assert "moving_window_size" in diagnostics[0].message


def test_a_parameter_present_in_only_one_matrix_row_is_refused(growth):
    """`df_transformed` exists in both graphs, `df_replicate_stats` in one.

    A field that applies to one matrix row and not the other is worse than one
    that is refused, because nothing about the run says so.
    """
    diagnostics = validate_bindings(growth, [step_parameter(step="df_replicate_stats")])
    assert "binding.step_not_found" in codes(diagnostics)


def test_a_stage_input_binding_is_accepted(growth):
    binding = FieldBinding(key="raw", target="stage_input", stage="fit", binding_key="raw_data")
    assert validate_bindings(growth, [binding]) == []


def test_a_stage_output_binding_is_accepted(growth):
    binding = FieldBinding(key="results", target="stage_output", stage="fit", binding_key="results")
    assert validate_bindings(growth, [binding]) == []


def test_two_fields_cannot_share_a_key(growth):
    diagnostics = validate_bindings(growth, [step_parameter(), step_parameter()])
    assert "binding.duplicate_field" in codes(diagnostics)


def test_every_problem_is_reported_not_just_the_first(growth):
    diagnostics = validate_bindings(
        growth,
        [
            step_parameter(key="a", stage="nope"),
            FieldBinding(key="b", target="default_value", binding_key="nope"),
        ],
    )
    assert len(diagnostics) == 2


# --- recorded types --------------------------------------------------------


def test_the_type_at_the_target_is_recorded(growth):
    """So a later revision changing a number to a path is detectable rather
    than failing inside a container."""
    types = infer_value_types(growth, [step_parameter()])
    assert types["window"] == "integer"


def test_a_public_input_records_what_it_accepts(growth):
    binding = FieldBinding(key="folder", target="default_value", binding_key="data_root")
    assert infer_value_types(growth, [binding])["folder"] == "directory"


# --- application -----------------------------------------------------------


def test_a_step_parameter_binding_reaches_every_matrix_row(growth):
    """The whole reason a binding names a stage rather than a stage key."""
    bound = apply_bindings(growth, [step_parameter()], {"window": 9})
    for stage in bound.pipeline.stages:
        step = next(s for s in stage.steps if s.name == "df_fit_max_growth_rate")
        assert step.parameters["moving_window_size"] == 9, stage.key


def test_the_stored_revision_is_not_touched(growth):
    """It is immutable and may already be in use by another publication."""
    before = growth.stages[0].steps[-1].parameters["moving_window_size"]
    apply_bindings(growth, [step_parameter()], {"window": 9})
    assert growth.stages[0].steps[-1].parameters["moving_window_size"] == before


def test_a_field_left_blank_leaves_the_pipeline_s_own_value(growth):
    bound = apply_bindings(growth, [step_parameter()], {})
    step = next(s for s in bound.pipeline.stages[0].steps if s.name == "df_fit_max_growth_rate")
    assert step.parameters["moving_window_size"] == 5


def test_a_public_input_binding_becomes_a_submitted_value(growth):
    binding = FieldBinding(key="folder", target="default_value", binding_key="data_root")
    bound = apply_bindings(growth, [binding], {"folder": "/mnt/lab/run7"})
    assert bound.values == {"data_root": "/mnt/lab/run7"}


def test_a_stage_input_binding_overrides_that_input(growth):
    binding = FieldBinding(key="raw", target="stage_input", stage="fit", binding_key="raw_data")
    bound = apply_bindings(growth, [binding], {"raw": "/mnt/lab/override.csv"})
    for stage in bound.pipeline.stages:
        assert stage.inputs["raw_data"] == "/mnt/lab/override.csv"


def test_other_parameters_are_left_alone(growth):
    bound = apply_bindings(growth, [step_parameter()], {"window": 9})
    step = next(s for s in bound.pipeline.stages[0].steps if s.name == "df_fit_max_growth_rate")
    assert step.parameters["time_col"] == "time_h"
