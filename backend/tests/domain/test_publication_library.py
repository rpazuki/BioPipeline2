"""Check publication library references and typed administrator presets."""

import pytest

from app.domain.errors import ValidationFailed
from app.domain.publication_library import parse_library


def test_structured_presets_are_coerced_and_resolved():
    library = parse_library("""
definitions:
  Options:
    fields:
      window: {type: integer, required: true}
      enabled: {type: boolean, default: false}
presets:
  standard:
    type_ref: Options
    value: {window: "5"}
""")
    assert library.presets["standard"]["value"] == {"window": 5, "enabled": False}
    assert library.schemas["Options"]["fields"][0]["type"] == "integer"


@pytest.mark.parametrize(
    "source",
    [
        "definitions: []",
        "definitions: {Missing: {type: unknown}}",
        "definitions: {Cycle: {fields: {self: {type: Cycle}}}}",
        "presets: {x: {type_ref: Missing, value: 5}}",
        "presets: {x: {type_ref: [], value: 5}}",
        "definitions: {N: {type: integer}}\npresets: {x: {type_ref: N, value: bad}}",
        "definitions: {N: {type: number}}\npresets: {x: {type_ref: N, value: .nan}}",
        "definitions: {N: {type: string}}\npresets: {x: {type_ref: N, value: null}}",
        "unexpected: {}",
        "[broken",
        "definitions: {Choice: {type: enum}}",
        "definitions: {N: {fields: {n: {type: integer, default: bad}}}}",
        "definitions: {N: {type: number}}\npresets: {x: {type_ref: N, value: 'nan'}}",
        "definitions: {}\ndefinitions: {}",
        "definitions: {N: {fields: {1: {type: integer}}}}",
        "definitions: {N: {type: integer, description: {unexpected: value}}}",
    ],
)
def test_invalid_libraries_are_rejected(source):
    with pytest.raises(ValidationFailed):
        parse_library(source)


def test_an_enumeration_can_return_an_object():
    library = parse_library("""
definitions:
  Choice:
    type: enum
    options:
      - {label: Standard, value: {window: 5, enabled: true}}
presets:
  standard:
    type_ref: Choice
    value: {window: 5, enabled: true}
""")
    assert library.presets["standard"]["value"] == {"window": 5, "enabled": True}
