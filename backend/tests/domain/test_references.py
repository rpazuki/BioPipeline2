"""Tests for the `{brace}` reference language.

Every rejection rule has a named test, because the compiler's safety rests on
this module refusing bad input rather than silently coercing it. The cases
under "real-world regressions" come from the actual deployment.
"""

from __future__ import annotations

import pytest

from app.domain.errors import ExpressionError
from app.domain.references import (
    Namespace,
    ResolutionContext,
    check_reserved_names,
    parse,
    render,
    render_tree,
    walk_templates,
)


def ctx(**kwargs) -> ResolutionContext:
    return ResolutionContext(**kwargs)


# --- parsing --------------------------------------------------------------


def test_literal_text_has_no_references():
    assert parse("just some text").is_literal


def test_a_single_reference_is_whole_value():
    template = parse("{ddof}")
    assert template.is_whole_value
    assert template.references[0].namespace is Namespace.VARIABLE


def test_surrounding_text_is_not_whole_value():
    template = parse("{data_root}/processed/{item.stem}")
    assert not template.is_whole_value
    assert len(template.references) == 2


def test_matrix_and_item_references_parse():
    assert parse("{variant.group_cols}").references[0].namespace is Namespace.VARIANT
    assert parse("{item.raw}").references[0].namespace is Namespace.ITEM


def test_doubled_braces_escape_to_literals():
    assert render(parse("{{literal}}"), ctx()) == "{literal}"


def test_whitespace_inside_braces_is_ignored():
    assert parse("{  data_root  }").references[0].dotted == "data_root"


# --- parse rejections -----------------------------------------------------


def test_rejects_an_empty_reference():
    with pytest.raises(ExpressionError, match="Empty reference"):
        parse("{}")


def test_rejects_an_unbalanced_brace():
    """An unmatched brace is a typo, not a literal."""
    with pytest.raises(ExpressionError, match="Unbalanced brace"):
        parse("value: {data_root")


def test_rejects_an_empty_segment():
    with pytest.raises(ExpressionError, match="empty segment"):
        parse("{variant..name}")


@pytest.mark.parametrize(
    "source",
    ["{a b}", "{a()}", "{a + 1}", "{a['x']}", "{a|upper}", "{a-b.c.d.e.f}"],
)
def test_rejects_anything_that_is_not_a_plain_path(source: str):
    """The language has no calls, operators, indexing or filters, by design."""
    with pytest.raises(ExpressionError):
        parse(source)


def test_a_dangerous_looking_name_is_just_an_unknown_variable():
    """There is no evaluation here, so a name that looks like Python is only
    ever a dictionary key lookup that fails."""
    parse("{__import__}")  # parses: it is a syntactically valid name
    with pytest.raises(ExpressionError, match="Unknown variable '__import__'"):
        render("{__import__}", ctx(variables={"safe": 1}))


def test_rejects_a_dotted_path_on_a_plain_variable():
    with pytest.raises(ExpressionError, match="not a valid reference"):
        parse("{some.nested.thing}")


def test_rejects_a_bare_namespace_root():
    with pytest.raises(ExpressionError, match=r"\{variant.<attr>\}"):
        parse("{variant}")


def test_rejects_an_unknown_item_attribute():
    with pytest.raises(ExpressionError, match="Unknown fan-out item attribute"):
        parse("{item.owner}")


def test_rejects_an_overlong_template():
    with pytest.raises(ExpressionError, match="exceeds"):
        parse("x" * 9000)


# --- whole value versus interpolation -------------------------------------


def test_whole_value_substitution_preserves_type():
    """Replaces the unquoted-brace idiom, which relied on a YAML parsing accident."""
    result = render("{ddof}", ctx(variables={"ddof": 0}))
    assert result == 0
    assert isinstance(result, int)


def test_interpolation_produces_a_string():
    context = ctx(variables={"data_root": "/data"}, in_fanout_stage=True, item={"stem": "run1"})
    assert render("{data_root}/processed/{item.stem}", context) == "/data/processed/run1"


def test_booleans_interpolate_lowercase():
    assert render("--save={flag}", ctx(variables={"flag": True})) == "--save=true"


def test_a_non_scalar_cannot_be_interpolated():
    with pytest.raises(ExpressionError, match="cannot be interpolated"):
        render("cols={group_cols}", ctx(variables={"group_cols": ["a", "b"]}))


def test_a_non_scalar_is_fine_as_a_whole_value():
    assert render("{group_cols}", ctx(variables={"group_cols": ["a", "b"]})) == ["a", "b"]


def test_null_cannot_be_interpolated():
    with pytest.raises(ExpressionError, match="cannot be interpolated"):
        render("x={maybe}", ctx(variables={"maybe": None}))


# --- resolution rejections ------------------------------------------------


def test_an_unknown_variable_is_an_error_not_an_empty_string():
    """The rule that stops silent substitution into a path."""
    with pytest.raises(ExpressionError, match="Unknown variable 'custom_rules'"):
        render("{custom_rules}", ctx(variables={"od600_col": "od600"}))


def test_the_error_names_the_known_variables():
    with pytest.raises(ExpressionError, match="Known: a, b"):
        render("{missing}", ctx(variables={"a": 1, "b": 2}))


def test_a_matrix_reference_outside_a_matrix_is_an_error():
    with pytest.raises(ExpressionError, match="declares a 'variables' matrix"):
        render("{variant.name}", ctx())


def test_an_item_reference_outside_a_fanout_stage_is_an_error():
    with pytest.raises(ExpressionError, match="only valid inside a stage"):
        render("{item.raw}", ctx(in_fanout_stage=False))


def test_an_item_reference_at_compile_time_is_deferred_not_empty():
    with pytest.raises(ExpressionError, match="cannot be resolved at compile time"):
        render("{item.raw}", ctx(in_fanout_stage=True, item=None))


def test_an_item_reference_is_marked_deferred():
    assert parse("{item.stem}").has_deferred
    assert not parse("{data_root}").has_deferred


# --- real-world regressions -----------------------------------------------


def test_the_variant_group_cols_2_case_now_fails_at_compile_time():
    """509 of 2,178 real task specifications carried this unresolved.

    The `replicates` matrix row does not define `group_cols_2`; only
    `post_replicates` does. The old renderer passed the reference through as
    `{"variant.group_cols_2": null}` and the run reported success.
    """
    replicates = {"name": "replicates", "group_cols": "group_id"}
    with pytest.raises(ExpressionError, match="no attribute 'group_cols_2'"):
        render("{variant.group_cols_2}", ctx(variant=replicates))


def test_the_error_explains_that_matrix_rows_must_be_uniform():
    post = {"name": "post_replicates", "group_cols": "well", "group_cols_2": "group_id"}
    assert render("{variant.group_cols_2}", ctx(variant=post)) == "group_id"
    with pytest.raises(ExpressionError, match="must define the same attributes"):
        render("{variant.group_cols_2}", ctx(variant={"name": "x"}))


def test_a_real_output_path_renders():
    context = ctx(
        variables={"data_root": "/data"},
        variant={"name": "no_replicates"},
        item={"stem": "260312_EGMB"},
        in_fanout_stage=True,
    )
    rendered = render("{data_root}/processed/{variant.name}/{item.stem}", context)
    assert rendered == "/data/processed/no_replicates/260312_EGMB"


# --- trees ----------------------------------------------------------------


def test_render_tree_preserves_shape_and_types():
    document = {
        "value_column_name": "{od600_col}",
        "ddof": "{ddof}",
        "group_cols": ["{variant.group_cols}"],
        "literal": 4,
    }
    out = render_tree(
        document,
        ctx(variables={"od600_col": "od600", "ddof": 0}, variant={"group_cols": "well"}),
    )
    assert out == {
        "value_column_name": "od600",
        "ddof": 0,
        "group_cols": ["well"],
        "literal": 4,
    }
    assert isinstance(out["ddof"], int)


def test_walk_finds_templates_with_their_paths():
    document = {"stages": [{"parameters": {"input": "{data_root}", "threads": 4}}]}
    [(path, template)] = walk_templates(document)
    assert path == ("stages", 0, "parameters", "input")
    assert template.references[0].dotted == "data_root"


def test_walk_propagates_a_parse_error_from_deep_in_a_document():
    with pytest.raises(ExpressionError):
        walk_templates({"a": {"b": ["{bad reference}"]}})


# --- reserved names -------------------------------------------------------


def test_a_variable_may_not_shadow_a_namespace_root():
    with pytest.raises(ExpressionError, match="reserved namespace roots"):
        check_reserved_names(["data_root", "variant"])


def test_ordinary_variable_names_are_accepted():
    check_reserved_names(["data_root", "od600_col", "strain_pattern"])
