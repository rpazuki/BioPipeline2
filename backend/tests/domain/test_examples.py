"""Every example pipeline must compile.

The examples are the format's regression suite. They are modelled on real
pipelines, so a change that breaks one is a change that would have broken an
author's document.
"""

from __future__ import annotations

import pathlib

import pytest

from app.domain.compiler import compile_pipeline
from app.infrastructure.pipeline_loader import (
    DirectoryLibraryLoader,
    LibraryNotFound,
    parse_document,
    parse_library,
)

ROOT = pathlib.Path(__file__).resolve().parents[3]
PIPELINES = sorted((ROOT / "examples/pipelines").glob("*.yaml"))
COMPONENTS = ROOT / "examples/components"


def _compile(path: pathlib.Path):
    document = parse_document(path.read_text())
    return compile_pipeline(document, load_library=DirectoryLibraryLoader(COMPONENTS))


def test_there_are_examples_to_check():
    assert PIPELINES, "examples/pipelines contains no documents"


@pytest.mark.parametrize("path", PIPELINES, ids=lambda p: p.stem)
def test_every_example_compiles_without_errors(path: pathlib.Path):
    result = _compile(path)
    assert result.ok, "\n".join(str(d) for d in result.errors)


@pytest.mark.parametrize("path", PIPELINES, ids=lambda p: p.stem)
def test_every_example_compiles_deterministically(path: pathlib.Path):
    assert _compile(path).pipeline.graph_hash == _compile(path).pipeline.graph_hash


# --- the growth-rate example in detail ------------------------------------


@pytest.fixture
def growth():
    return _compile(ROOT / "examples/pipelines/od600_growth_rates.yaml").pipeline


def test_the_matrix_produces_one_stage_per_variant(growth):
    assert set(growth.stage_keys) == {"fit:no_replicates", "fit:replicates"}


def test_each_variant_pins_its_own_component_graph(growth):
    chosen = {stage.key: stage.component.graph for stage in growth.stages}
    assert chosen == {
        "fit:no_replicates": "growth_rate_fit_pipeline",
        "fit:replicates": "growth_rate_replicates_fit_pipeline",
    }


def test_every_selectable_graph_is_pinned_not_just_the_first(growth):
    """The IR must stay self-contained, so all graphs the matrix can reach are
    recorded with a digest."""
    assert len(growth.components) == 2
    assert all(pin.digest.startswith("sha256:") for pin in growth.components)


def test_provided_inputs_become_the_public_contract(growth):
    assert [i.key for i in growth.inputs] == ["data_root", "mapping_yaml"]
    data_root = next(i for i in growth.inputs if i.key == "data_root")
    assert data_root.accept == "directory"
    assert "shared" in data_root.sources


def test_a_whole_value_reference_keeps_its_type(growth):
    """`moving_window_size: "{moving_window_size}"` must be the integer 5."""
    stage = growth.stage("fit:no_replicates")
    step = next(s for s in stage.steps if s.name == "df_fit_max_growth_rate")
    assert step.parameters["moving_window_size"] == 5
    assert isinstance(step.parameters["moving_window_size"], int)


def test_item_references_remain_deferred_for_run_materialisation(growth):
    """Partial rendering: `{data_root}` is substituted at compile time and
    `{item.raw}` survives for run materialisation."""
    stage = growth.stage("fit:no_replicates")
    raw = stage.inputs["raw_data"]
    assert "{item.raw}" in raw
    assert "{data_root}" not in raw
    assert stage.is_fanned_out


def test_the_fanout_source_itself_is_resolved_at_compile_time(growth):
    """The mapping path has no item reference, so it resolves now."""
    stage = growth.stage("fit:no_replicates")
    assert "{item." not in (stage.fanout.mapping or "")


def test_output_paths_carry_the_variant_and_the_item(growth):
    """The bug this pins down: an all-or-nothing renderer left the whole path
    untouched, so the matrix row never reached the output directory and both
    variants would have written to the same place."""
    stage = growth.stage("fit:replicates")
    [output] = stage.outputs
    assert "/processed/replicates/" in output.path
    assert "{item.stem}" in output.path
    assert output.has_deferred


def test_the_two_variants_write_to_different_directories(growth):
    paths = {stage.outputs[0].path for stage in growth.stages}
    assert len(paths) == 2, f"variants share an output path: {paths}"


# --- the loader -----------------------------------------------------------


def test_the_projects_own_library_shape_loads():
    """`pipelines:` with a `Processes:` block, as existing libraries are written."""
    library = parse_library((COMPONENTS / "growth_rates.yaml").read_text())
    assert "growth_rate_fit_pipeline" in library.graphs
    steps = library.graphs["growth_rate_fit_pipeline"]
    assert steps[0].package == "labUtils.media_bot"


def test_a_library_reference_may_not_escape_its_root():
    """Library references are author-supplied text."""
    loader = DirectoryLibraryLoader(COMPONENTS)
    with pytest.raises(LibraryNotFound, match="outside the library root"):
        loader("../../etc/passwd")


def test_a_missing_library_is_reported_clearly():
    loader = DirectoryLibraryLoader(COMPONENTS)
    with pytest.raises(LibraryNotFound, match="does not exist"):
        loader("nope.yaml")


def test_a_process_missing_its_package_is_rejected():
    from app.domain.errors import ValidationFailed

    with pytest.raises(ValidationFailed, match="missing package"):
        parse_library("pipelines:\n  - g:\n      Processes:\n        - a:\n            method: f\n")
