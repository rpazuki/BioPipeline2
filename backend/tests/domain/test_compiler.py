"""Compiler tests.

Every rejection rule has a named test. The cases under "real-world defects"
reproduce failures found in a real deployment, where 23% of task
specifications carried an unresolved reference and the system reported success
regardless.
"""

from __future__ import annotations

import pytest

from app.domain.authoring import ComponentLibrary, PipelineDocument
from app.domain.compiler import compile_pipeline


def doc(**kwargs) -> PipelineDocument:
    base = {
        "pipeline": "test",
        "stages": [{"name": "s", "steps": [{"name": "a", "package": "m", "method": "f"}]}],
    }
    return PipelineDocument(**{**base, **kwargs})


def codes(result) -> set[str]:
    return {d.code for d in result.diagnostics}


GROWTH = ComponentLibrary(
    graphs={
        "growth_rate_fit_pipeline": [
            {"name": "df_parsed", "package": "labUtils.media_bot", "method": "parse"},
            {
                "name": "df_fit_max_growth_rate",
                "package": "labUtils.growth_rates",
                "method": "fit",
                "parameters": {"moving_window_size": 5},
            },
        ],
        "growth_rate_replicates_fit_pipeline": [
            {"name": "df_parsed", "package": "labUtils.media_bot", "method": "parse"},
        ],
    }
)


def library(_path: str) -> ComponentLibrary:
    return GROWTH


# --- the happy path -------------------------------------------------------


def test_a_minimal_pipeline_compiles():
    result = compile_pipeline(doc())
    assert result.ok
    assert result.pipeline is not None
    assert result.pipeline.stage_keys == ("s",)


def test_defaults_are_substituted_with_their_type_intact():
    result = compile_pipeline(
        doc(
            defaults={"threads": 8},
            stages=[
                {
                    "name": "s",
                    "steps": [
                        {
                            "name": "a",
                            "package": "m",
                            "method": "f",
                            "parameters": {"n": "{threads}", "label": "n={threads}"},
                        }
                    ],
                }
            ],
        )
    )
    parameters = result.pipeline.stages[0].steps[0].parameters
    assert parameters["n"] == 8 and isinstance(parameters["n"], int)
    assert parameters["label"] == "n=8"


def test_compilation_is_deterministic():
    """Identical source must yield an identical hash, or caching and the
    revision model are both unsound."""
    first = compile_pipeline(doc(defaults={"a": 1}))
    second = compile_pipeline(doc(defaults={"a": 1}))
    assert first.pipeline.graph_hash == second.pipeline.graph_hash


def test_a_different_graph_yields_a_different_hash():
    first = compile_pipeline(
        doc(
            defaults={"a": 1},
            stages=[
                {
                    "name": "s",
                    "steps": [
                        {"name": "x", "package": "m", "method": "f", "parameters": {"n": "{a}"}}
                    ],
                }
            ],
        )
    )
    second = compile_pipeline(
        doc(
            defaults={"a": 2},
            stages=[
                {
                    "name": "s",
                    "steps": [
                        {"name": "x", "package": "m", "method": "f", "parameters": {"n": "{a}"}}
                    ],
                }
            ],
        )
    )
    assert first.pipeline.graph_hash != second.pipeline.graph_hash


def test_a_default_nothing_references_does_not_change_the_hash():
    """The hash is over the compiled graph, not the source. Two documents that
    compile identically are identical, which is what lets the compiler skip a
    rebuild."""
    assert (
        compile_pipeline(doc(defaults={"unused": 1})).pipeline.graph_hash
        == compile_pipeline(doc(defaults={"unused": 2})).pipeline.graph_hash
    )


def test_a_matrix_variable_may_be_called_variant():
    """It is what the real job definitions call it. Only a *default* named
    'variant' would shadow the namespace."""
    result = compile_pipeline(doc(variables={"variant": [{"name": "a"}]}))
    assert result.ok


def test_public_inputs_are_derived_from_the_provided_sentinel():
    result = compile_pipeline(doc(defaults={"data_root": "$WILL_PROVIDE$", "od600_col": "od600"}))
    assert [i.key for i in result.pipeline.inputs] == ["data_root"]


# --- matrix ---------------------------------------------------------------


def test_a_matrix_expands_one_stage_per_row():
    result = compile_pipeline(doc(variables={"variant": [{"name": "a"}, {"name": "b"}]}))
    assert set(result.pipeline.stage_keys) == {"s:a", "s:b"}


def test_matrix_attributes_resolve_per_row():
    result = compile_pipeline(
        doc(
            variables={
                "variant": [
                    {"name": "no_replicates", "group_cols": "well"},
                    {"name": "replicates", "group_cols": "group_id"},
                ]
            },
            stages=[
                {
                    "name": "s",
                    "steps": [
                        {
                            "name": "a",
                            "package": "m",
                            "method": "f",
                            "parameters": {"cols": "{variant.group_cols}"},
                        }
                    ],
                }
            ],
        )
    )
    got = {st.key: st.steps[0].parameters["cols"] for st in result.pipeline.stages}
    assert got == {"s:no_replicates": "well", "s:replicates": "group_id"}


def test_an_oversized_matrix_is_rejected():
    result = compile_pipeline(doc(variables={f"v{i}": list(range(4)) for i in range(6)}))
    assert "matrix.too_large" in codes(result)


def test_matrix_rows_must_be_uniform():
    """Caught at parse time: a row missing an attribute the others have is
    what produced the unresolved reference in 23% of real task specs."""
    with pytest.raises(ValueError, match="not uniform"):
        doc(variables={"variant": [{"name": "a", "x": 1}, {"name": "b"}]})


# --- real-world defects ---------------------------------------------------


def test_an_unresolvable_reference_is_an_error_not_an_empty_string():
    result = compile_pipeline(
        doc(
            stages=[
                {
                    "name": "s",
                    "steps": [
                        {
                            "name": "a",
                            "package": "m",
                            "method": "f",
                            "parameters": {"x": "{custom_rules}"},
                        }
                    ],
                }
            ]
        )
    )
    assert not result.ok
    assert "reference.unresolved" in codes(result)


def test_an_override_naming_a_nonexistent_step_is_an_error():
    """The second silent failure: the override was dropped without a warning."""
    result = compile_pipeline(
        doc(
            components={"growth": {"library": "g.yaml", "graph": "growth_rate_fit_pipeline"}},
            stages=[
                {
                    "name": "s",
                    "uses": "growth",
                    "step_parameters": {"df_combined_fit_2": {"on_cols": ["x"]}},
                }
            ],
        ),
        load_library=library,
    )
    assert not result.ok
    assert "override.unknown_step" in codes(result)
    assert "df_combined_fit_2" in str(result.errors[0])


def test_an_override_of_a_real_step_is_applied():
    result = compile_pipeline(
        doc(
            components={"growth": {"library": "g.yaml", "graph": "growth_rate_fit_pipeline"}},
            stages=[
                {
                    "name": "s",
                    "uses": "growth",
                    "step_parameters": {"df_fit_max_growth_rate": {"moving_window_size": 9}},
                }
            ],
        ),
        load_library=library,
    )
    assert result.ok
    step = next(s for s in result.pipeline.stages[0].steps if s.name == "df_fit_max_growth_rate")
    assert step.parameters["moving_window_size"] == 9


# --- components -----------------------------------------------------------


def test_a_component_is_expanded_and_pinned():
    result = compile_pipeline(
        doc(
            components={"growth": {"library": "g.yaml", "graph": "growth_rate_fit_pipeline"}},
            stages=[{"name": "s", "uses": "growth"}],
        ),
        load_library=library,
    )
    assert result.ok
    assert [s.name for s in result.pipeline.stages[0].steps] == [
        "df_parsed",
        "df_fit_max_growth_rate",
    ]
    pin = result.pipeline.components[0]
    assert pin.graph == "growth_rate_fit_pipeline"
    assert pin.digest.startswith("sha256:")


def test_a_component_selected_by_a_matrix_variable_resolves_per_row():
    """The constraint that forces component resolution after matrix expansion:
    real job definitions write `pipeline: "{variant.pipeline}"`."""
    result = compile_pipeline(
        doc(
            components={"growth": {"library": "g.yaml", "graph": "{variant.graph}"}},
            variables={
                "variant": [
                    {"name": "plain", "graph": "growth_rate_fit_pipeline"},
                    {"name": "reps", "graph": "growth_rate_replicates_fit_pipeline"},
                ]
            },
            stages=[{"name": "s", "uses": "growth"}],
        ),
        load_library=library,
    )
    assert result.ok
    per_row = {st.key: st.component.graph for st in result.pipeline.stages}
    assert per_row == {
        "s:plain": "growth_rate_fit_pipeline",
        "s:reps": "growth_rate_replicates_fit_pipeline",
    }
    # Every selectable graph is pinned, not just one.
    assert len(result.pipeline.components) == 2


def test_a_component_selection_that_cannot_be_enumerated_is_rejected():
    """A graph chosen from a runtime-supplied value would make the IR
    non-self-contained."""
    result = compile_pipeline(
        doc(
            components={"growth": {"library": "g.yaml", "graph": "{item.stem}"}},
            stages=[
                {"name": "s", "uses": "growth", "fanout": {"type": "folders", "data_dir": "/d"}}
            ],
        ),
        load_library=library,
    )
    assert not result.ok
    assert "component.unresolvable_selection" in codes(result)


def test_an_undeclared_component_is_rejected():
    result = compile_pipeline(doc(stages=[{"name": "s", "uses": "ghost"}]), load_library=library)
    assert "component.unknown" in codes(result)


def test_an_unknown_graph_in_a_known_library_is_rejected():
    result = compile_pipeline(
        doc(
            components={"growth": {"library": "g.yaml", "graph": "nope"}},
            stages=[{"name": "s", "uses": "growth"}],
        ),
        load_library=library,
    )
    assert "component.graph_unknown" in codes(result)
    assert "growth_rate_fit_pipeline" in str(result.errors[0])


def test_an_unreadable_library_is_a_diagnostic_not_a_crash():
    def broken(_path: str) -> ComponentLibrary:
        raise FileNotFoundError("g.yaml")

    result = compile_pipeline(
        doc(
            components={"growth": {"library": "g.yaml", "graph": "x"}},
            stages=[{"name": "s", "uses": "growth"}],
        ),
        load_library=broken,
    )
    assert "component.library_unreadable" in codes(result)


def test_importing_without_a_loader_is_reported():
    result = compile_pipeline(
        doc(
            components={"growth": {"library": "g.yaml", "graph": "x"}},
            stages=[{"name": "s", "uses": "growth"}],
        )
    )
    assert "component.no_loader" in codes(result)


# --- fan-out --------------------------------------------------------------


def test_item_references_survive_compilation_as_deferred():
    result = compile_pipeline(
        doc(
            defaults={"root": "/data"},
            stages=[
                {
                    "name": "s",
                    "fanout": {"type": "mapping_file", "mapping": "{root}/map.yaml"},
                    "inputs": {"raw": "{root}/{item.raw}"},
                    "steps": [{"name": "a", "package": "m", "method": "f"}],
                }
            ],
        )
    )
    assert result.ok
    stage = result.pipeline.stages[0]
    assert stage.fanout.mapping == "/data/map.yaml"
    # Partial: the resolvable half is substituted now, the item half is not.
    assert stage.inputs["raw"] == "/data/{item.raw}"
    assert stage.is_fanned_out


def test_a_lone_item_reference_is_preserved_whole():
    """Nothing else to substitute, and whole-value semantics apply on the
    second pass at run materialisation."""
    result = compile_pipeline(
        doc(
            stages=[
                {
                    "name": "s",
                    "fanout": {"type": "folders", "data_dir": "/d"},
                    "inputs": {"dir": "{item.stem}"},
                    "steps": [{"name": "a", "package": "m", "method": "f"}],
                }
            ]
        )
    )
    assert result.pipeline.stages[0].inputs["dir"] == "{item.stem}"


def test_an_item_reference_without_a_fanout_is_rejected():
    result = compile_pipeline(
        doc(
            stages=[
                {
                    "name": "s",
                    "inputs": {"raw": "{item.raw}"},
                    "steps": [{"name": "a", "package": "m", "method": "f"}],
                }
            ]
        )
    )
    assert not result.ok
    assert "reference.item_outside_fanout" in codes(result)


def test_a_fanout_missing_its_source_is_rejected_at_parse_time():
    with pytest.raises(ValueError, match="requires 'mapping'"):
        doc(
            stages=[
                {
                    "name": "s",
                    "fanout": {"type": "mapping_file"},
                    "steps": [{"name": "a", "package": "m", "method": "f"}],
                }
            ]
        )


# --- graph ----------------------------------------------------------------


def test_an_unknown_dependency_is_rejected():
    result = compile_pipeline(
        doc(
            stages=[
                {
                    "name": "s",
                    "needs": ["ghost"],
                    "steps": [{"name": "a", "package": "m", "method": "f"}],
                }
            ]
        )
    )
    assert "graph.unknown_dependency" in codes(result)


def test_a_dependency_cycle_is_rejected():
    result = compile_pipeline(
        doc(
            stages=[
                {
                    "name": "a",
                    "needs": ["b"],
                    "steps": [{"name": "x", "package": "m", "method": "f"}],
                },
                {
                    "name": "b",
                    "needs": ["a"],
                    "steps": [{"name": "y", "package": "m", "method": "f"}],
                },
            ]
        )
    )
    assert not result.ok
    assert "graph.cycle" in codes(result)


def test_a_self_dependency_is_rejected_at_parse_time():
    with pytest.raises(ValueError, match="cannot depend on itself"):
        doc(
            stages=[
                {
                    "name": "s",
                    "needs": ["s"],
                    "steps": [{"name": "a", "package": "m", "method": "f"}],
                }
            ]
        )


def test_dependencies_are_scoped_to_the_matrix_row():
    """Row A's second stage must depend on row A's first, not row B's."""
    result = compile_pipeline(
        doc(
            variables={"variant": [{"name": "x"}, {"name": "y"}]},
            stages=[
                {"name": "one", "steps": [{"name": "a", "package": "m", "method": "f"}]},
                {
                    "name": "two",
                    "needs": ["one"],
                    "steps": [{"name": "b", "package": "m", "method": "f"}],
                },
            ],
        )
    )
    two_x = next(s for s in result.pipeline.stages if s.key == "two:x")
    assert two_x.needs == ["one:x"]


# --- names and policy -----------------------------------------------------


def test_a_reserved_name_is_rejected():
    result = compile_pipeline(doc(defaults={"variant": 1}))
    assert "name.reserved" in codes(result)


def test_an_input_policy_without_a_provided_default_warns():
    result = compile_pipeline(doc(defaults={"a": 1}, inputs={"a": {"accept": "file"}}))
    assert result.ok
    assert "input.not_provided" in codes(result)


def test_every_error_carries_a_location():
    result = compile_pipeline(
        doc(
            stages=[
                {
                    "name": "s",
                    "steps": [
                        {"name": "a", "package": "m", "method": "f", "parameters": {"x": "{nope}"}}
                    ],
                }
            ]
        )
    )
    assert all(d.location for d in result.errors)


def test_errors_are_collected_not_raised_on_the_first():
    """An author fixing a document should see everything at once."""
    result = compile_pipeline(
        doc(
            defaults={"variant": 1},
            stages=[
                {
                    "name": "s",
                    "needs": ["ghost"],
                    "steps": [
                        {"name": "a", "package": "m", "method": "f", "parameters": {"x": "{nope}"}}
                    ],
                }
            ],
        )
    )
    assert len(result.errors) >= 3
    assert {"name.reserved", "reference.unresolved", "graph.unknown_dependency"} <= codes(result)


# --- delivery declarations ------------------------------------------------


def test_a_shared_delivery_must_name_its_root():
    """An output cannot be delivered somewhere unspecified. Catching it at
    authoring time beats discovering it when a run tries to deliver."""
    with pytest.raises(ValueError, match="must name 'shared_root'"):
        doc(
            stages=[
                {
                    "name": "s",
                    "steps": [{"name": "a", "package": "m", "method": "f"}],
                    "outputs": {"o": {"path": "outputs/o", "delivery": ["shared"]}},
                }
            ]
        )


def test_a_shared_delivery_with_a_root_compiles():
    result = compile_pipeline(
        doc(
            stages=[
                {
                    "name": "s",
                    "steps": [{"name": "a", "package": "m", "method": "f"}],
                    "outputs": {
                        "o": {
                            "path": "outputs/o",
                            "delivery": ["download", "shared"],
                            "shared_root": "lab_results",
                        }
                    },
                }
            ]
        )
    )
    assert result.ok
    assert result.pipeline.stages[0].outputs[0].shared_root == "lab_results"


def test_a_download_only_output_needs_no_root():
    result = compile_pipeline(
        doc(
            stages=[
                {
                    "name": "s",
                    "steps": [{"name": "a", "package": "m", "method": "f"}],
                    "outputs": {"o": {"path": "outputs/o"}},
                }
            ]
        )
    )
    assert result.ok
    assert result.pipeline.stages[0].outputs[0].shared_root is None
