# ADR 0034: Where a type is declared

Date: 2026-09-19
Status: Accepted
Decision owner: Roozbeh Pazuki
Related gaps: G33, G93

## Context

The plan gave the type library a registry of its own: a `type_definitions`
table, and `GET/POST /api/v1/types` with `POST /types/import/python` beside it
(document 05). The schema has carried that table since the base migration with
nothing writing to it.

The real deployment does not work that way. In
`job_defs/OD600_growth_rates_ingestion.yaml` the type is declared **inside the
job definition**:

```yaml
definitions:
  CustomReplicateRule:
    description: Rule definition for custom replicate statistics aggregation.
    fields:
      direction: {type: enum, required: true, options: [alphabetical, numerical]}
      pattern: {type: string, required: false}
      sample_size: {type: integer, required: true}
defaults:
  custom_rules: CustomReplicateRule
```

There is no registry, no versioning, and no cross-document reuse. G33 already
recorded that the version scheme documents 03 and 04 proposed had no defined
resolution rule, and it was superseded by snapshotting rather than repaired.

G93 is the reason this matters now: values are submitted as strings —
`{"n_samples": "200"}` against a type declaring integer — and nothing coerced
them. Coercion needs the type to be reachable at submit time, and *which* type
is reachable depends entirely on where types live.

## Options

- Option A: The registry the plan specified. `type_definitions` + `/types` CRUD + a screen an admin curates types in. Cross-document reuse; a second place a type can live; a resolution rule between the two.
- Option B: Declared in the document, resolved at compile, frozen at publish. Matches the real system exactly; no reuse across documents.
- Option C: Both, with a precedence rule.

## Decision

**Option B.**

A type is declared in the document that uses it, parsed by
`app/domain/types.py`, resolved at compile time into a self-contained schema,
and **frozen** — copied onto the publication field when the entry is published,
and onto each saved value when it is saved.

`type_definitions` **stays unwritten**, and this ADR is what says so rather
than leaving another table nobody can explain. It is not dropped: a curated
registry is a plausible thing to want, and the column set is right for it. What
would be wrong is a CRUD screen for a registry no pipeline can currently
reference.

`POST /types/import/python` is **deferred to Phase 6**, not refused. Importing a
type from `labUtils.media_bot.CustomReplicateRule` means importing that module,
which means introspecting an installed environment — exactly what Phase 6
builds, and not something to half-do first.

### What freezing means

Three moments, and they can legitimately disagree:

| Moment | What is frozen | Why |
| --- | --- | --- |
| compile | the resolved schema, into the immutable revision | a revision cannot drift from the document that produced it |
| publish | the schema, onto the publication field | an entry published in March goes on asking for what it asked for in March |
| save | the schema, beside the value | a saved value keeps its meaning when the definition moves |

A saved value offered on a field is therefore checked against **that field's**
schema, not its own, and one that no longer fits is shown disabled with the
reason. Hiding it would leave a researcher wondering where their rule went.

### Coercion (G93)

Submitted values are coerced against the frozen schema, in the application
layer, before materialisation — so `"200"` is an `int` in the stored task spec
and a science function never receives the string. Failures are reported per
path (`values.rules.sample_size`), all of them at once, because a form that
reports one error per submission is a form somebody fills in six times.

`materialise.coerce_value` was written for this and never called, because
nothing could supply its `target`. A frozen schema is that `target`.

## Consequences

- G93 closes, and G33 closes as superseded: there is nothing to version.
- An input naming a type nobody defined fails the **compile**, the same rule bindings follow.
- A type cannot be shared between two pipelines without being written twice. That is what the real system does today, and the cost is visible in a way a registry's staleness would not be.
- `publication_fields.type_schema` is new; `saved_values.type_schema` finally has a writer, as does the whole `saved_values` table.
- The type library screen document 07 lists is not built. It would be a screen over a registry nothing reads.
- Nested structs, lists and maps are supported by the schema and coercer, but the form renders them as JSON: none of the real definitions use them, and a half-built repeater is worse than a box that says what it wants.

## Follow-up updates required

- `gaps.md`: G93 and G33 close.
- `14-gap-closure-ledger.md` records what the work opened.
- `03-domain-model.md` and `05-api-and-contracts.md` carry the decision rather than the registry.
