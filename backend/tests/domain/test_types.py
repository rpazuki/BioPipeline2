"""Typed values, and the string that should have been a number.

G93: real submissions arrive as `{"n_samples": "200", "seed": "42"}` against a
library declaring integer, integer. Nothing coerced them. Everything here is
about that conversion happening, failing loudly when it cannot, and saying
which field.

The definitions used are the real ones, copied from the job definitions in the
deployment rather than invented for the test.
"""

from __future__ import annotations

import pytest

from app.domain.types import (
    TypeError_,
    ValueRejected,
    coerce,
    coerce_scalar,
    parse_definitions,
    resolve,
)

# Exactly as it appears in `OD600_growth_rates_ingestion.yaml`.
REAL = {
    "CustomReplicateRule": {
        "description": "Rule definition for custom replicate statistics aggregation.",
        "fields": {
            "direction": {
                "type": "enum",
                "required": True,
                "options": ["alphabetical", "numerical"],
            },
            "pattern": {"type": "string", "required": False},
            "sample_size": {"type": "integer", "required": True},
        },
    },
    "Strain_Pattern": {
        "type": "string",
        "default": "\\w+",
        "description": "Regex string.",
    },
}


def schema(key: str = "CustomReplicateRule", raw: dict | None = None) -> dict:
    return resolve(key, parse_definitions(raw or REAL))


# --- reading a definition --------------------------------------------------


def test_both_kinds_of_type_are_read():
    definitions = parse_definitions(REAL)
    assert definitions["CustomReplicateRule"].is_struct
    assert not definitions["Strain_Pattern"].is_struct
    assert definitions["Strain_Pattern"].default == "\\w+"


def test_a_bare_list_of_options_is_accepted():
    """The documented shape is label/value pairs; the real files use strings.

    Refusing the short form would refuse the only form that actually appears.
    """
    options = parse_definitions(REAL)["CustomReplicateRule"].fields["direction"].options
    assert [(option.label, option.value) for option in options] == [
        ("alphabetical", "alphabetical"),
        ("numerical", "numerical"),
    ]


def test_an_option_may_be_a_whole_object():
    # The real variant selector returns a five-key mapping, not a string.
    raw = {
        "Variant": {
            "type": "enum",
            "options": [{"label": "No replicates", "value": {"graph": "fit", "group": "well"}}],
        }
    }
    resolved = schema("Variant", raw)
    assert resolved["options"][0]["value"] == {"graph": "fit", "group": "well"}


def test_a_definition_that_is_neither_kind_is_refused():
    with pytest.raises(TypeError_, match="either 'fields'"):
        parse_definitions({"Broken": {"description": "nothing else"}})


def test_a_type_that_refers_to_itself_is_refused_with_a_message():
    """Rather than a RecursionError, which tells an author nothing."""
    raw = {"Loop": {"fields": {"inner": {"type": "Loop"}}}}
    with pytest.raises(TypeError_, match="refers to itself"):
        schema("Loop", raw)


def test_an_unknown_type_is_refused():
    with pytest.raises(TypeError_, match="No type called 'Nope'"):
        schema("Nope")


# --- freezing --------------------------------------------------------------


def test_a_resolved_schema_carries_everything_it_needs():
    """It is going into a JSONB column and has to survive without this code."""
    frozen = schema()
    assert frozen["kind"] == "struct"
    assert [field["name"] for field in frozen["fields"]] == ["direction", "pattern", "sample_size"]
    assert frozen["fields"][0]["options"][0]["value"] == "alphabetical"


def test_a_nested_type_is_flattened_in_place():
    raw = {
        "Inner": {"fields": {"n": {"type": "integer", "required": True}}},
        "Outer": {"fields": {"inner": {"type": "Inner", "required": True}}},
    }
    frozen = schema("Outer", raw)
    assert frozen["fields"][0]["schema"]["fields"][0]["name"] == "n"


# --- coercion --------------------------------------------------------------


def test_the_string_becomes_the_number():
    """G93, in one line."""
    value = coerce({"direction": "numerical", "sample_size": "200"}, schema())
    assert value["sample_size"] == 200
    assert isinstance(value["sample_size"], int)


def test_every_problem_is_reported_at_once_and_against_its_own_field():
    with pytest.raises(ValueRejected) as rejected:
        coerce({"direction": "sideways", "sample_size": "many"}, schema())

    problems = {item["path"]: item["message"] for item in rejected.value.problems}
    # Not "the form is invalid": which field, and what it wanted.
    assert "CustomReplicateRule.direction" in problems
    assert "alphabetical" in problems["CustomReplicateRule.direction"]
    assert "not a whole number" in problems["CustomReplicateRule.sample_size"]


def test_a_missing_required_field_is_named():
    with pytest.raises(ValueRejected) as rejected:
        coerce({"sample_size": 3}, schema())
    assert rejected.value.problems[0]["path"] == "CustomReplicateRule.direction"


def test_an_optional_field_left_blank_is_simply_absent():
    value = coerce({"direction": "numerical", "sample_size": 3, "pattern": ""}, schema())
    assert "pattern" not in value


def test_a_field_the_type_does_not_have_is_refused_not_dropped():
    """Silently dropping it would discard something the researcher typed."""
    with pytest.raises(ValueRejected) as rejected:
        coerce({"direction": "numerical", "sample_size": 3, "extra": 1}, schema())
    assert rejected.value.problems[0]["path"] == "CustomReplicateRule.extra"


def test_a_default_fills_in_for_a_blank():
    frozen = {
        "kind": "struct",
        "key": "T",
        "fields": [{"name": "n", "type": "integer", "default": 5, "container": "single"}],
    }
    assert coerce({}, frozen) == {"n": 5}


def test_an_enum_option_chosen_from_a_form_arrives_as_text():
    """A select sends "2" for an option whose value is the integer 2."""
    frozen = {
        "kind": "struct",
        "key": "T",
        "fields": [
            {
                "name": "n",
                "type": "enum",
                "container": "single",
                "options": [{"label": "two", "value": 2}],
            }
        ],
    }
    assert coerce({"n": "2"}, frozen) == {"n": 2}


def test_a_list_container_coerces_each_member():
    frozen = {
        "kind": "struct",
        "key": "T",
        "fields": [{"name": "sizes", "type": "integer", "container": "list"}],
    }
    assert coerce({"sizes": ["1", "2", "3"]}, frozen) == {"sizes": [1, 2, 3]}


def test_a_map_container_coerces_each_entry():
    frozen = {
        "kind": "struct",
        "key": "T",
        "fields": [{"name": "by_plate", "type": "number", "container": "map"}],
    }
    assert coerce({"by_plate": {"A1": "0.42"}}, frozen) == {"by_plate": {"A1": 0.42}}


def test_a_scalar_alias_coerces_on_its_own():
    assert coerce("A1", schema("Strain_Pattern")) == "A1"


@pytest.mark.parametrize(
    ("value", "target", "expected"),
    [
        ("200", "integer", 200),
        (" 24.0 ", "number", 24.0),
        ("yes", "boolean", True),
        ("off", "boolean", False),
        (7, "string", "7"),
    ],
)
def test_the_conversions_a_form_actually_needs(value, target, expected):
    assert coerce_scalar(value, target, "x") == expected


def test_a_boolean_is_not_a_number():
    """`True` is an int in Python, which is how a checkbox becomes a 1."""
    frozen = {
        "kind": "struct",
        "key": "T",
        "fields": [{"name": "n", "type": "integer", "container": "single"}],
    }
    with pytest.raises(ValueRejected):
        coerce({"n": True}, frozen)
