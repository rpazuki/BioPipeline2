"""The workflow reference language.

Replaces the `${{ ... }}` syntax an earlier draft invented. The project already
had a reference mechanism and this is it: single-brace templating over
variables, defaults and fan-out items, as used by every real job definition.

Design position: **reference-only interpolation, not an expression evaluator.**
No calls, no operators, no indexing, no indirection. A template names a path
into a fixed namespace and nothing else. The text is admin-authored but
resolved against researcher-supplied values, so every feature added here is a
feature available to someone probing the sandbox.

Grammar::

    template  := ( literal | escape | reference )*
    escape    := "{{" -> "{"  |  "}}" -> "}"
    reference := "{" ws path ws "}"
    path      := name ( "." name )*
    name      := [A-Za-z_][A-Za-z0-9_-]*

Namespaces, and nothing else resolves:

* ``{name}`` - a variable or default.
* ``{variant.<attr>}`` - an attribute of the current matrix row.
* ``{item.<attr>}`` - an attribute of the current fan-out item. Legal only
  inside a stage declaring fan-out, and resolvable only at run
  materialisation.

Substitution rules, and the third is the one that matters:

1. A template that is **exactly one reference** yields the referenced value
   with its type intact. ``"{ddof}"`` is the integer ``0``, not ``"0"``. The
   current system gets this by writing an unquoted ``{ddof}``, which YAML
   parses as ``{'ddof': None}`` and the renderer special-cases. Same semantic,
   stated rather than inferred from a parser accident.
2. A template with surrounding text interpolates, and only scalars may be
   interpolated. A list or mapping is an error, not a stringified surprise.
3. An unresolvable reference is **always an error**. Never an empty string,
   never a passed-through mapping.

Rule 3 is not theoretical. Of 2,178 real task specifications, 509 (23%) carry
an unresolved reference that was passed through as a raw mapping::

    "df_combined_fit_2": {"on_cols": [{"variant.group_cols_2": null}]}
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.domain.errors import ExpressionError

# Ordered: the escapes must match before a single brace is considered.
_TOKEN_RE = re.compile(r"\{\{|\}\}|\{(?P<body>[^{}]*)\}")
_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")

MAX_TEMPLATE_LENGTH = 8192
MAX_PATH_SEGMENTS = 4


class Namespace(StrEnum):
    """Where a reference resolves from."""

    VARIABLE = "variable"
    VARIANT = "variant"
    ITEM = "item"


RESERVED_ROOTS = frozenset({"variant", "item"})
"""Names that may not be used for a variable or default, because they are
namespace roots. Shadowing them would make ``{variant}`` ambiguous."""

ITEM_ATTRIBUTES = frozenset({"raw", "meta", "stem", "path", "name", "index"})
"""Attributes a fan-out item exposes. ``raw``, ``meta`` and ``stem`` are what
the real `mapping_file` and `patterns` fan-outs produce."""


@dataclass(frozen=True, slots=True)
class Reference:
    """One parsed ``{...}`` reference."""

    namespace: Namespace
    segments: tuple[str, ...]
    raw: str

    @property
    def is_deferred(self) -> bool:
        """True when this can only resolve at run materialisation.

        Fan-out items do not exist until the fan-out source is enumerated, so a
        compiler must accept these while a run-time resolver must supply them.
        """
        return self.namespace is Namespace.ITEM

    @property
    def dotted(self) -> str:
        return ".".join(self.segments)

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.dotted


@dataclass(frozen=True, slots=True)
class Template:
    """A parsed template: alternating literal text and references."""

    source: str
    parts: tuple[str | Reference, ...]

    @property
    def references(self) -> tuple[Reference, ...]:
        return tuple(part for part in self.parts if isinstance(part, Reference))

    @property
    def is_literal(self) -> bool:
        return not self.references

    @property
    def is_whole_value(self) -> bool:
        """Exactly one reference and nothing else: substitution keeps the type."""
        return len(self.parts) == 1 and isinstance(self.parts[0], Reference)

    @property
    def has_deferred(self) -> bool:
        return any(reference.is_deferred for reference in self.references)


def _fail(message: str, raw: str, **details: Any) -> ExpressionError:
    return ExpressionError(message, details={"expression": raw, **details})


def parse_reference(body: str, raw: str) -> Reference:
    """Parse the inside of a ``{...}`` into a validated reference."""
    text = body.strip()
    if not text:
        raise _fail("Empty reference.", raw)

    segments = text.split(".")
    if len(segments) > MAX_PATH_SEGMENTS:
        raise _fail(
            f"Reference has {len(segments)} segments; the maximum is {MAX_PATH_SEGMENTS}.",
            raw,
        )
    for segment in segments:
        if not segment:
            raise _fail("Reference has an empty segment.", raw)
        if not _NAME_RE.match(segment):
            raise _fail(f"Invalid name '{segment}' in reference.", raw, name=segment)

    head = segments[0]

    if head == "variant":
        if len(segments) != 2:
            raise _fail("A matrix reference must be '{variant.<attr>}'.", raw)
        return Reference(Namespace.VARIANT, (segments[1],), raw)

    if head == "item":
        if len(segments) != 2:
            raise _fail("A fan-out reference must be '{item.<attr>}'.", raw)
        attribute = segments[1]
        if attribute not in ITEM_ATTRIBUTES:
            allowed = ", ".join(sorted(ITEM_ATTRIBUTES))
            raise _fail(
                f"Unknown fan-out item attribute '{attribute}'. Allowed: {allowed}.",
                raw,
                attribute=attribute,
            )
        return Reference(Namespace.ITEM, (attribute,), raw)

    if len(segments) != 1:
        raise _fail(
            f"'{text}' is not a valid reference. Only '{{variant.<attr>}}' and "
            "'{item.<attr>}' take a dotted path; a variable is referenced by name alone.",
            raw,
        )
    return Reference(Namespace.VARIABLE, (head,), raw)


def parse(source: str) -> Template:
    """Parse a template string. Raises :class:`ExpressionError` on bad syntax."""
    if len(source) > MAX_TEMPLATE_LENGTH:
        raise ExpressionError(
            f"Template exceeds {MAX_TEMPLATE_LENGTH} characters.",
            details={"length": len(source)},
        )

    parts: list[str | Reference] = []
    cursor = 0
    for match in _TOKEN_RE.finditer(source):
        if match.start() > cursor:
            parts.append(source[cursor : match.start()])
        token = match.group(0)
        if token == "{{":
            parts.append("{")
        elif token == "}}":
            parts.append("}")
        else:
            parts.append(parse_reference(match.group("body"), token))
        cursor = match.end()

    tail = source[cursor:]
    # An unmatched brace is a typo, not a literal. Saying so at compile time is
    # the whole point of this module.
    if "{" in tail or "}" in tail:
        stray = tail[min(tail.find(c) for c in "{}" if c in tail) :][:64]
        raise ExpressionError(
            "Unbalanced brace. Write '{{' or '}}' for a literal brace.",
            details={"expression": stray},
        )
    if tail:
        parts.append(tail)

    merged: list[str | Reference] = []
    for part in parts:
        if isinstance(part, str) and merged and isinstance(merged[-1], str):
            merged[-1] += part
        else:
            merged.append(part)
    return Template(source=source, parts=tuple(merged))


@dataclass(slots=True)
class ResolutionContext:
    """Values available to a resolver.

    ``item`` is absent at compile time and present at run materialisation,
    which is exactly the split :attr:`Reference.is_deferred` describes.
    """

    variables: Mapping[str, Any] = field(default_factory=dict)
    variant: Mapping[str, Any] | None = None
    item: Mapping[str, Any] | None = None
    in_fanout_stage: bool = False
    # Variable names whose values arrive at run time -- the public inputs a
    # pipeline marks `$WILL_PROVIDE$`. Partial rendering re-emits references to
    # these verbatim, the same way it treats `{item.*}`, so a revision compiled
    # without them stays correct once they are supplied.
    deferred: frozenset[str] = frozenset()


_SCALARS = (str, int, float, bool)


def resolve(reference: Reference, context: ResolutionContext) -> Any:
    """Resolve one reference, or raise. Never returns a default."""
    if reference.namespace is Namespace.VARIABLE:
        name = reference.segments[0]
        if name not in context.variables:
            known = ", ".join(sorted(context.variables)) or "none"
            raise _fail(
                f"Unknown variable '{name}'. Declare it under 'variables' or "
                f"'defaults'. Known: {known}.",
                reference.raw,
                name=name,
            )
        return context.variables[name]

    if reference.namespace is Namespace.VARIANT:
        attribute = reference.segments[0]
        if context.variant is None:
            raise _fail(
                "'{variant.*}' is only valid in a pipeline that declares a 'variables' matrix.",
                reference.raw,
            )
        if attribute not in context.variant:
            known = ", ".join(sorted(context.variant)) or "none"
            raise _fail(
                f"This matrix row has no attribute '{attribute}'. It defines: {known}. "
                "Every row of a matrix must define the same attributes.",
                reference.raw,
                attribute=attribute,
            )
        return context.variant[attribute]

    if not context.in_fanout_stage:
        raise _fail(
            "'{item.*}' is only valid inside a stage that declares a fanout block.",
            reference.raw,
        )
    if context.item is None:
        raise _fail(
            "'{item.*}' cannot be resolved at compile time; the item list does not "
            "exist until the fan-out source is enumerated.",
            reference.raw,
        )
    attribute = reference.segments[0]
    if attribute not in context.item:
        known = ", ".join(sorted(context.item)) or "none"
        raise _fail(
            f"This fan-out item has no attribute '{attribute}'. It provides: {known}.",
            reference.raw,
            attribute=attribute,
        )
    return context.item[attribute]


def render(template: Template | str, context: ResolutionContext) -> Any:
    """Resolve a template. Returns the referenced value for a whole-value
    template, and a string for an interpolated one."""
    parsed = parse(template) if isinstance(template, str) else template

    if parsed.is_literal:
        return "".join(part for part in parsed.parts if isinstance(part, str))

    if parsed.is_whole_value:
        reference = parsed.parts[0]
        assert isinstance(reference, Reference)
        return resolve(reference, context)

    rendered: list[str] = []
    for part in parsed.parts:
        if isinstance(part, str):
            rendered.append(part)
            continue
        value = resolve(part, context)
        if value is None or not isinstance(value, _SCALARS):
            raise _fail(
                f"'{part.dotted}' resolves to {type(value).__name__}, which cannot be "
                "interpolated into a string. Use it as the whole value instead.",
                part.raw,
                resolved_type=type(value).__name__,
            )
        rendered.append("true" if value is True else "false" if value is False else str(value))
    return "".join(rendered)


def _is_deferred(reference: Reference, context: ResolutionContext) -> bool:
    """Deferred by namespace (a fan-out item) or by value (a public input)."""
    if reference.is_deferred:
        return True
    return reference.namespace is Namespace.VARIABLE and reference.segments[0] in context.deferred


def render_partial(template: Template | str, context: ResolutionContext) -> Any:
    """Render everything that can resolve now, leaving deferred parts literal.

    A path such as ``"{data_root}/processed/{variant.name}/{item.stem}"`` mixes
    references that resolve at compile time with one that cannot exist until
    the fan-out is enumerated. Returning the string untouched, as an
    all-or-nothing renderer must, would leave ``{variant.name}`` unsubstituted
    and the matrix row invisible in the output path.

    So deferred references are re-emitted verbatim and everything else is
    resolved. A second pass at run materialisation, with an item in context,
    then sees only ``{item.*}``.
    """
    parsed = parse(template) if isinstance(template, str) else template
    deferred = [ref for ref in parsed.references if _is_deferred(ref, context)]

    if not deferred:
        return render(parsed, context)

    # A lone deferred reference keeps the original text: there is nothing else
    # to substitute, and whole-value semantics apply on the second pass.
    if parsed.is_whole_value:
        return parsed.source

    rendered: list[str] = []
    for part in parsed.parts:
        if isinstance(part, str):
            rendered.append(part)
        elif _is_deferred(part, context):
            rendered.append(part.raw)
        else:
            value = resolve(part, context)
            if value is None or not isinstance(value, _SCALARS):
                raise _fail(
                    f"'{part.dotted}' resolves to {type(value).__name__}, which cannot "
                    "be interpolated into a string.",
                    part.raw,
                    resolved_type=type(value).__name__,
                )
            rendered.append("true" if value is True else "false" if value is False else str(value))
    return "".join(rendered)


def render_tree(value: Any, context: ResolutionContext, *, partial: bool = False) -> Any:
    """Render every template in a nested structure, preserving shape."""
    renderer = render_partial if partial else render
    if isinstance(value, str):
        return renderer(value, context)
    if isinstance(value, Mapping):
        return {key: render_tree(item, context, partial=partial) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return [render_tree(item, context, partial=partial) for item in value]
    return value


def walk_templates(value: Any) -> list[tuple[tuple[str | int, ...], Template]]:
    """Find every template in a nested structure, with its location.

    Used by the compiler to validate a whole document in one pass and report
    each diagnostic against a real path.
    """
    found: list[tuple[tuple[str | int, ...], Template]] = []

    def visit(node: Any, path: tuple[str | int, ...]) -> None:
        if isinstance(node, str):
            template = parse(node)
            if not template.is_literal:
                found.append((path, template))
        elif isinstance(node, Mapping):
            for key, item in node.items():
                visit(item, (*path, str(key)))
        elif isinstance(node, Sequence) and not isinstance(node, str | bytes):
            for index, item in enumerate(node):
                visit(item, (*path, index))

    visit(value, ())
    return found


def check_reserved_names(names: Sequence[str]) -> None:
    """Reject variable names that shadow a namespace root."""
    clashes = sorted(set(names) & RESERVED_ROOTS)
    if clashes:
        raise ExpressionError(
            f"Variable name(s) {', '.join(clashes)} are reserved namespace roots.",
            details={"names": clashes},
        )
