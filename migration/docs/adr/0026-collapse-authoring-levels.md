# ADR 0026: Collapse the two authoring levels into one Pipeline

Date: 2026-09-10
Status: Accepted (amended 2026-09-10)
Decision owner: Roozbeh Pazuki
Decision deadline: Before Phase 1 closes
Related gaps: G-new

## Context

The current system has two authoring levels: a pipeline YAML (a graph of Python
function calls) and a job definition (stages, dependencies, a `variables` matrix,
fan-out, and `process_arg_mapping` overrides that reach into a pipeline's
processes). Document 03 proposed carrying both forward as PipelineRevision and
WorkflowRevision, adding a third revision layer for publications.

Three revision layers is a lot of concept for a lab of 5-20 people, and the two
authoring levels are not independently useful in practice: every job definition
in the sample references pipelines that exist only to serve it.

## Options

- Option A: Keep both levels as separately versioned runtime objects.
- Option B: Collapse into one authoring artifact with stages, dependencies and fan-out directly.
- Option C: Keep pipelines as reusable text fragments composed at compile time, not as runtime objects.

## Decision

**Amended to Option C** after a second review checked the reuse claim against
the full sample. The original decision, and the rationale below that said
"every job definition references pipelines created only for that job", were
**factually wrong**. That claim was made from three job definitions; twelve
were supplied later and it was never rechecked.

Reuse is pervasive:

| Graph | Referencing job definitions |
| --- | --- |
| `downlaod_organism_GEM_pipeline` | 3 |
| `collate_per_strain_pipeline` | 3 |
| `growth_rate_fit_pipeline` and its two variants | 3 each |
| `FBA_build_dataset_pipeline` | 2 |
| `synthetic_fba_dataset_generation_pipeline` | 2 |

`growth_rates_pipeline.yaml` alone is 401 lines and is referenced by four job
definitions. Full collapse means quadruplicating it.

**Option C.** One *runtime* concept, `Pipeline`, plus compile-time components:

- A component is a reusable named graph of steps, living in a component
  library file. It maps directly onto today's `(pipeline_yaml, pipeline)` pair.
- A component has **no** publication, schedule, run, or independent runtime
  lifecycle. It is not a versioned runtime object.
- The compiler resolves every component, pins it by content digest, and
  **expands it completely into the IR**. A run points only at
  `PipelineRevision`, which stays self-contained and immutable.

### The constraint that makes this non-trivial

In four job definitions the graph is chosen by a **matrix variable**:

```yaml
pipeline_yaml: growth_rates_pipeline.yaml
pipeline: "{variant.pipeline}"     # one of three graphs, per matrix row
```

So components cannot be resolved by a static import pass. The compiler must:

1. resolve components **after** matrix expansion;
2. **enumerate and pin every component the matrix can select** — all three
   growth-rate graphs, not just the one a given row picks;
3. **reject** any selection it cannot enumerate at compile time, such as a
   component name derived from a researcher-supplied field, because that would
   make the IR non-self-contained.

`pipelines` and `pipeline_revisions` replace the pipeline/workflow split.
`Publication` and `PublicationRevision` remain, because the researcher-facing
contract genuinely is a separate thing with its own lifecycle.

"Pipeline" rather than "Workflow": with one level there is no ambiguity left to
escape, and it is the word the lab already uses. Document 01's objection was to
"job" meaning six different things, and collapsing the model removes most of that
overloading on its own.

## Consequences

- Two tables and a revision layer removed; the runtime model stays single-level.
- **This partially walks back "collapse into one."** There is one runtime
  concept but two authoring artifacts: pipelines and component libraries. That
  is a deliberate trade against quadruplicating a 401-line graph, and it should
  be taken knowingly rather than reintroduced quietly.
- A component changing later cannot alter an existing revision, because the IR
  is fully expanded and the component is digest-pinned.
- New failure modes the compiler must report: unresolvable component, ambiguous
  component name, and a component selection that cannot be enumerated.
- The compiled IR must now express what the job-definition layer expressed: a `variables` matrix, per-stage fan-out, dependencies, and process-argument overrides.

## Follow-up updates required

- Update `../../gaps.md` if this closes or supersedes a row.
- Update `../../14-gap-closure-ledger.md`.
- Update the affected design document.
