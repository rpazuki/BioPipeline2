# The pipeline document: format and conventions

A pipeline is one YAML file. An administrator writes it, the compiler turns it
into an immutable revision, and a publication later exposes some of its values
as a form. This is the reference for that file.

Two things to know before the syntax.

**One authoring level, not two.** The previous system had pipelines *and*
workflows. This has pipelines, which may import reusable graphs from component
libraries (ADR 0026). What used to be a workflow is a component.

**An unresolvable reference is an error, always.** In the previous system a
`{variant.group_cols_2}` that resolved to nothing was passed through as a raw
mapping, and 23% of real task specifications carried one. Nobody noticed
because nothing failed — the science ran with a parameter that was not what
the author wrote. The compiler refuses the document instead (ADR 0027).

The example referred to throughout is
[`examples/pipelines/od600_growth_rates.yaml`](../../examples/pipelines/od600_growth_rates.yaml),
which exercises every feature at once.

## The whole document

```yaml
pipeline: od600_growth_rates          # required, the only required key besides `stages`
title: OD600 growth rates             # what the catalog shows
description: >
  Parse plate-reader exports, fit growth curves, write per-experiment results.

components:                           # reusable graphs, imported from libraries
  growth:
    library: growth_rates.yaml
    graph: "{variant.graph}"

definitions:                          # types, for fields that are not plain strings
  Strain_Pattern:
    type: string
    default: \w+

variables:                            # the matrix: every row produces its own stages
  variant:
    - name: no_replicates
      graph: growth_rate_fit_pipeline
      group_cols: well
    - name: replicates
      graph: growth_rate_replicates_fit_pipeline
      group_cols: group_id

defaults:                             # values used everywhere, by reference
  data_root: $WILL_PROVIDE$           # ... or declared as a public input
  mapping_yaml: $WILL_PROVIDE$
  strain: $WILL_PROVIDE$
  od600_col: od600
  moving_window_size: 5

inputs:                               # how each $WILL_PROVIDE$ may be supplied
  data_root:
    accept: directory
    sources: [shared, upload]
    help: Folder holding the plate-reader exports.
  mapping_yaml:
    accept: file
    sources: [upload]
  strain:
    accept: value
    type_ref: Strain_Pattern          # a name from `definitions`

stages:                               # required, at least one
  - name: fit
    task_class: standard
    uses: growth
    fanout: {type: mapping_file, mapping: "{mapping_yaml}"}
    inputs:
      raw_data: "{data_root}/{item.raw}"
    step_parameters:
      df_parsed: {value_column_name: "{od600_col}"}
    outputs:
      results:
        path: "processed/{variant.name}/{item.stem}"
        delivery: [download]
```

**Unknown keys are refused.** A misspelled key is the same defect as an
unresolved reference: the author believes they configured something and did
not. `fanot:` fails the compile rather than being ignored.

## The reference language

Single braces over a fixed namespace. No calls, no operators, no arithmetic,
no indexing — the text is admin-authored but resolved against values a
researcher typed, so every feature here would be a feature available to
someone probing the sandbox.

| Reference | Resolves to | Where it is legal |
| --- | --- | --- |
| `{name}` | a `defaults` entry or a variable | anywhere |
| `{variant.attr}` | an attribute of the current matrix row | anywhere, once `variables` defines `variant` |
| `{item.raw}`, `{item.meta}`, `{item.stem}` | the current fan-out item | only inside a stage that declares `fanout` |
| `{{` and `}}` | a literal `{` and `}` | anywhere |

Three substitution rules, and the third is the one that matters:

1. **A template that is exactly one reference keeps the value's type.**
   `moving_window_size: "{moving_window_size}"` passes the integer `5`, not
   the string `"5"`. The old system got this by writing an unquoted `{ddof}`,
   which YAML parses as the mapping `{'ddof': None}` and the renderer
   special-cased. Same meaning, stated rather than inherited from a parser
   accident.
2. **A template with surrounding text interpolates, and only scalars may be
   interpolated.** `"{data_root}/{item.raw}"` is a path. A list or mapping in
   that position is an error, not a stringified surprise.
3. **An unresolvable reference is an error.** Never an empty string, never a
   passed-through mapping.

### Always quote braces

```yaml
step_parameters:
  df_parsed:
    value_column_name: "{od600_col}"     # correct
```

```yaml
    value_column_name: {od600_col}       # WRONG: YAML reads a mapping
```

An unquoted `{x}` is a YAML flow mapping before the compiler ever sees it.
Rule 1 exists so that quoting costs nothing: the quoted form still passes a
number as a number.

## Top-level keys

### `pipeline`

The name. `[A-Za-z_][A-Za-z0-9_-]*`, at most 128 characters. Revisions are
versioned per pipeline name, so changing it starts a new history.

`variant`, `item` and the other namespace roots are reserved; a variable or
default named after one is refused (`name.reserved`).

### `defaults`

Values referenced from anywhere in the document.

```yaml
defaults:
  od600_col: od600                 # string
  moving_window_size: 5            # integer, and it stays an integer
  ddof: 0
  strict: true                     # boolean
  group_cols: [well, strain]       # list: usable as a whole value, not interpolated
  data_root: $WILL_PROVIDE$        # supplied at submission
```

`$WILL_PROVIDE$` marks a **public input**: the value the researcher supplies.
Everything else is substituted at compile time and is gone from the compiled
revision — which is why a publication field cannot bind to it later. (It can
bind to the step parameter where the value actually landed; see
[the publication fields section](#what-a-publication-can-expose).)

### `inputs`

Policy for each `$WILL_PROVIDE$` default. Optional — an input with no policy
accepts an upload — but worth writing, because this is what the submission
form offers.

```yaml
inputs:
  data_root:
    accept: directory              # file | directory | value
    sources: [shared, upload]      # shared | upload | url
    help: Folder holding the plate-reader exports and their metadata.
  sample_sheet:
    accept: file
    sources: [upload]
  replicate_rule:
    accept: value
    type_ref: CustomReplicateRule  # a name from `definitions`
```

`sources` is an allowlist. `shared` means "a path under a registered storage
root"; `upload` means the browser's chunked upload; `url` is carried from the
old system and the fetch is done by a worker, never by the API.

### `variables` — the matrix

Each key maps to a list of rows; the cross product is expanded, and every row
produces its own copy of every stage.

```yaml
variables:
  variant:
    - {name: no_replicates, graph: growth_rate_fit_pipeline, group_cols: well}
    - {name: replicates,   graph: growth_rate_replicates_fit_pipeline, group_cols: group_id}
```

Stage `fit` then compiles into `fit:no_replicates` and `fit:replicates`.

**Every row must define the same attributes.** A row missing `group_cols_2`
that the others have is what produced the 23% finding, so it is refused at
authoring time rather than at substitution. Rows may also be plain scalars
(`[1, 2, 3]`), but a list must not mix mappings with scalars.

The expansion is capped at 512 rows (`matrix.too_large`).

### `components` and component libraries

A component is a named graph of steps, kept in a library file so several
pipelines can use it.

```yaml
components:
  growth:
    library: growth_rates.yaml     # resolved inside the component library root
    graph: "{variant.graph}"       # may be templated: chosen per matrix row
```

`library` is resolved inside `BP_COMPONENT_LIBRARY_ROOT`
(`/var/lib/biopipeline2/components` by default) and may not escape it.
Because `graph` can be chosen by a matrix variable, component resolution
happens *after* matrix expansion, and every graph a document could select must
exist at compile time — each one is pinned by digest into the revision, so a
later edit to the library cannot change a revision that already exists.

A library file uses either shape. The `pipelines:` form is what the existing
libraries already use:

```yaml
pipelines:
  - growth_rate_fit_pipeline:
      Processes:
        - df_parsed:
            package: labUtils.media_bot
            method: parse
            parameters:
              raw_data: raw_data             # names a stage input
              meta_data: meta_data
              value_column_name: od600
        - df_transformed:
            package: labUtils.growth_rates
            method: transform_to_log_n_n0
            parameters:
              df: df_parsed                  # names the previous step's return
```

or the plain form:

```yaml
graphs:
  growth_rate_fit_pipeline:
    - name: df_parsed
      package: labUtils.media_bot
      method: parse
      parameters: {raw_data: raw_data, value_column_name: od600}
```

**Data flow is explicit.** A parameter whose value names a stage input or an
earlier step receives that value: `df: df_parsed` passes the previous step's
return object, in process, in the same container (ADR 0032). Nothing is
chained implicitly.

### `definitions` — types

Types live in the document that uses them. There is no registry and no
versioning: a type is frozen by *snapshot* when a publication is published and
when a value is saved, so changing a definition later cannot retroactively
change what a published entry asks for.

```yaml
definitions:
  Strain_Pattern:                      # a scalar alias: a name for a string
    type: string
    default: \w+

  CustomReplicateRule:                 # a struct: it has fields
    description: Rule for custom replicate aggregation.
    fields:
      direction:
        type: enum
        required: true
        options: [alphabetical, numerical]
      sample_size:
        type: integer
        required: true
        default: 3
      labels:
        type: string
        container: list                # single | list | map
      nested:
        type: Strain_Pattern           # a reference to another definition
```

Field types: `string`, `integer`, `number`, `boolean`, `enum`, or the name of
another definition. Options may be bare values (`[alphabetical, numerical]`)
or `{label, value}` objects when the label and the value differ — a value may
be a whole object, which is how a variant selector returns five keys while
showing one name.

Structs may nest eight deep; deeper is refused rather than recursing.

### `stages`

```yaml
stages:
  - name: fit                    # required
    needs: [prepare]             # other stage names; the graph must be acyclic
    task_class: standard         # small | standard | large | exclusive
    uses: growth                 # EITHER a component...
    steps: [...]                 # ...OR inline steps. Exactly one.
    step_parameters:             # overrides for a component's steps
      df_parsed: {value_column_name: "{od600_col}"}
    fanout: {...}
    inputs: {...}
    outputs: {...}
```

`task_class` is a **request**, not a hint: admission control refuses to start
a task whose request does not fit the remaining host budget, so an `exclusive`
task runs alone and sequential execution of heavy work falls out of the
arithmetic rather than needing a separate queue.

Inline steps, when there is no component worth extracting:

```yaml
    steps:
      - name: parse
        package: labUtils.media_bot      # absolute dotted name, no leading dot
        method: parse
        parameters:
          raw_data: raw_data
          value_column_name: "{od600_col}"
```

#### `fanout` — one stage, many tasks

| `type` | Requires | Produces one task per |
| --- | --- | --- |
| `none` (default) | — | the stage itself |
| `mapping_file` | `mapping` | entry in a YAML of `data.csv: meta.csv` pairs |
| `folders` | `data_dir` | sub-directory of `data_dir` |
| `patterns` | `data_dir`, `raw_pattern` (and optionally `meta_pattern`) | glob match, paired by position |

```yaml
    fanout:
      type: mapping_file
      mapping: "{mapping_yaml}"
```

```yaml
    fanout:
      type: patterns
      data_dir: "{data_root}"
      raw_pattern: "*_raw.csv"
      meta_pattern: "*_meta.csv"
```

Items expose `{item.raw}`, `{item.meta}` and `{item.stem}`. They resolve at
run materialisation, not at compile time — the item list does not exist until
the source is enumerated — and `{item.*}` outside a fanned-out stage is
refused (`reference.item_outside_fanout`).

#### `inputs` — what the stage reads

```yaml
    inputs:
      raw_data: "{data_root}/{item.raw}"
      meta_data: "{data_root}/{item.meta}"
```

A stage input is a path the container will be given. If it is absolute it must
sit under a registered storage root, or the task is refused before it starts
with a message naming the root that is missing rather than a file-not-found
from inside the container.

#### `outputs` — what it produces, and where it goes

```yaml
    outputs:
      results:
        path: "processed/{variant.name}/{item.stem}"   # workspace-relative
        delivery: [download, shared]
        shared_root: lab-share                         # required if `shared`
        retention_days: 90
        optional: false
```

**Paths are workspace-relative.** A shared root is mounted read-only, and an
output is verified where the platform can see it and *then* delivered. A task
writing straight into institutional storage could overwrite somebody else's
results before anything checked it.

`delivery: [shared]` without `shared_root` is refused at authoring time: an
output cannot be delivered somewhere unspecified, and finding that out during
a run is exactly the surprise this format exists to prevent.

`optional: true` means the run still succeeds when the file is absent.
Otherwise the worker verifies every declared output itself and fails the task
when one is missing — a task that reports success without producing what it
declared has failed.

## What a publication can expose

The document defines what *can* be configured; a publication decides what a
researcher actually sees. A field binds to one of four coordinates:

| `target` | Names | Example |
| --- | --- | --- |
| `default_value` | a public input (`$WILL_PROVIDE$` only) | the `data_root` folder |
| `step_parameter` | `stage` + `step` + the parameter | `fit` / `df_fit_max_growth_rate` / `moving_window_size` |
| `stage_input` | `stage` + the input key | `fit` / `raw_data` |
| `stage_output` | `stage` + the output key | `fit` / `results` |

A binding names a **stage**, not a stage key: with a matrix, exposing "the
moving window of the fit stage" means both `fit:no_replicates` and
`fit:replicates`. Binding to one key would leave the other row silently on the
old value.

A binding to a `default_value` that is *not* `$WILL_PROVIDE$` is refused at
publish time, with a message saying where the value actually lives: a plain
default is substituted at compile time, so by the time there is an IR to bind
against, `{od600_col}` is gone and `od600` is in its place.

Writing the fields themselves is in
[first-run.md](../operations/first-run.md#6-publish-it-as-a-catalog-entry).

## What the compiler refuses

Every one of these is a diagnostic with a location, not an exception:

| Code | Meaning |
| --- | --- |
| `reference.unresolved` | `{x}` names nothing. The 23% defect. |
| `reference.item_outside_fanout` | `{item.*}` in a stage with no `fanout` |
| `graph.cycle` | stages depend on each other in a loop |
| `graph.unknown_dependency` | `needs:` names a stage that does not exist |
| `graph.duplicate_stage_key` | two stages compile to the same key |
| `component.unknown` | `uses:` names no entry in `components` |
| `component.graph_unknown` | the library has no such graph |
| `component.library_unreadable` | the file is missing, outside the root, or invalid |
| `component.unresolvable_selection` | a templated `graph` that cannot be enumerated |
| `override.unknown_step` | `step_parameters` names a step the component does not have |
| `input.not_provided` | a `$WILL_PROVIDE$` default with no value at submission |
| `matrix.too_large` | more than 512 rows |
| `name.reserved` | a variable named after a namespace root |
| `type.invalid`, `type.unresolved`, `type.not_a_value` | a definition that does not make sense |
| `type.unused` | a definition nothing references (a warning) |

Preview before committing: **Pipelines → New revision → Compile preview**
shows the diagnostics, the input contract and the stage graph without storing
anything. A stored revision is immutable.

## Conventions

- **Quote every brace.** See above; this is the one that bites.
- **Name stages for what they do** (`fit`, `collate`), not for their order.
  Stage names appear in task keys, publication bindings and the run page.
- **Keep paths workspace-relative in `outputs`**, absolute only in `inputs`,
  and only under a registered root.
- **Put reusable graphs in a component library** rather than repeating steps.
  A component is pinned by digest, so sharing one is safe.
- **Prefer a matrix over copy-pasted stages.** Two stages that differ by one
  parameter are a matrix with two rows; the uniformity rule then protects you.
- **Mark `$WILL_PROVIDE$` for everything a researcher chooses**, and give each
  one an `inputs:` policy with `help`. The help text is what appears under the
  control on the submission form.
- **Write `retention_days` on outputs that matter.** The default retention is
  deployment-wide (`BP_DEFAULT_RETENTION_DAYS`, 90 days); an output somebody
  will come back to in a year should say so.

## Coming from the previous system's job definitions

| Previously | Now |
| --- | --- |
| Pipeline *and* workflow files | One pipeline document; a workflow is a component (ADR 0026) |
| `${{ ... }}` in one draft, `{...}` in the real definitions | `{...}` only |
| Unquoted `{ddof}`, parsed as a mapping and special-cased | Quoted `"{ddof}"`, with rule 1 keeping the type |
| An unresolved reference passed through | A compile error |
| `Processes:` inside a workflow | `Processes:` still loads inside a *component library*; a pipeline's own stages use `steps:` |
| Types in `labUtils` or by convention | `definitions:` in the document, snapshotted at publish |
| Outputs written anywhere the code chose | Declared, workspace-relative, verified, then delivered |

The `Processes:` library shape is accepted unchanged, so existing component
libraries load without rewriting.
