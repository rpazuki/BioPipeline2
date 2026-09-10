# Domain Model

## Naming rules

One authoring level, not two (ADR 0026). "Pipeline" is the runnable thing, and
it is the word the lab already uses; with a single level there is no ambiguity
left to escape.

| Preferred term | Meaning |
| --- | --- |
| Pipeline | A mutable authoring container. Holds revisions. |
| PipelineRevision | An immutable compiled version. This is what a run points at. |
| PipelineInput | A public input a run must supply. The current system marks these `$WILL_PROVIDE$`. |
| PipelineOutput | A declared output, with the destinations it may be delivered to. |
| Stage | One step in a pipeline: a named callable with parameters, dependencies, and optional fan-out. |
| TaskPlan | A materialised task specification produced by compilation or run creation. |
| Publication | A stable catalog entry visible to researchers. |
| PublicationRevision | An immutable version of catalog metadata and field policy for a pipeline revision. |
| FieldSpec | UI and policy metadata for one public input or output, plus how it binds. |
| Run | A single execution of a pipeline revision. |
| Task | One executable unit within a run. |
| TaskAttempt | One attempt to execute a task. Retries create more attempts. |
| Artifact | An uploaded input, generated output, log, manifest, or package. |
| Delivery | One attempt to place an output at a destination. Has its own status and retry. |
| Schedule | A recurrence rule that creates runs. |
| RuntimeEnvironment | A named, mutable Python environment an admin installs into. |
| EnvironmentSnapshot | That environment as it stood when a run was submitted. |

Do not use "job" or "workflow" as internal nouns. If the UI keeps a familiar
label, document that it maps to `Publication` or `Pipeline` internally.

## Versioning model

Definitions are mutable only in draft form. Anything used to run work is
immutable, **enforced by a database trigger** rather than by convention: the
revision tables reject `UPDATE` and `DELETE` outright.

- Pipelines have many revisions.
- Publications have many revisions.
- Runs point at exact pipeline and publication revisions.
- Tasks point at the compiled task plan used at run creation.
- Runs bind to an environment snapshot, so what executed is recorded even
  though the environment itself is mutable (ADR 0028).
- Artifacts record a checksum.

A published catalog entry may change its current revision; prior runs stay
attached to the revision they used.

**Types are not versioned.** The real type library has no version field. Instead
the type schema is *snapshotted* into the publication revision and into each
saved value, which is what freezes it. Snapshot-on-publish replaces the
version-pointer scheme documents 03 and 04 originally proposed.

## Authoring versus runtime

Authoring documents stay YAML because that is readable and reviewable. Runtime
state is not YAML text: compilation produces a normalised intermediate
representation, and runs use the IR rather than re-rendering source.

### The authoring document

Shaped after what the current job definitions already do, with one authoring
level instead of two (ADR 0026):

```yaml
pipeline: od600_growth_rates
description: Parse, fit and plot OD600 values.

# Cross-product expansion. Known at compile time.
variables:
  variant:
    - {name: no_replicates, group_cols: well,     callable_set: basic}
    - {name: replicates,    group_cols: group_id, callable_set: replicates}

# Shared values. $WILL_PROVIDE$ marks a public input a run must supply.
defaults:
  data_root: $WILL_PROVIDE$
  mapping_yaml: $WILL_PROVIDE$
  od600_col: od600
  strain_pattern: "\\w+"

stages:
  - name: fit
    fanout:
      type: mapping_file            # one task per raw/meta pair
      mapping: "{mapping_yaml}"
    inputs:
      raw_data: "{data_root}/{item.raw}"
      meta_data: "{data_root}/{item.meta}"
    steps:
      - name: df_parsed
        package: labUtils.media_bot
        method: parse
        parameters:
          raw_data: raw_data        # bare name: an earlier step or input
          value_column_name: "{od600_col}"
      - name: df_transformed
        package: labUtils.growth_rates
        method: transform_to_log_n_n0
        parameters:
          df: df_parsed             # bare name: this stage's earlier step
          group_cols: ["{variant.group_cols}"]
    outputs:
      results:
        path: "{data_root}/processed/{variant.name}/{item.stem}"
        delivery: [download, shared]
```

### Reference resolution

Two mechanisms, each keeping the job it already does (ADR 0027):

**`{brace}` templating** interpolates variables, defaults and fan-out items into
values. Three rules, and the third is the important one:

1. A string that is **exactly one reference** substitutes the value with its
   type intact. `"{ddof}"` yields the integer `0`, not `"0"`. This replaces the
   current unquoted-`{x}` idiom — which works only because YAML parses it as
   `{'x': None}` and the renderer special-cases it — with the same semantic,
   stated rather than inferred from a parser accident.
2. A string with **surrounding text** interpolates and accepts scalars only.
   Interpolating a list or mapping is an error, not a stringified surprise.
3. An **unresolvable reference is a compile error.** Never an empty string,
   never a passed-through mapping.

Namespaces, unchanged from the current system: `{name}` for variables and
defaults, `{variant.x}` for matrix values, `{item.raw|meta|stem}` for fan-out
items. `{item.*}` is legal only inside a stage that declares fan-out, and
resolves only at run materialisation.

**Bare names** wire dataflow inside a stage: `df: df_parsed` refers to an
earlier step or a declared input. Where a bare name is ambiguous — a literal
that shadows a step name — the compiler errors rather than guessing.

### Why rule 3 exists

Of 2,178 real task specifications, **509 (23%) contain an unresolved reference
passed through as a raw mapping**:

```json
"df_combined_fit_2": {"on_cols": [{"variant.group_cols_2": null}]}
```

Those results were unaffected, but only by luck: the reference appears solely in
pipelines that do not define that step, so the value never reached a function.
Two silent failures cancelled out — an unresolved reference passing through, and
an override naming a nonexistent step being dropped. Either alone turns a typo
into a run that reports success and quietly did not apply a setting.

The compiler must therefore reject both: an unresolvable reference, and a
binding or override naming a step, stage or parameter that does not exist.

### Fan-out

Fan-out is real, not aspirational, and three kinds are in use:

| type | Source | Item attributes | Resolved |
| --- | --- | --- | --- |
| `mapping_file` | A YAML file of `raw.csv: meta.csv` pairs | `raw`, `meta`, `stem` | at run creation |
| `folders` | Folders under a directory | `stem` | at run creation, or deferred if upstream |
| `patterns` | Glob a raw and a meta pattern and pair them | `raw`, `meta`, `stem` | at run creation |
| `none` | — | — | — |

Plus the `variables` cross-product, which is known at compile time. Expansion is
therefore two-level: matrix times fan-out items. Observed maximum width is 58
tasks.

Fan-out over an upstream stage's output is deferred: the item list does not
exist until that stage finishes, so those tasks are materialised during the run.

## Compiled intermediate representation

The compiler produces a JSON-compatible IR containing pipeline metadata, the
public input schema, the resolved stage graph with dependencies and fan-out
rules, task templates, output declarations with delivery policy, and validation
diagnostics.

The IR is immutable and stored with the revision. It carries an `ir_version`,
and a run never recompiles: compatibility is a read-side decision, so a later
release can tell whether it is able to execute a revision an earlier one
compiled.

## Run lifecycle

Recommended run statuses:

- `queued`: run accepted and waiting for task execution.
- `running`: at least one task is running.
- `succeeded`: all required tasks succeeded.
- `failed`: at least one required task failed and no retry remains.
- `cancel_requested`: user requested cancellation; workers should stop active tasks.
- `cancelled`: execution stopped by user or admin.
- `blocked`: dependencies, validation, or external resources prevent progress.

There is deliberately **no `expired` status**: a run whose outputs were later
cleaned still succeeded, so expiry is a fact about artifacts and workspaces
rather than an overwrite of the outcome (ADR 0012).

Task statuses:

- `created`: task row exists but dependencies are not satisfied.
- `queued`: ready to be claimed.
- `claimed`: worker owns it but execution has not started.
- `running`: task container is running.
- `succeeded`: task completed with valid outputs.
- `failed`: task attempt failed and no retry remains.
- `retry_wait`: retry is scheduled.
- `cancelled`: task did not complete because the run was cancelled.
- `skipped`: task was intentionally skipped by workflow logic.

## Publications and fields

A publication is the curated researcher-facing contract for a pipeline
revision, not the pipeline itself.

Publication data: display name, description, pipeline revision reference, field
order and grouping, allowed input source modes, defaults and fixed hidden
values, output visibility, retention and delivery policy, access policy, and
status (draft, published, archived).

### Field bindings

A field says how it reaches into the pipeline. The current system supports two
binding targets, and both are kept:

```json
{"target": "definition_path",   "path": ["defaults", "od600_col"]}
{"target": "stage_process_arg", "stage": "fit",
                                "process": "df_fit_max_growth_rate",
                                "parameter": "moving_window_size"}
```

Document 01 condemned this as "patching arbitrary YAML paths", and that was
wrong. The mechanism lets an admin expose *any* value in a definition as a form
control without the author having to pre-declare it, which is materially more
flexible than declaring every public input at the boundary.

The defensible half of the criticism is **when** a binding is resolved. So:

- Bindings are resolved **at publish time**, into the compiled IR.
- A field references a compiled input slot; the IR records where that slot feeds.
- A binding naming a stage, process or parameter that does not exist **fails at
  publish**, rather than being silently dropped at run time — which is exactly
  the second of the two silent failures described above.

Nothing patches YAML at run time.

### FieldSpec

Grounded in the real field model, which carries roughly 25 attributes:

- Stable field id (`default_od600_col`, `stage_fit_process_df_fit_max_growth_rate_moving_window_size`).
- Binding, as above.
- Label, help text, placeholder, example.
- Type: a primitive, or `typed` with a `schema_ref` into the type library.
- `type_schema`: the resolved type snapshotted at publish time.
- Container: `single`, `list`, or `map`.
- Options for enums, as label/value pairs. **A value may be a whole object** —
  the variant selector returns a five-key mapping, not a string.
- Required, nullable, readonly, saveable.
- `io_role`: `none`, `input`, or `output`.
- For file-like fields: accepted kind, allowed source modes, allowed shared roots.
- For outputs: allowed delivery modes.

## Typed values

The type library is a schema registry. Its real shape:

```yaml
CustomReplicateRule:                                   # a struct type
  description: Rule definition for custom replicate statistics aggregation.
  source: labUtils.media_bot.CustomReplicateRule       # Python origin
  fields:
    direction:
      type: enum
      required: false
      options: [{label: ALPHABETICAL, value: alphabetical}, ...]
    sample_size: {type: integer, required: false}

Strain_Pattern:                                        # a scalar alias
  type: string
  default: \w+
  description: Regex string.
```

Two kinds: **struct** types with `fields`, and **scalar aliases** with a type
and default and no fields. Fields may reference other types by name, with
`container: list` or `map`. Enums are label/value pairs. `source` records the
Python class a type was imported from, which is what makes import from
dataclasses, TypedDict and Pydantic models round-trip.

There is **no versioning**. Types are frozen by snapshot: the resolved schema is
copied into the publication field and into each saved value.

**Coercion is required at submit time.** Real submissions arrive as strings —
`{"n_samples": "200", "seed": "42", "max_time": "24.0"}` — against a library
declaring integer, integer, float. Values must be coerced and validated before
persistence, and failed coercion must fail the request rather than reaching a
science function as a string.

## Artifacts and workspaces

Artifacts should be explicit records:

- Uploaded inputs.
- Shared-storage references approved by policy.
- Generated outputs.
- Logs.
- Manifests.
- Packaged output archives.

A workspace is a temporary execution layout for one run or task. It is not the source of truth. The artifact table and storage backend are the source of truth.

## Compatibility terms

During migration, the UI can display familiar terms such as "Published Jobs" if users already know them. Internally, prefer `Publication`, `Run`, and `Task`. The old term should be treated as a label, not the domain model.


## Review additions

The original review additions for this document are superseded. Their substance
is now in the body above, and the reasoning is recorded in
[15-premise-correction.md](15-premise-correction.md), ADR 0026 (collapse), ADR
0027 (authoring format) and ADR 0012 (delete semantics).

Two of them were wrong and are worth naming:

- The `${{ ... }}` expression language was invented rather than discovered. The
  project already had `{brace}` templating with a whole-value convention.
- Removing published-field bindings was the wrong conclusion. Resolving them at
  publish time is the right one.
