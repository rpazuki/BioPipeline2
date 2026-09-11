"""Run materialisation: compiled pipeline plus submitted values become tasks."""

from __future__ import annotations

import pathlib

import pytest

from app.domain.compiler import compile_pipeline
from app.domain.materialise import (
    DEFAULT_RESOURCES,
    coerce_value,
    folder_items,
    mapping_file_items,
    materialise,
)
from app.infrastructure.pipeline_loader import DirectoryLibraryLoader, parse_document

ROOT = pathlib.Path(__file__).resolve().parents[3]


@pytest.fixture
def growth():
    document = parse_document((ROOT / "examples/pipelines/od600_growth_rates.yaml").read_text())
    result = compile_pipeline(
        document, load_library=DirectoryLibraryLoader(ROOT / "examples/components")
    )
    assert result.ok
    return result.pipeline


MAPPING = {
    "mediabotJLF1.csv": "protocol_metadata_1.csv",
    "mediabotJLF2.csv": "protocol_metadata_2.csv",
    "mediabotJLF3.csv": "protocol_metadata_2.csv",
}


def enumerate_mapping(_fanout):
    return mapping_file_items(MAPPING)


def codes(result) -> set[str]:
    return {d.code for d in result.diagnostics}


VALUES = {"data_root": "/data/run1", "mapping_yaml": "/data/run1/mapping.yaml"}


# --- inputs ---------------------------------------------------------------


def test_a_missing_required_input_is_an_error(growth):
    result = materialise(growth, {"data_root": "/data"}, enumerate_fanout=enumerate_mapping)
    assert not result.ok
    assert "input.missing" in codes(result)


def test_an_unexpected_input_is_a_warning_not_an_error(growth):
    result = materialise(growth, {**VALUES, "surprise": 1}, enumerate_fanout=enumerate_mapping)
    assert result.ok
    assert "input.unexpected" in codes(result)


def test_a_path_input_must_be_a_path(growth):
    result = materialise(growth, {**VALUES, "data_root": 42}, enumerate_fanout=enumerate_mapping)
    assert not result.ok
    assert "input.invalid" in codes(result)


# --- coercion -------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "target", "expected"),
    [
        ("200", "integer", 200),
        (" 42 ", "integer", 42),
        ("24.0", "number", 24.0),
        ("0.5", "number", 0.5),
        ("true", "boolean", True),
        ("False", "boolean", False),
        ("1", "boolean", True),
    ],
)
def test_form_strings_are_coerced(raw, target, expected):
    """Real submissions arrive as strings against a library declaring numbers."""
    assert coerce_value(raw, target, "k") == expected


@pytest.mark.parametrize(
    ("raw", "target"), [("abc", "integer"), ("1.5", "integer"), ("maybe", "boolean")]
)
def test_a_value_that_cannot_be_coerced_fails_loudly(raw, target):
    with pytest.raises(ValueError, match="k"):
        coerce_value(raw, target, "k")


def test_a_boolean_is_not_silently_an_integer():
    with pytest.raises(ValueError, match="got a boolean"):
        coerce_value(True, "integer", "k")


# --- fan-out --------------------------------------------------------------


def test_fanout_produces_one_task_per_item_per_variant(growth):
    result = materialise(growth, VALUES, enumerate_fanout=enumerate_mapping)
    assert result.ok
    # 2 matrix rows x 3 mapping entries
    assert len(result.tasks) == 6


def test_task_keys_are_unique_and_readable(growth):
    result = materialise(growth, VALUES, enumerate_fanout=enumerate_mapping)
    keys = [task.task_key for task in result.tasks]
    assert len(set(keys)) == len(keys)
    assert "fit:no_replicates:mediabotJLF1" in keys


def test_item_references_are_finished_at_materialisation(growth):
    result = materialise(growth, VALUES, enumerate_fanout=enumerate_mapping)
    task = next(t for t in result.tasks if t.task_key.endswith("mediabotJLF1"))
    assert task.inputs["raw_data"] == "/data/run1/mediabotJLF1.csv"
    assert task.inputs["meta_data"] == "/data/run1/protocol_metadata_1.csv"
    assert "{" not in task.inputs["raw_data"]


def test_output_paths_carry_both_the_variant_and_the_item(growth):
    result = materialise(growth, VALUES, enumerate_fanout=enumerate_mapping)
    paths = {task.outputs[0]["path"] for task in result.tasks}
    assert len(paths) == 6, "tasks share an output directory"
    assert "/data/run1/processed/replicates/mediabotJLF2" in paths


def test_an_empty_fanout_source_is_an_error(growth):
    """A run that would do nothing is a mistake, not a success."""
    result = materialise(growth, VALUES, enumerate_fanout=lambda _f: [])
    assert not result.ok
    assert "fanout.empty" in codes(result)


def test_a_failing_enumerator_becomes_a_diagnostic_not_a_crash(growth):
    def broken(_fanout):
        raise FileNotFoundError("mapping.yaml")

    result = materialise(growth, VALUES, enumerate_fanout=broken)
    assert not result.ok
    assert "fanout.unresolvable" in codes(result)


def test_fanning_out_without_an_enumerator_is_reported(growth):
    result = materialise(growth, VALUES)
    assert not result.ok
    assert "fanout.no_enumerator" in codes(result)


def test_the_fanout_source_itself_resolves_from_submitted_values(growth):
    seen: list[str] = []

    def capture(fanout):
        seen.append(fanout.mapping or "")
        return mapping_file_items(MAPPING)

    materialise(growth, VALUES, enumerate_fanout=capture)
    assert seen and all(path == "/data/run1/mapping.yaml" for path in seen)


# --- steps and resources --------------------------------------------------


def test_component_steps_are_carried_into_every_task(growth):
    result = materialise(growth, VALUES, enumerate_fanout=enumerate_mapping)
    task = next(t for t in result.tasks if t.stage_key == "fit:no_replicates")
    assert [step["name"] for step in task.steps] == [
        "df_parsed",
        "df_transformed",
        "df_fit_max_growth_rate",
    ]


def test_each_variant_runs_its_own_component_graph(growth):
    result = materialise(growth, VALUES, enumerate_fanout=enumerate_mapping)
    plain = next(t for t in result.tasks if t.stage_key == "fit:no_replicates")
    reps = next(t for t in result.tasks if t.stage_key == "fit:replicates")
    assert "df_transformed" in {s["name"] for s in plain.steps}
    assert "df_replicate_stats" in {s["name"] for s in reps.steps}


def test_overridden_parameters_keep_their_compiled_type(growth):
    result = materialise(growth, VALUES, enumerate_fanout=enumerate_mapping)
    task = result.tasks[0]
    step = next(s for s in task.steps if s["name"] == "df_fit_max_growth_rate")
    assert step["parameters"]["moving_window_size"] == 5
    assert isinstance(step["parameters"]["moving_window_size"], int)


def test_tasks_carry_a_resource_request(growth):
    result = materialise(growth, VALUES, enumerate_fanout=enumerate_mapping)
    resources = result.tasks[0].resources
    assert resources == DEFAULT_RESOURCES["standard"]
    assert resources.cpu_millicores > 0 and resources.memory_bytes > 0


# --- dependencies ---------------------------------------------------------


def _two_stage(fanout_second: bool):
    document = parse_document(
        f"""
pipeline: two_stage
defaults: {{root: /d}}
stages:
  - name: first
    fanout: {{type: folders, data_dir: "{{root}}"}}
    steps:
      - {{name: a, package: m, method: f}}
    outputs:
      out: {{path: "{{root}}/{{item.stem}}"}}
  - name: second
    needs: [first]
    {"fanout: {type: folders, data_dir: '{root}'}" if fanout_second else ""}
    steps:
      - {{name: b, package: m, method: g}}
"""
    )
    result = compile_pipeline(document)
    assert result.ok, [str(d) for d in result.errors]
    return result.pipeline


def test_a_gather_stage_waits_for_every_upstream_task():
    pipeline = _two_stage(fanout_second=False)
    result = materialise(pipeline, {}, enumerate_fanout=lambda _f: folder_items(["a", "b", "c"]))
    assert result.ok
    second = next(t for t in result.tasks if t.stage_name == "second")
    assert len(second.needs) == 3


def test_dependencies_are_conservative_when_both_stages_fan_out():
    """Pairing item-by-item would be more parallel but is only correct when
    both stages enumerate the same source in the same order, which the format
    does not guarantee."""
    pipeline = _two_stage(fanout_second=True)
    result = materialise(pipeline, {}, enumerate_fanout=lambda _f: folder_items(["a", "b"]))
    second = [t for t in result.tasks if t.stage_name == "second"]
    assert len(second) == 2
    assert all(len(task.needs) == 2 for task in second)


def test_the_first_stage_has_no_dependencies():
    pipeline = _two_stage(fanout_second=False)
    result = materialise(pipeline, {}, enumerate_fanout=lambda _f: folder_items(["a"]))
    first = next(t for t in result.tasks if t.stage_name == "first")
    assert first.needs == ()


# --- helpers --------------------------------------------------------------


def test_mapping_items_expose_raw_meta_and_stem():
    [item] = mapping_file_items({"run1.csv": "meta1.csv"})
    assert item == {"raw": "run1.csv", "meta": "meta1.csv", "stem": "run1"}


def test_a_stem_strips_directories_and_the_extension():
    [item] = mapping_file_items({"sub/dir/run.2.csv": "m.csv"})
    assert item["stem"] == "run.2"
