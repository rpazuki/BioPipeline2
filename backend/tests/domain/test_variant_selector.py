import pytest

from app.domain.compiler import compile_pipeline
from app.domain.materialise import materialise
from app.infrastructure.pipeline_loader import parse_document

SOURCE = """pipeline: choose_variant
defaults: {method: $WILL_PROVIDE$}
inputs: {method: {accept: value, selects_variant: true}}
variables:
  method:
    - {name: first, factor: 2}
    - {name: second, factor: 3}
stages:
  - name: prepare
    steps:
      - {name: result, package: builtins, method: str, parameters: {object: '{variant.factor}'}}
  - name: finish
    needs: [prepare]
    steps:
      - {name: result, package: builtins, method: str, parameters: {object: done}}
"""


def test_selection_keeps_only_the_chosen_compiled_variant_and_its_dependencies():
    compiled = compile_pipeline(parse_document(SOURCE)).pipeline
    assert compiled is not None
    original = compiled.model_dump()
    selected = materialise(compiled, {"method": "second"})
    assert selected.ok
    assert [task.stage_key for task in selected.tasks] == ["prepare:second", "finish:second"]
    assert selected.tasks[0].steps[0]["parameters"]["object"] == 3
    assert selected.tasks[1].needs == (selected.tasks[0].task_key,)
    assert compiled.model_dump() == original


@pytest.mark.parametrize("value", ["unknown", [], None, {"name": "first"}])
def test_invalid_selection_cannot_create_any_tasks(value):
    compiled = compile_pipeline(parse_document(SOURCE)).pipeline
    result = materialise(compiled, {"method": value})
    assert not result.ok
    assert not result.tasks
    assert result.errors[0].location == "inputs.method"


def test_matrix_without_selector_still_runs_every_variant():
    compiled = compile_pipeline(
        parse_document(SOURCE.replace("selects_variant: true", "selects_variant: false"))
    ).pipeline
    assert len(materialise(compiled, {"method": "first"}).tasks) == 4


def test_an_invalid_selector_is_a_compile_error():
    result = compile_pipeline(
        parse_document(
            SOURCE.replace("defaults: {method: $WILL_PROVIDE$}", "defaults: {method: first}")
        )
    )
    assert not result.ok
    assert any(item.code == "matrix.invalid_selector" for item in result.errors)
