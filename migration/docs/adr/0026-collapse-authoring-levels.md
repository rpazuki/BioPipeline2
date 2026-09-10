# ADR 0026: Collapse the two authoring levels into one Pipeline

Date: 2026-09-10
Status: Accepted
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

**Option B.** One authoring artifact, named `Pipeline`.

`pipelines` and `pipeline_revisions` replace the pipeline/workflow split.
`Publication` and `PublicationRevision` remain, because the researcher-facing
contract genuinely is a separate thing with its own lifecycle.

"Pipeline" rather than "Workflow": with one level there is no ambiguity left to
escape, and it is the word the lab already uses. Document 01's objection was to
"job" meaning six different things, and collapsing the model removes most of that
overloading on its own.

## Consequences

- Two tables and a revision layer removed; 35 tables became 33.
- Reuse of a pipeline across several jobs is lost. Nothing in the sample relied on it.
- Authors learn one concept instead of two.
- The compiled IR must now express what the job-definition layer expressed: a `variables` matrix, per-stage fan-out, dependencies, and process-argument overrides.

## Follow-up updates required

- Update `../../gaps.md` if this closes or supersedes a row.
- Update `../../14-gap-closure-ledger.md`.
- Update the affected design document.
