# ADR 0031: Publication binding plan

Date: 2026-09-10
Status: Accepted
Decision owner: Roozbeh Pazuki
Related gaps: G2-02

## Context

Document 03 restored flexible publication-field bindings, but three things
disagreed with each other:

- Document 03 said an admin may expose any internal value, resolved into the
  compiled IR at publish time.
- Document 07 said the publication editor must not patch arbitrary YAML paths.
- The implemented `PublicationField` carried **no** binding at all and could
  only reference a pre-declared `PipelineInput` or `PipelineOutput`.

Document 03 also said the current system has two binding kinds. The real
deployment's 72 publication fields use **three**: 52 `definition_path`, 18
`stage_process_arg`, 2 `stage_input_source`.

There is also a structural problem nobody had addressed: a `PipelineRevision`
is already immutable when a publication is created, so a publication cannot add
a public slot to it.

## Options

- Option A: Pre-declare every public input on the pipeline; publications may only reference those.
- Option B: Patch the pipeline document at run time, as the current system does.
- Option C: An immutable binding plan owned by the publication revision, validated against the IR at publish time and combined with submitted values into a task plan at run creation.

## Decision

**Option C.**

Each publication field carries a binding validated at publish time against the
pipeline revision's compiled IR, and stored as structured columns rather than a
YAML path:

| `binding_target` | Coordinates | Replaces |
| --- | --- | --- |
| `default_value` | `binding_key` | `definition_path` into `defaults`/`variables` |
| `step_parameter` | `binding_stage`, `binding_step`, `binding_key` | `stage_process_arg` |
| `stage_input` | `binding_stage`, `binding_key` | `stage_input_source` |
| `stage_output` | `binding_stage`, `binding_key` | output destination and delivery |

Rules:

1. Bind to **stable semantic identifiers** — stage name, step name, parameter
   name — never to an array position in source YAML.
2. Validate every target and its type against `compiled_spec` when the
   publication revision is created. A binding naming a stage, step, parameter
   or input that does not exist **fails the publish**.
3. Record the expected type in `binding_value_type`, so a later incompatibility
   is detectable rather than silent.
4. At run creation, submitted values plus the binding plan produce a **new
   immutable task plan**. Nothing patches source YAML; nothing mutates the
   pipeline revision, which may be shared with other publications.
5. The original binding is preserved, so an old run stays explainable.

A database check constraint enforces that each target carries its own
coordinates and only those.

## Consequences

- Resolves the three-way contradiction: one binding schema is used by the
  domain document, the database model, and the API.
- The admin experience stays "select a value to expose"; nobody writes paths by
  hand.
- `pipeline_inputs` and `pipeline_outputs` remain, but as the *declared* public
  surface, not as the only bindable targets.
- Rule 2 closes the second of the two silent failures found in the real data:
  an override naming a step absent from the target pipeline was dropped without
  a warning.
- A conversion is needed for the 72 existing bindings if any publication is ever
  recreated from the old system. There is no importer, so this is documentation
  rather than code.

## Follow-up updates required

- Document 03's "two target kinds" is corrected to three-plus-outputs.
- Document 07's "must not patch arbitrary YAML paths" is reworded: the editor
  exposes values, and binding resolution happens at publish time.
