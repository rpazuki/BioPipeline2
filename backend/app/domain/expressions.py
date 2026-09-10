"""The workflow expression language (G21).

Document 03's example workflow uses ``${{ inputs.sample_sheet }}`` and friends
without ever defining the language. This module defines it.

Design position: **this is reference-only interpolation, not an expression
evaluator.** There are no function calls, no arithmetic, no comparisons, and no
indirection. A template names a path into a fixed namespace and nothing else.
That is a deliberate restriction: the text is authored by an admin but resolved
against researcher-supplied values, so every feature added here is a feature
available to someone probing for a way out of the sandbox.

Grammar::

    template   := ( literal | escape | expression )*
    escape     := "$${{"                     -> literal "${{"
    expression := "${{" ws path ws "}}"
    path       := segment ( "." segment )*
    segment    := identifier | integer
    identifier := [A-Za-z_][A-Za-z0-9_-]*

Namespaces, and nothing else resolves:

* ``inputs.<key>`` - a workflow input value.
* ``stages.<stage>.outputs.<key>`` - a declared output of an earlier stage.
* ``fanout.item`` and ``fanout.item.{path,name,index}`` - the current fan-out
  item. Legal only inside a fan-out stage, and only resolvable at run
  materialisation, never at compile time.

Substitution rules:

* A template that is *exactly* one expression yields the referenced value with
  its type intact (whole-value substitution). ``${{ inputs.threads }}`` is the
  integer 8, not the string "8".
* A template with surrounding text performs string interpolation, and only
  scalars may be interpolated. Interpolating a directory, list, or object into
  a string is an error rather than a stringified surprise.
* An unresolvable reference is always an error. It never yields an empty
  string: silent empty substitution into a path-shaped parameter is how
  traversal bugs happen.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.domain.errors import ExpressionError

_EXPRESSION_RE = re.compile(r"\$\$\{\{|\$\{\{(?P<body>.*?)\}\}", re.DOTALL)
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
_INTEGER_RE = re.compile(r"^[0-9]+$")

MAX_TEMPLATE_LENGTH = 8192
MAX_PATH_SEGMENTS = 8


class Namespace(StrEnum):
    INPUTS = "inputs"
    STAGES = "stages"
    FANOUT = "fanout"


FANOUT_ITEM_ATTRIBUTES = frozenset({"path", "name", "index", "relpath"})


@dataclass(frozen=True, slots=True)
class Reference:
    """One parsed ``${{ ... }}`` reference."""

    namespace: Namespace
    segments: tuple[str, ...]
    raw: str

    @property
    def is_deferred(self) -> bool:
        """True when the reference can only resolve at run materialisation.

        Fan-out items do not exist until an upstream stage has produced its
        output, so a compiler must accept these while a run-time resolver must
        supply them.
        """
        return self.namespace is Namespace.FANOUT

    @property
    def dotted(self) -> str:
        return ".".join((self.namespace.value, *self.segments))

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
        """True when the template is exactly one reference and nothing else."""
        return len(self.parts) == 1 and isinstance(self.parts[0], Reference)

    @property
    def has_deferred(self) -> bool:
        return any(ref.is_deferred for ref in self.references)


def _fail(message: str, raw: str, **details: Any) -> ExpressionError:
    return ExpressionError(message, details={"expression": raw, **details})


def parse_path(body: str, raw: str) -> Reference:
    """Parse the inside of a ``${{ ... }}`` into a validated reference."""
    text = body.strip()
    if not text:
        raise _fail("Empty expression.", raw)

    segments = text.split(".")
    if len(segments) > MAX_PATH_SEGMENTS:
        raise _fail(
            f"Expression path has {len(segments)} segments; the maximum is {MAX_PATH_SEGMENTS}.",
            raw,
        )
    for segment in segments:
        if not segment:
            raise _fail("Expression path has an empty segment.", raw)
        if not (_IDENTIFIER_RE.match(segment) or _INTEGER_RE.match(segment)):
            raise _fail(f"Invalid path segment '{segment}'.", raw, segment=segment)

    head, *rest = segments
    try:
        namespace = Namespace(head)
    except ValueError:
        allowed = ", ".join(sorted(ns.value for ns in Namespace))
        raise _fail(
            f"Unknown namespace '{head}'. Expressions may only reference: {allowed}.",
            raw,
            namespace=head,
        ) from None

    if namespace is Namespace.INPUTS:
        if len(rest) != 1:
            raise _fail("An inputs reference must be exactly 'inputs.<key>'.", raw)
    elif namespace is Namespace.STAGES:
        # stages.<stage>.outputs.<key>
        if len(rest) != 3 or rest[1] != "outputs":
            raise _fail(
                "A stage reference must be 'stages.<stage>.outputs.<key>'.",
                raw,
            )
    elif namespace is Namespace.FANOUT:
        if not rest or rest[0] != "item":
            raise _fail("A fan-out reference must start with 'fanout.item'.", raw)
        if len(rest) > 2:
            raise _fail("A fan-out reference may not go deeper than 'fanout.item.<attr>'.", raw)
        if len(rest) == 2 and rest[1] not in FANOUT_ITEM_ATTRIBUTES:
            allowed = ", ".join(sorted(FANOUT_ITEM_ATTRIBUTES))
            raise _fail(
                f"Unknown fan-out attribute '{rest[1]}'. Allowed: {allowed}.",
                raw,
                attribute=rest[1],
            )

    return Reference(namespace=namespace, segments=tuple(rest), raw=raw)


def parse(source: str) -> Template:
    """Parse a template string. Raises :class:`ExpressionError` on bad syntax."""
    if len(source) > MAX_TEMPLATE_LENGTH:
        raise ExpressionError(
            f"Template exceeds {MAX_TEMPLATE_LENGTH} characters.",
            details={"length": len(source)},
        )

    parts: list[str | Reference] = []
    cursor = 0
    for match in _EXPRESSION_RE.finditer(source):
        if match.start() > cursor:
            parts.append(source[cursor : match.start()])
        if match.group(0) == "$${{":
            parts.append("${{")
        else:
            raw = match.group(0)
            parts.append(parse_path(match.group("body"), raw))
        cursor = match.end()

    tail = source[cursor:]
    if "${{" in tail:
        raise ExpressionError(
            "Unterminated expression: '${{' without a closing '}}'.",
            details={"expression": tail[tail.index("${{") :][:64]},
        )
    if tail:
        parts.append(tail)

    # Merge adjacent literals so is_whole_value stays meaningful.
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

    ``fanout_item`` is absent at compile time and present at run
    materialisation, which is exactly the compile-time/run-time split that
    :attr:`Reference.is_deferred` describes.
    """

    inputs: Mapping[str, Any] = field(default_factory=dict)
    stage_outputs: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    fanout_item: Mapping[str, Any] | None = None
    in_fanout_stage: bool = False


_SCALAR_TYPES = (str, int, float, bool)


def resolve_reference(reference: Reference, context: ResolutionContext) -> Any:
    """Resolve one reference, or raise. Never returns a default."""
    if reference.namespace is Namespace.INPUTS:
        key = reference.segments[0]
        if key not in context.inputs:
            raise _fail(f"Unknown workflow input '{key}'.", reference.raw, input=key)
        return context.inputs[key]

    if reference.namespace is Namespace.STAGES:
        stage, _outputs, key = reference.segments
        if stage not in context.stage_outputs:
            raise _fail(
                f"Unknown stage '{stage}'. A stage may only reference stages it depends on.",
                reference.raw,
                stage=stage,
            )
        outputs = context.stage_outputs[stage]
        if key not in outputs:
            raise _fail(
                f"Stage '{stage}' declares no output '{key}'.",
                reference.raw,
                stage=stage,
                output=key,
            )
        return outputs[key]

    # fan-out
    if not context.in_fanout_stage:
        raise _fail(
            "'fanout.item' is only valid inside a stage that declares a fanout block.",
            reference.raw,
        )
    if context.fanout_item is None:
        raise _fail(
            "'fanout.item' cannot be resolved at compile time; it is only available "
            "once the upstream output exists.",
            reference.raw,
        )
    if len(reference.segments) == 1:
        return context.fanout_item
    attribute = reference.segments[1]
    if attribute not in context.fanout_item:
        raise _fail(
            f"Fan-out item has no attribute '{attribute}'.",
            reference.raw,
            attribute=attribute,
        )
    return context.fanout_item[attribute]


def render(template: Template | str, context: ResolutionContext) -> Any:
    """Resolve a template against ``context``.

    Returns the referenced value unchanged for a whole-value template, and a
    string for an interpolated one.
    """
    parsed = parse(template) if isinstance(template, str) else template

    if parsed.is_literal:
        return "".join(part for part in parsed.parts if isinstance(part, str))

    if parsed.is_whole_value:
        reference = parsed.parts[0]
        assert isinstance(reference, Reference)
        return resolve_reference(reference, context)

    rendered: list[str] = []
    for part in parsed.parts:
        if isinstance(part, str):
            rendered.append(part)
            continue
        value = resolve_reference(part, context)
        if value is None or not isinstance(value, _SCALAR_TYPES):
            raise _fail(
                f"'{part.dotted}' resolves to {type(value).__name__}, which cannot be "
                "interpolated into a string. Use it as the whole value instead.",
                part.raw,
                resolved_type=type(value).__name__,
            )
        rendered.append("true" if value is True else "false" if value is False else str(value))
    return "".join(rendered)


def walk_templates(value: Any) -> list[tuple[tuple[str | int, ...], Template]]:
    """Find every template in a nested structure, with its path.

    Used by the compiler to validate an entire workflow document in one pass and
    report each diagnostic against a real location.
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
