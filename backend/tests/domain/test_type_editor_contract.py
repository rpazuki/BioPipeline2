"""Presence, nested values, and value shapes used by the visual type editor."""

import pytest

from app.domain.publication_library import parse_library
from app.domain.types import (
    ValueRejected,
    coerce,
    parse_definitions,
    resolve,
    same_contract,
    type_contract,
    with_container,
)


def schema(fields):
    return resolve("Options", parse_definitions({"Options": {"fields": fields}}))


def test_presence_keeps_false_zero_empty_string_and_explicit_null():
    resolved = schema(
        {
            "flag": {"type": "boolean", "required": True, "nullable": False},
            "count": {"type": "integer", "required": True, "nullable": False},
            "label": {"type": "string", "required": True, "nullable": False},
            "optional": {"type": "string", "required": True, "nullable": True},
        }
    )
    value = {"flag": False, "count": 0, "label": "", "optional": None}
    assert coerce(value, resolved) == value
    with pytest.raises(ValueRejected) as rejected:
        coerce({}, resolved)
    assert len(rejected.value.problems) == 4


def test_explicit_null_default_is_different_from_no_default():
    resolved = schema(
        {"name": {"type": "string", "required": True, "nullable": True, "default": None}}
    )
    assert coerce({}, resolved) == {"name": None}
    assert resolved["fields"][0]["has_default"] is True


def test_clearing_an_explicit_field_does_not_reapply_a_default():
    resolved = schema({"name": {"type": "string", "default": "initial", "nullable": False}})
    assert coerce({"name": ""}, resolved) == {"name": ""}
    with pytest.raises(ValueRejected):
        coerce({"name": None}, resolved)


def test_root_list_and_map_coerce_nested_values_and_report_member_paths():
    resolved = schema({"count": {"type": "integer", "required": True, "nullable": False}})
    assert coerce([{"count": "2"}], with_container(resolved, "list")) == [{"count": 2}]
    assert coerce({"first": {"count": "3"}}, with_container(resolved, "map")) == {
        "first": {"count": 3}
    }
    with pytest.raises(ValueRejected) as rejected:
        coerce([{"count": "many"}], with_container(resolved, "list"))
    assert rejected.value.problems[0]["path"] == "Options[0].count"


def test_metadata_and_unknown_default_presence_survive_resolution():
    resolved = schema(
        {
            "name": {
                "type": "string",
                "label": "Display name",
                "help": "Enter a name",
                "example": "first",
                "placeholder": "Name",
                "format": "text",
                "nullable": False,
            }
        }
    )
    member = resolved["fields"][0]
    assert member["label"] == "Display name"
    assert member["help"] == "Enter a name"
    assert member["example"] == "first"
    assert member["has_default"] is False


def test_presets_can_hold_whole_root_collections():
    document = parse_library("""definitions:
  Count: {type: integer}
presets:
  counts: {type_ref: Count, container: list, value: ['2', 3]}
  named: {type_ref: Count, container: map, value: {first: '4'}}
""")
    assert document.presets["counts"]["value"] == [2, 3]
    assert document.presets["named"]["value"] == {"first": 4}


def test_choice_keeps_boolean_and_numeric_values_distinct():
    resolved = {
        "kind": "scalar",
        "type": "enum",
        "options": [{"label": "Zero", "value": 0}, {"label": "False", "value": False}],
    }
    assert coerce(False, resolved) is False
    assert type(coerce(0, resolved)) is int


def test_structured_choices_validate_values_using_their_selected_type():
    resolved = resolve(
        "Choice",
        parse_definitions(
            {
                "Options": {"fields": {"count": {"type": "integer", "required": True}}},
                "Choice": {
                    "type": "enum",
                    "value_type": "Options",
                    "options": [{"label": "Small", "value": {"count": "3"}}],
                },
            }
        ),
    )
    assert resolved["options"][0]["value"] == {"count": 3}
    assert coerce({"count": "3"}, resolved) == {"count": 3}


def test_contract_preserves_legacy_semantics_while_ignoring_new_presentation_metadata():
    old = {
        "kind": "struct",
        "key": "Options",
        "fields": [{"name": "count", "type": "integer", "required": True, "default": None}],
    }
    current = {
        **old,
        "label": "New display name",
        "default": None,
        "has_default": False,
        "fields": [{**old["fields"][0], "has_default": False, "help": "Enter a count"}],
    }
    assert type_contract(old) == type_contract(current)
    assert type_contract({**old, "nullable": True}) != type_contract(old)


def test_type_contract_distinguishes_boolean_and_numeric_choices():
    first = {"kind": "scalar", "type": "enum", "options": [{"label": "Choice", "value": False}]}
    second = {**first, "options": [{"label": "Choice", "value": 0}]}
    assert not same_contract(first, second)
