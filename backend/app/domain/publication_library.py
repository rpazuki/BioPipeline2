"""Validate reusable publication types and administrator-defined values."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

import yaml

from app.domain import types
from app.domain.errors import ValidationFailed

EMPTY_SOURCE = "definitions: {}\npresets: {}\n"


class _UniqueLoader(yaml.SafeLoader):
    """Reject duplicate keys rather than silently replacing an earlier value."""

    def construct_mapping(self, node, deep=False):
        self.flatten_mapping(node)
        pairs = self.construct_pairs(node, deep=deep)
        result = {}
        for key, value in pairs:
            if not isinstance(key, str) or key in result:
                raise ValidationFailed("Library mappings need unique string keys.")
            result[key] = value
        return result


@dataclass(frozen=True)
class LibraryDocument:
    """A validated library with resolved types and coerced preset values."""

    source_text: str
    digest: str
    schemas: dict[str, dict[str, Any]]
    presets: dict[str, dict[str, Any]]


def parse_library(source: str) -> LibraryDocument:
    """Resolve all references and validate every preset before saving a library.

    Raises ValidationFailed for malformed YAML, unknown types, recursive types,
    or values that do not satisfy their declared types.
    """
    try:
        raw = yaml.load(source, Loader=_UniqueLoader)
        json.dumps(raw, allow_nan=False)
    except (yaml.YAMLError, ValueError, TypeError, RecursionError) as error:
        raise ValidationFailed(
            "The library must contain finite, JSON-compatible YAML values."
        ) from error
    if not isinstance(raw, dict) or set(raw) - {"definitions", "presets"}:
        raise ValidationFailed("Use a mapping with only 'definitions' and 'presets' sections.")
    definitions = types.parse_definitions(raw.get("definitions"))
    for key, definition in definitions.items():
        _name(key)
        if definition.type and definition.type not in (*types.PRIMITIVES, "enum"):
            raise ValidationFailed(f"Type '{key}': scalar aliases must use a primitive or enum.")
    schemas = {key: types.resolve(key, definitions) for key in definitions}
    for resolved_schema in schemas.values():
        _validate_defaults(resolved_schema)
    presets = raw.get("presets", {})
    if not isinstance(presets, dict):
        raise ValidationFailed("'presets' must be a mapping of names to typed values.")
    resolved = {}
    for key, preset in presets.items():
        _name(key)
        if not isinstance(preset, dict) or set(preset) - {
            "type_ref",
            "value",
            "description",
            "container",
            "label",
        }:
            raise ValidationFailed(
                f"Preset '{key}' needs type_ref, value, and optional description."
            )
        if "value" not in preset:
            raise ValidationFailed(f"Preset '{key}' must supply a value.")
        if preset.get("description") is not None and not isinstance(preset["description"], str):
            raise ValidationFailed(f"Preset '{key}': description must be text.")
        reference = preset.get("type_ref")
        schema = schemas.get(reference) if isinstance(reference, str) else None
        if schema is None:
            raise ValidationFailed(f"Preset '{key}' refers to an unknown type.")
        container = preset.get("container", "single")
        schema = types.with_container(schema, container)
        resolved[key] = {
            "type_ref": preset["type_ref"],
            "description": preset.get("description"),
            "label": preset.get("label", key),
            "container": container,
            "value": types.coerce(preset["value"], schema, path=key),
        }
    return LibraryDocument(source, hashlib.sha256(source.encode()).hexdigest(), schemas, resolved)


def _name(key: Any) -> None:
    if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,127}", key):
        raise ValidationFailed(
            "Type and preset names must be identifiers of at most 128 characters."
        )


def _validate_defaults(schema: dict[str, Any]) -> None:
    if schema.get("description") is not None and not isinstance(schema["description"], str):
        raise ValidationFailed("Type descriptions must be text.")
    if types.has_default(schema):
        types.coerce(schema["default"], schema)
    for entry in schema.get("fields", []):
        if entry.get("description") is not None and not isinstance(entry["description"], str):
            raise ValidationFailed("Field descriptions must be text.")
        if types.has_default(entry):
            types.coerce({entry["name"]: entry["default"]}, {"kind": "struct", "fields": [entry]})
        if entry.get("schema"):
            _validate_defaults(entry["schema"])
