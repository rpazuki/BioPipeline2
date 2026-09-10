# Domain Model

## Naming rules

BioPipeline2 should use precise names and avoid the overloaded word "job" except where a user-facing legacy term must be preserved temporarily.

| Preferred term | Meaning |
| --- | --- |
| PipelineDefinition | A reusable scientific pipeline document. It defines executable steps and parameters. |
| PipelineRevision | An immutable validated version of a pipeline definition. |
| WorkflowTemplate | An admin-authored orchestration document that references pipeline revisions, inputs, stages, dependencies, and fan-out rules. |
| WorkflowRevision | An immutable compiled version of a workflow template. This is what runs point to. |
| WorkflowInput | A named input required or accepted by a workflow revision. |
| TaskPlan | A normalized task template or materialized task specification produced by compilation or run creation. |
| Publication | A stable catalog entry visible to researchers. |
| PublicationRevision | An immutable version of catalog metadata and field policy for a workflow revision. |
| FieldSpec | UI and policy metadata for one public input or output declaration. |
| Run | A single execution of a workflow revision, requested manually or by a schedule. |
| Task | One executable unit within a run. |
| TaskAttempt | One attempt to execute a task. Retries create more attempts. |
| Artifact | An uploaded input, generated output, log, manifest, or package. |
| Schedule | A recurrence rule that creates runs from a publication revision and saved input set. |

## Versioning model

Definitions are mutable only in draft form. Anything used to run work is immutable.

- Pipeline definitions have many revisions.
- Workflow templates have many revisions.
- Publications have many revisions.
- Runs point to exact workflow and publication revisions.
- Tasks point to the compiled task plan used at run creation time.
- Artifacts are content-addressed or checksum-recorded.

A published catalog entry may change its current revision, but prior runs remain attached to the exact revision they used.

## Authoring versus runtime

Authoring documents may be YAML because that is readable and reviewable. Runtime state should not be YAML text. The compile step should produce a normalized intermediate representation.

### Workflow authoring document

A future workflow YAML should be explicit about public inputs and stage behavior. Example:

```yaml
workflow:
  slug: demultiplex-and-qc
  title: Demultiplex and QC
  inputs:
    sample_sheet:
      type: file
      required: true
      accepted_extensions: [csv, tsv]
    run_folder:
      type: directory
      required: true
      source_modes: [upload, shared]
    threads:
      type: integer
      default: 8
      minimum: 1
      maximum: 64
  stages:
    - name: demultiplex
      pipeline: bcl-convert@3
      parameters:
        sample_sheet: ${{ inputs.sample_sheet }}
        run_folder: ${{ inputs.run_folder }}
        threads: ${{ inputs.threads }}
      outputs:
        fastq_root: output://fastq
    - name: qc
      needs: [demultiplex]
      fanout:
        from: ${{ stages.demultiplex.outputs.fastq_root }}
        mode: folders
      pipeline: fastqc@2
      parameters:
        input_folder: ${{ fanout.item.path }}
      outputs:
        report: output://qc/${{ fanout.item.name }}.html
```

The exact syntax can change, but the principles should not:

- Inputs are declared at the workflow boundary.
- Stage outputs are declared and named.
- Later stages reference prior named outputs, not magic placeholder strings.
- Fan-out sources are explicit.
- Public fields are derived from or mapped to workflow inputs, not arbitrary YAML patches.

## Compiled workflow intermediate representation

The compiler should produce a JSON-compatible IR with:

- Workflow metadata: id, revision id, slug, version, title.
- Input schema: names, types, defaults, constraints, source policies.
- Stage graph: stages, dependencies, fan-out rules.
- Task templates: executable pipeline revision, parameters, expected inputs, declared outputs.
- Output declarations: names, artifact kind, visibility, retention policy.
- Validation diagnostics: warnings, errors, deprecations.

This IR is immutable and stored with the workflow revision. Runs use the IR, not the original YAML text.

## Run lifecycle

Recommended run statuses:

- `draft`: optional state for a saved form before submission.
- `queued`: run accepted and waiting for task execution.
- `running`: at least one task is running.
- `succeeded`: all required tasks succeeded.
- `failed`: at least one required task failed and no retry remains.
- `cancel_requested`: user requested cancellation; workers should stop active tasks.
- `cancelled`: execution stopped by user or admin.
- `blocked`: dependencies, validation, or external resources prevent progress.
- `expired`: run outputs were cleaned according to retention policy.

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

A publication is not the workflow itself. It is the curated researcher-facing contract for a workflow revision.

Publication data:

- Display name.
- Description.
- Workflow revision reference.
- Field order and grouping.
- Allowed input source modes.
- Defaults and fixed hidden values.
- Output visibility and retention policy.
- Access policy.
- Current status: draft, published, archived.

FieldSpec should include:

- Stable field id.
- Workflow input id or output declaration id.
- Label, help text, placeholder.
- Type reference or primitive type.
- Required flag and constraints.
- Source policy for file-like fields.
- Save-value policy.
- Visibility policy.
- UI grouping metadata.

FieldSpec should not contain arbitrary YAML path bindings. Binding belongs in the compiled workflow IR.

## Typed values

The type library should become a first-class schema registry. It should support:

- Primitive field types.
- Structured object types.
- Lists and maps.
- Units and domain-specific constraints where useful.
- Versioned type definitions.
- Saved named values per user and type.
- Import from Python dataclasses, TypedDict, and Pydantic models.

Typed values should be validated at submit time and normalized before persistence. Failed coercion must fail the request.

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

> Findings below are registered with evidence, severity, and status in
> [gaps.md](gaps.md). This section says what to do about them.

### The expression language needs a specification

The example workflow uses `${{ inputs.sample_sheet }}`,
`${{ stages.demultiplex.outputs.fastq_root }}`, and `${{ fanout.item.path }}`.
That is a language, and it is the most security-sensitive part of the compiler:
it evaluates admin-authored text against researcher-supplied values. The plan
never specifies it, and Phase 2's acceptance criteria do not test it.

Specify before Phase 2:

- The full grammar, and the fact that it is **not** a general expression
  evaluator. Reference-only interpolation (paths into a known namespace) is
  strongly preferred over anything with function calls or arithmetic.
- The namespaces available and where each is legal (`inputs`, `stages.*.outputs`,
  `fanout.item`, and nothing else). `fanout.item` must be rejected outside a
  fan-out stage.
- Type rules: what happens when a string template interpolates a directory, a
  list, or null. Whole-value substitution and string interpolation are different
  operations and should look different.
- Escaping, so a literal `${{` is expressible.
- Evaluation timing: which references resolve at compile time and which can only
  resolve at run materialisation. Fan-out references are necessarily the latter.
- Failure mode: an unresolvable reference is a compile error, never an empty
  string. Silent empty substitution into a shell-adjacent parameter is how path
  traversal happens.

### Output delivery belongs in the domain model

`Artifact` and retention are modelled, but the current system also decides *where
an output goes*: download only, or copied into an allowlisted shared root. That
is a first-class concept and it can fail independently of the run.

Add to the vocabulary:

| Term | Meaning |
| --- | --- |
| DeliveryPolicy | The allowed and default destinations for a declared output, set on the workflow output and narrowed by the publication. |
| Delivery | One attempt to place a run's output at a destination. Has its own status and retry. |

A run can succeed while a delivery fails; the run detail UI must be able to show
that. See the `run_deliveries` table added in
[04-data-model-postgres.md](04-data-model-postgres.md).

### Input source modes are incomplete

`source_modes: [upload, shared]` omits `url`, which the current system supports
by fetching a researcher-supplied URL server-side. Either carry it with the
controls specified in [05-api-and-contracts.md](05-api-and-contracts.md) or drop
it explicitly - it is currently a published-field capability, so dropping it is a
user-visible change.

### Run and task lifecycle gaps

The status lists are good. Missing transitions and rules:

- **Who owns each transition.** `queued -> running` is set by a worker;
  `cancel_requested -> cancelled` must be owned by a reaper, because the worker
  that held the task may be gone. Write the owner next to each transition, or the
  code will disagree with itself.
- **A terminal-state rule**: `succeeded`, `failed`, `cancelled`, and `expired`
  are terminal; no process may move a run out of them. Enforce it in the domain
  layer, not just by convention.
- **`retry_wait` and `blocked` need reasons**, not just statuses - a blocked run
  with no explanation is an unactionable support ticket.
- **`expired` interacts with `succeeded`**: a run whose outputs were cleaned still
  succeeded. Consider keeping the run status terminal and expressing expiry as an
  artifact-level or retention-level fact, rather than overwriting the outcome.
- **Partial success**: if a workflow declares an optional stage, is a run with a
  failed optional task `succeeded` or `failed`? Decide, or the first workflow with
  an optional stage will decide for you.
- **`draft` runs** are listed as an optional status, while document 05 has a
  separate `POST /catalog/{slug}/drafts` endpoint. A draft is arguably not a run
  at all. Pick one representation.

### Immutability needs enforcement, not just intent

"Anything used to run work is immutable" is the load-bearing principle of the
whole design. State how it is enforced: no `UPDATE` path in the repository for
revision tables, plus a database-level guard (a trigger or a revoked update
privilege). Convention alone will not survive a deadline.

Related: `publications.current_revision_id` is mutable by design. Say explicitly
that changing it never affects existing runs, and that archiving a publication
does not invalidate the runs that used it.

### Compiled IR needs a version

The IR is stored and read by later code releases. It needs its own
`ir_version`, and a stated policy: can a new release read an old IR, and what
happens to a queued run whose IR predates a breaking IR change? Without this,
the first IR change either breaks in-flight runs or forces a recompile of
immutable revisions - which contradicts immutability.
