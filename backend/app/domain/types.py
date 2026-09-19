"""Typed values: what a field means, and what a submitted string has to become.

The gap this closes is G93, and it is worth stating plainly. A submission
arrives from an HTML form, so every value in it is a string:
`{"n_samples": "200", "seed": "42", "max_time": "24.0"}`. The type library says
integer, integer, float. Nothing coerced them, so `"200"` reached a science
function that expected a number, and what happened next depended entirely on
whether that function happened to be tolerant.

Two kinds of type, taken from the real job definitions rather than invented:

    definitions:
      CustomReplicateRule:                # a struct: it has fields
        description: Rule for custom replicate aggregation.
        fields:
          direction: {type: enum, required: true, options: [alphabetical, numerical]}
          sample_size: {type: integer, required: true}
      Strain_Pattern:                     # a scalar alias: a name for a string
        type: string
        default: \\w+

**No versions.** The real library has none, and inventing one would invent a
lifecycle the types do not have. A type is frozen by *snapshot*: `resolve`
produces a self-contained schema with every reference flattened, and that
snapshot is copied onto the publication field at publish and onto each saved
value. A definition that changes afterwards cannot retroactively change what a
published entry asks for, or what a saved value means.

**Coercion fails loudly.** Every problem is reported against its own path —
`custom_rules.sample_size`, not "the form" — because a researcher looking at
twenty fields needs to be told which one, and a message that says only
"invalid" is a message that sends them to an administrator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from app.domain.errors import ValidationFailed

PRIMITIVES = ("string", "integer", "number", "boolean")
CONTAINERS = ("single", "list", "map")

# How deep a struct may nest. Not a stylistic limit: `resolve` flattens
# references, so a type that reaches itself through six others would expand
# for ever, and the depth is what stops it with a message instead of a
# RecursionError.
MAX_DEPTH = 8


class TypeError_(ValidationFailed):
    """A type definition that does not make sense."""

    code = "type.invalid"


class ValueRejected(ValidationFailed):
    """Submitted values that do not satisfy their types."""

    code = "value.invalid"

    def __init__(self, problems: list[dict[str, str]]) -> None:
        super().__init__(
            f"{len(problems)} value(s) do not match what this entry asks for.",
            details={"errors": problems},
        )
        self.problems = problems


@dataclass(frozen=True, slots=True)
class Option:
    """One choice of an enum.

    A value may be a whole object, not only a string: the real variant
    selector returns a five-key mapping, and flattening that to its label
    would lose the four keys nobody sees.
    """

    label: str
    value: Any


def _options(raw: Any, where: str) -> list[Option]:
    """Read either shape the real definitions use.

    `[alphabetical, numerical]` in the job definitions; `[{label, value}]` in
    the documented form. Both mean the same thing, and refusing the shorter
    one would refuse the only one that actually appears in the wild.
    """
    if not isinstance(raw, list) or not raw:
        raise TypeError_(f"{where}: an enum needs a non-empty list of options.")
    options: list[Option] = []
    for entry in raw:
        if isinstance(entry, dict):
            if "value" not in entry:
                raise TypeError_(f"{where}: an option object needs a 'value'.")
            label = str(entry.get("label", entry["value"]))
            options.append(Option(label=label, value=entry["value"]))
        else:
            options.append(Option(label=str(entry), value=entry))
    return options


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """One field of a struct type."""

    name: str
    type: str
    """A primitive, `enum`, or the name of another type."""
    required: bool = False
    default: Any = None
    options: list[Option] = field(default_factory=list)
    container: Literal["single", "list", "map"] = "single"
    description: str | None = None


@dataclass(frozen=True, slots=True)
class TypeSpec:
    """A type as written in a document's `definitions:` block."""

    key: str
    description: str | None = None
    fields: dict[str, FieldSpec] | None = None
    """Present for a struct, absent for a scalar alias."""
    type: str | None = None
    """Present for a scalar alias, absent for a struct."""
    default: Any = None
    options: list[Option] = field(default_factory=list)

    @property
    def is_struct(self) -> bool:
        return self.fields is not None


def parse_definitions(raw: Any) -> dict[str, TypeSpec]:
    """Read a document's `definitions:` block.

    Refuses rather than guesses: a definition that is neither a struct nor a
    scalar alias is a mistake that would otherwise become a field nobody can
    fill in.
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise TypeError_("'definitions' must be a mapping of type name to definition.")

    parsed: dict[str, TypeSpec] = {}
    for key, body in raw.items():
        where = f"definitions.{key}"
        if not isinstance(body, dict):
            raise TypeError_(f"{where}: a type definition must be a mapping.")
        description = body.get("description")
        if "fields" in body:
            fields = body["fields"]
            if not isinstance(fields, dict) or not fields:
                raise TypeError_(f"{where}: 'fields' must be a non-empty mapping.")
            parsed[key] = TypeSpec(
                key=key,
                description=description,
                fields={
                    name: _field(name, spec, f"{where}.fields.{name}")
                    for name, spec in fields.items()
                },
            )
            continue
        declared = body.get("type")
        if not declared:
            raise TypeError_(
                f"{where}: a type needs either 'fields' (a struct) or 'type' (an alias)."
            )
        parsed[key] = TypeSpec(
            key=key,
            description=description,
            type=str(declared),
            default=body.get("default"),
            options=_options(body["options"], where) if declared == "enum" else [],
        )
    return parsed


def _field(name: str, spec: Any, where: str) -> FieldSpec:
    if not isinstance(spec, dict):
        raise TypeError_(f"{where}: a field must be a mapping.")
    declared = spec.get("type")
    if not declared:
        raise TypeError_(f"{where}: a field needs a 'type'.")
    container = spec.get("container", "single")
    if container not in CONTAINERS:
        raise TypeError_(f"{where}: 'container' must be one of {', '.join(CONTAINERS)}.")
    return FieldSpec(
        name=name,
        type=str(declared),
        required=bool(spec.get("required", False)),
        default=spec.get("default"),
        options=_options(spec["options"], where) if declared == "enum" else [],
        container=container,
        description=spec.get("description"),
    )


# --- resolution ------------------------------------------------------------


def resolve(key: str, definitions: dict[str, TypeSpec], _depth: int = 0) -> dict[str, Any]:
    """Flatten a type into a self-contained schema.

    The output is plain JSON, because it is going into a JSONB column and has
    to survive without the code that produced it. Every reference to another
    type is expanded in place, so a stored snapshot needs nothing else to be
    understood — which is the whole of how a type is frozen.
    """
    if _depth > MAX_DEPTH:
        raise TypeError_(
            f"'{key}' nests more than {MAX_DEPTH} types deep, or refers to itself.",
            details={"type": key},
        )
    spec = definitions.get(key)
    if spec is None:
        raise TypeError_(f"No type called '{key}' is defined.", details={"type": key})

    if not spec.is_struct:
        return {
            "kind": "scalar",
            "key": key,
            "type": spec.type,
            "description": spec.description,
            "default": spec.default,
            "options": [{"label": o.label, "value": o.value} for o in spec.options],
        }

    fields: list[dict[str, Any]] = []
    for name, declared in (spec.fields or {}).items():
        entry: dict[str, Any] = {
            "name": name,
            "type": declared.type,
            "required": declared.required,
            "default": declared.default,
            "container": declared.container,
            "description": declared.description,
            "options": [{"label": o.label, "value": o.value} for o in declared.options],
        }
        if declared.type not in PRIMITIVES and declared.type != "enum":
            entry["schema"] = resolve(declared.type, definitions, _depth + 1)
        fields.append(entry)
    return {
        "kind": "struct",
        "key": key,
        "description": spec.description,
        "fields": fields,
    }


# --- coercion --------------------------------------------------------------


def coerce_scalar(value: Any, target: str, path: str) -> Any:
    """Turn one submitted value into what its type says it is.

    The form hands back a string for everything. Refusing to convert is not an
    option — a researcher typing 200 into a field labelled "number of samples"
    has done nothing wrong — and neither is passing it through.
    """
    if target == "string":
        return value if isinstance(value, str) else str(value)
    if target == "boolean":
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in {"true", "1", "yes", "on"}:
            return True
        if text in {"false", "0", "no", "off"}:
            return False
        raise _problem(path, f"'{value}' is not a yes or no.")
    if target == "integer":
        if isinstance(value, bool):
            raise _problem(path, "This must be a whole number, not a yes or no.")
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            raise _problem(path, f"'{value}' is not a whole number.") from None
    if target == "number":
        if isinstance(value, bool):
            raise _problem(path, "This must be a number, not a yes or no.")
        try:
            return float(str(value).strip())
        except (TypeError, ValueError):
            raise _problem(path, f"'{value}' is not a number.") from None
    raise _problem(path, f"'{target}' is not a type this platform knows.")


class _Problem(Exception):
    def __init__(self, path: str, message: str) -> None:
        super().__init__(message)
        self.path = path
        self.message = message


def _problem(path: str, message: str) -> _Problem:
    return _Problem(path, message)


def coerce(value: Any, schema: dict[str, Any], path: str = "") -> Any:
    """Coerce and validate one value against a frozen schema.

    Raises `ValueRejected` carrying every problem found, not just the first:
    a form that reports one error per submission is a form somebody fills in
    six times.
    """
    problems: list[dict[str, str]] = []
    result = _coerce(value, schema, path or schema.get("key", "value"), problems)
    if problems:
        raise ValueRejected(problems)
    return result


def _coerce(value: Any, schema: dict[str, Any], path: str, problems: list[dict[str, str]]) -> Any:
    kind = schema.get("kind")
    if kind == "scalar":
        return _scalar(value, schema, path, problems)
    if kind != "struct":
        problems.append({"path": path, "message": "This field has no usable type."})
        return value
    if not isinstance(value, dict):
        problems.append({"path": path, "message": "This must be a set of named values."})
        return value

    declared = {entry["name"]: entry for entry in schema.get("fields", [])}
    unexpected = sorted(set(value) - set(declared))
    for name in unexpected:
        # A warning would be silently dropping data the researcher typed.
        problems.append({"path": f"{path}.{name}", "message": "This type has no such field."})

    result: dict[str, Any] = {}
    for name, entry in declared.items():
        if name not in value or value[name] in (None, ""):
            if entry.get("default") is not None:
                result[name] = entry["default"]
            elif entry.get("required"):
                problems.append({"path": f"{path}.{name}", "message": "This is required."})
            continue
        result[name] = _container(value[name], entry, f"{path}.{name}", problems)
    return result


def _container(value: Any, entry: dict[str, Any], path: str, problems: list[dict[str, str]]) -> Any:
    container = entry.get("container", "single")
    if container == "single":
        return _member(value, entry, path, problems)
    if container == "list":
        if not isinstance(value, list):
            problems.append({"path": path, "message": "This must be a list."})
            return value
        return [_member(item, entry, f"{path}[{i}]", problems) for i, item in enumerate(value)]
    if not isinstance(value, dict):
        problems.append({"path": path, "message": "This must be a set of named values."})
        return value
    return {key: _member(item, entry, f"{path}.{key}", problems) for key, item in value.items()}


def _member(value: Any, entry: dict[str, Any], path: str, problems: list[dict[str, str]]) -> Any:
    nested = entry.get("schema")
    if nested:
        return _coerce(value, nested, path, problems)
    return _scalar(value, entry, path, problems)


def _scalar(value: Any, entry: dict[str, Any], path: str, problems: list[dict[str, str]]) -> Any:
    target = entry.get("type")
    if target == "enum":
        allowed = [option["value"] for option in entry.get("options", [])]
        # Compared as text, because a form returns "2" for an option whose
        # value is the integer 2, and refusing that would refuse the only
        # thing a select can send.
        for candidate in allowed:
            if value == candidate or str(value) == str(candidate):
                return candidate
        labels = ", ".join(str(option) for option in allowed)
        problems.append({"path": path, "message": f"Choose one of: {labels}."})
        return value
    try:
        return coerce_scalar(value, str(target), path)
    except _Problem as problem:
        problems.append({"path": problem.path, "message": problem.message})
        return value
