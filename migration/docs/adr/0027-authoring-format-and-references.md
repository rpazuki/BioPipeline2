# ADR 0027: Authoring format and reference resolution

Date: 2026-09-10
Status: Accepted
Decision owner: Roozbeh Pazuki
Decision deadline: Before Phase 1 closes
Related gaps: G21

## Context

Document 03 invented a `\${{ ... }}` expression language and it was implemented,
with 39 tests. The project already has a reference mechanism, and it is not that.

Real job definitions use single-brace templating over `variables` and `defaults`,
with dotted access (`{data_root}`, `{variant.name}`, `{item.stem}`). Pipelines
wire stage dataflow by bare name (`df: df_parsed`). Whole-value substitution is
expressed by writing an unquoted `{x}`, which YAML parses as `{'x': None}` and
the renderer special-cases back into a typed value.

That last part is a semantic worth keeping — `ddof: 0` must stay an integer —
encoded in a way that is not. It is invisible, undocumented, and a formatter
adding quotes silently changes meaning.

## Options

- Option A: Keep bare-name wiring only.
- Option B: Unify on `{brace}` templating everywhere, including stage outputs.
- Option C: `{brace}` for variables and interpolation, bare names for stage dataflow, with the whole-value rule stated explicitly.

## Decision

**Option C.**

1. A string that is **exactly one reference** substitutes the value with its type
   intact: `"{ddof}"` yields the integer. This replaces the unquoted-brace idiom
   with the same semantic, stated rather than inferred from YAML's parser.
2. A string with **surrounding text** interpolates and accepts scalars only.
   Interpolating a list or mapping is an error, not a stringified surprise.
3. An **unresolvable reference is a compile error.** Never an empty string, never
   a passed-through mapping.
4. Everything is quoted; ordinary YAML.

Namespaces are unchanged from the current system: `{name}` for variables and
defaults, `{variant.x}` for matrix values, `{item.raw|meta|stem}` for fan-out
items. Bare names remain for stage dataflow inside `parameters:`, and the
compiler errors where a bare name is ambiguous rather than guessing.

## Consequences

- The `\${{ }}` syntax is deleted. Its validation machinery — whole-value
  detection, nested-document walking, structured diagnostics — is reused.
- Rule 3 is the one that matters: 509 of 2,178 real task specifications (23%)
  carry an unresolved reference that was passed through as a raw mapping. See
  [15-premise-correction.md](../../15-premise-correction.md).
- The 52 unquoted braces in the existing job definitions must be quoted during
  re-authoring.

## Follow-up updates required

- Update `../../gaps.md` if this closes or supersedes a row.
- Update `../../14-gap-closure-ledger.md`.
- Update the affected design document.
