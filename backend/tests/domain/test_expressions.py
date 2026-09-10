"""Tests for the workflow expression language (G21).

Every rejection rule in the language has a named test here, because the
compiler's safety rests on this module refusing bad input rather than
silently coercing it.
"""

from __future__ import annotations

import pytest

from app.domain.errors import ExpressionError
from app.domain.expressions import (
    Namespace,
    ResolutionContext,
    parse,
    render,
    walk_templates,
)

# --- parsing --------------------------------------------------------------


def test_literal_text_has_no_references():
    template = parse("just some text")
    assert template.is_literal
    assert template.references == ()


def test_single_reference_is_whole_value():
    template = parse("${{ inputs.threads }}")
    assert template.is_whole_value
    assert template.references[0].namespace is Namespace.INPUTS
    assert template.references[0].segments == ("threads",)


def test_surrounding_text_is_not_whole_value():
    template = parse("prefix-${{ inputs.name }}.txt")
    assert not template.is_whole_value
    assert len(template.references) == 1


def test_stage_output_reference_parses():
    template = parse("${{ stages.demultiplex.outputs.fastq_root }}")
    reference = template.references[0]
    assert reference.namespace is Namespace.STAGES
    assert reference.segments == ("demultiplex", "outputs", "fastq_root")


def test_escape_yields_a_literal_brace_sequence():
    template = parse("$${{ inputs.threads }}")
    assert template.is_literal
    assert render(template, ResolutionContext()) == "${{ inputs.threads }}"


def test_whitespace_inside_the_braces_is_ignored():
    assert parse("${{inputs.a}}").references[0].dotted == "inputs.a"
    assert parse("${{   inputs.a   }}").references[0].dotted == "inputs.a"


# --- parse rejections -----------------------------------------------------


def test_rejects_unknown_namespace():
    with pytest.raises(ExpressionError, match="Unknown namespace"):
        parse("${{ secrets.api_key }}")


def test_rejects_bare_identifier_without_namespace():
    with pytest.raises(ExpressionError, match="Unknown namespace"):
        parse("${{ threads }}")


def test_rejects_empty_expression():
    with pytest.raises(ExpressionError, match="Empty expression"):
        parse("${{ }}")


def test_rejects_unterminated_expression():
    with pytest.raises(ExpressionError, match="Unterminated expression"):
        parse("value: ${{ inputs.a")


def test_rejects_empty_path_segment():
    with pytest.raises(ExpressionError, match="empty segment"):
        parse("${{ inputs..a }}")


@pytest.mark.parametrize(
    "source",
    [
        "${{ inputs.a b }}",
        "${{ inputs.a() }}",
        "${{ inputs.a + 1 }}",
        "${{ inputs['a'] }}",
        "${{ inputs.a|upper }}",
        "${{ __import__ }}",
    ],
)
def test_rejects_anything_that_is_not_a_plain_path(source: str):
    """The language has no calls, operators, indexing, or filters, by design."""
    with pytest.raises(ExpressionError):
        parse(source)


def test_rejects_wrong_shape_for_inputs():
    with pytest.raises(ExpressionError, match=r"exactly 'inputs.<key>'"):
        parse("${{ inputs.a.b }}")


def test_rejects_wrong_shape_for_stage_reference():
    with pytest.raises(ExpressionError, match=r"stages.<stage>.outputs.<key>"):
        parse("${{ stages.demux.fastq }}")


def test_rejects_fanout_reference_that_is_not_an_item():
    with pytest.raises(ExpressionError, match=r"must start with 'fanout.item'"):
        parse("${{ fanout.source }}")


def test_rejects_unknown_fanout_attribute():
    with pytest.raises(ExpressionError, match="Unknown fan-out attribute"):
        parse("${{ fanout.item.owner }}")


def test_rejects_overlong_path():
    with pytest.raises(ExpressionError, match="maximum"):
        parse("${{ " + ".".join(["inputs"] + ["a"] * 12) + " }}")


def test_rejects_overlong_template():
    with pytest.raises(ExpressionError, match="exceeds"):
        parse("x" * 9000)


# --- resolution -----------------------------------------------------------


def test_whole_value_substitution_preserves_type():
    context = ResolutionContext(inputs={"threads": 8})
    result = render("${{ inputs.threads }}", context)
    assert result == 8
    assert isinstance(result, int)


def test_interpolation_produces_a_string():
    context = ResolutionContext(inputs={"name": "sample01"})
    assert render("out/${{ inputs.name }}.html", context) == "out/sample01.html"


def test_booleans_interpolate_lowercase():
    context = ResolutionContext(inputs={"flag": True})
    assert render("--verbose=${{ inputs.flag }}", context) == "--verbose=true"


def test_stage_output_resolves():
    context = ResolutionContext(stage_outputs={"demux": {"fastq_root": "/work/out/fastq"}})
    assert render("${{ stages.demux.outputs.fastq_root }}", context) == "/work/out/fastq"


def test_fanout_item_resolves_inside_a_fanout_stage():
    context = ResolutionContext(
        in_fanout_stage=True,
        fanout_item={"path": "/work/out/fastq/s1", "name": "s1", "index": 0},
    )
    assert render("${{ fanout.item.name }}", context) == "s1"


# --- resolution rejections ------------------------------------------------


def test_unknown_input_is_an_error_not_an_empty_string():
    """The rule that prevents silent empty substitution into a path."""
    with pytest.raises(ExpressionError, match="Unknown workflow input"):
        render("${{ inputs.missing }}", ResolutionContext(inputs={"present": 1}))


def test_unknown_stage_is_an_error():
    with pytest.raises(ExpressionError, match="Unknown stage"):
        render("${{ stages.nope.outputs.x }}", ResolutionContext())


def test_undeclared_stage_output_is_an_error():
    context = ResolutionContext(stage_outputs={"demux": {"fastq_root": "/x"}})
    with pytest.raises(ExpressionError, match="declares no output"):
        render("${{ stages.demux.outputs.other }}", context)


def test_fanout_outside_a_fanout_stage_is_an_error():
    with pytest.raises(ExpressionError, match="only valid inside a stage"):
        render("${{ fanout.item.path }}", ResolutionContext(in_fanout_stage=False))


def test_fanout_at_compile_time_is_deferred_not_empty():
    context = ResolutionContext(in_fanout_stage=True, fanout_item=None)
    with pytest.raises(ExpressionError, match="cannot be resolved at compile time"):
        render("${{ fanout.item.path }}", context)


def test_non_scalar_cannot_be_interpolated_into_a_string():
    context = ResolutionContext(inputs={"files": ["a", "b"]})
    with pytest.raises(ExpressionError, match="cannot be interpolated"):
        render("list=${{ inputs.files }}", context)


def test_non_scalar_is_fine_as_a_whole_value():
    context = ResolutionContext(inputs={"files": ["a", "b"]})
    assert render("${{ inputs.files }}", context) == ["a", "b"]


def test_null_cannot_be_interpolated():
    context = ResolutionContext(inputs={"maybe": None})
    with pytest.raises(ExpressionError, match="cannot be interpolated"):
        render("x=${{ inputs.maybe }}", context)


# --- deferral -------------------------------------------------------------


def test_fanout_reference_is_marked_deferred():
    assert parse("${{ fanout.item.path }}").has_deferred
    assert not parse("${{ inputs.a }}").has_deferred


# --- walking --------------------------------------------------------------


def test_walk_finds_templates_with_their_paths():
    document = {
        "stages": [
            {"name": "qc", "parameters": {"input": "${{ inputs.folder }}", "threads": 4}},
        ],
        "title": "no templates here",
    }
    found = walk_templates(document)
    assert len(found) == 1
    path, template = found[0]
    assert path == ("stages", 0, "parameters", "input")
    assert template.references[0].dotted == "inputs.folder"


def test_walk_propagates_a_parse_error_from_deep_in_a_document():
    with pytest.raises(ExpressionError):
        walk_templates({"a": {"b": ["${{ bogus.ns }}"]}})
