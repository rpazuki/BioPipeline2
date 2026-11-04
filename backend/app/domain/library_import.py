"""Preview explicit imports of legacy administrator types and publication constants."""

from __future__ import annotations

import re
from typing import Any

import yaml

from app.domain.errors import ValidationFailed
from app.domain.publication_library import _UniqueLoader, parse_library

ALIASES = {
    "float": "number",
    "text": "string",
    "path": "string",
    "file": "string",
    "directory": "string",
    "glob": "string",
    "datetime": "string",
}


def import_library(base_source: str, source: str, format: str) -> tuple[str, list[str]]:
    """Merge supported legacy definitions without overwriting existing names.

    Returns validated YAML and import notes. This function reads configuration
    only; it neither imports Python classes nor runs input or output functions.
    """
    parse_library(base_source)
    try:
        raw = yaml.load(source, Loader=_UniqueLoader)
        base = yaml.load(base_source, Loader=_UniqueLoader)
    except yaml.YAMLError as error:
        raise ValidationFailed("The import is not valid YAML.") from error
    if not isinstance(raw, dict):
        raise ValidationFailed("Import a YAML mapping.")
    base["definitions"] = base.get("definitions") or {}
    base["presets"] = base.get("presets") or {}
    notes = []

    def add(section: str, name: str, value: Any):
        if name in base[section] and base[section][name] != value:
            raise ValidationFailed(f"'{name}' already exists. Rename the imported entry first.")
        base[section][name] = value

    if format == "legacy_types":
        definitions = raw.get("definitions", raw)
        if not isinstance(definitions, dict):
            raise ValidationFailed("The legacy type library must map names to definitions.")
        for name, definition in definitions.items():
            if not isinstance(definition, dict):
                raise ValidationFailed(f"Type '{name}' must be a mapping.")
            converted = {
                key: value
                for key, value in definition.items()
                if key in {"description", "fields", "type", "default", "options"}
            }
            if "type" in converted:
                converted["type"] = _alias(converted["type"])
            if isinstance(converted.get("fields"), dict):
                converted["fields"] = {
                    key: {**body, "type": _alias(body.get("type"))}
                    if isinstance(body, dict)
                    else body
                    for key, body in converted["fields"].items()
                }
            add("definitions", name, converted)
        notes.append(
            "Legacy float types become number; path-like value members become strings. "
            "Configure file transfers in the publication."
        )
        notes.append(
            "Python source references and researcher multiple-instance flags "
            "are not executed or imported."
        )
    elif format == "presets":
        presets = raw.get("presets", raw)
        if not isinstance(presets, dict):
            raise ValidationFailed("Presets must map names to type_ref and value entries.")
        for name, value in presets.items():
            add("presets", name, value)
    elif format == "legacy_constants":
        if set(raw) & {"defaults", "variables"}:
            defaults, variables = raw.get("defaults", {}), raw.get("variables", {})
        else:
            defaults, variables = raw, {}
        if not isinstance(defaults, dict) or not isinstance(variables, dict):
            raise ValidationFailed("Legacy defaults and variables must be mappings.")
        for name, value in defaults.items():
            if value is None or (
                isinstance(value, str)
                and ("$WILL_PROVIDE$" in value or re.search(r"\{[A-Za-z_][A-Za-z0-9_.]*\}", value))
            ):
                notes.append(f"Skipped unresolved input or reference '{name}'.")
                continue
            type_name = _type_name(name)
            primitive = (
                "boolean"
                if isinstance(value, bool)
                else "integer"
                if isinstance(value, int)
                else "number"
                if isinstance(value, float)
                else "string"
                if isinstance(value, str)
                else None
            )
            definition = (
                {"type": primitive}
                if primitive
                else {"type": "enum", "options": [{"label": name, "value": value}]}
            )
            add("definitions", type_name, definition)
            add("presets", name, {"type_ref": type_name, "value": value})
        for name, variants in variables.items():
            if not isinstance(variants, dict) or not variants:
                raise ValidationFailed(f"Variable '{name}' needs named variants.")
            type_name = _type_name(name)
            add(
                "definitions",
                type_name,
                {
                    "type": "enum",
                    "options": [{"label": key, "value": value} for key, value in variants.items()],
                },
            )
            for key, value in variants.items():
                add("presets", f"{name}_{key}", {"type_ref": type_name, "value": value})
        notes.append(
            "Only defaults and named variants were imported. Pipeline steps, input "
            "preprocessing and output serializers were not imported."
        )
    else:
        raise ValidationFailed("Choose a supported library import format.")
    merged = yaml.safe_dump(base, sort_keys=False, allow_unicode=True)
    parse_library(merged)
    return merged, notes


def _type_name(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,110}", name):
        raise ValidationFailed("Imported constant names must be identifiers up to 111 characters.")
    return f"Imported_{name}"


def _alias(value: Any) -> Any:
    return ALIASES.get(value, value) if isinstance(value, str) else value
