"""Import legacy administrator configuration without running its Python references."""

import pytest

from app.domain.errors import ValidationFailed
from app.domain.library_import import import_library
from app.domain.publication_library import EMPTY_SOURCE, parse_library


def test_legacy_types_are_normalized_with_explicit_notes():
    merged, notes = import_library(
        EMPTY_SOURCE,
        """Options:
  source: some.package.Class
  multiple: true
  fields:
    rate: {type: float, required: true}
    location: {type: path}
""",
        "legacy_types",
    )
    schema = parse_library(merged).schemas["Options"]
    assert schema["fields"][0]["type"] == "number"
    assert schema["fields"][1]["type"] == "string"
    assert notes and "source:" not in merged


def test_constants_and_object_variants_become_reusable_values():
    merged, notes = import_library(
        EMPTY_SOURCE,
        """defaults:
  window: 5
  input: $WILL_PROVIDE$
variables:
  options:
    standard: {window: 5, normalize: true}
    wide: {window: 11, normalize: true}
stages: {ignored: ignored}
""",
        "legacy_constants",
    )
    parsed = parse_library(merged)
    assert parsed.presets["window"]["value"] == 5
    assert parsed.presets["options_wide"]["value"] == {"window": 11, "normalize": True}
    assert "input" not in parsed.presets
    assert any("Skipped" in note for note in notes)


def test_import_cannot_silently_overwrite_an_existing_type():
    base = "definitions: {N: {type: integer}}\npresets: {}"
    with pytest.raises(ValidationFailed, match="already exists"):
        import_library(base, "N: {type: string}", "legacy_types")


def test_preset_import_uses_existing_types():
    base = "definitions: {N: {type: integer}}\npresets: {}"
    merged, _ = import_library(base, "standard: {type_ref: N, value: '5'}", "presets")
    assert parse_library(merged).presets["standard"]["value"] == 5
