# Task Entry-Point Contract

Version: 2.0
Last reviewed: 2026-09-10
Applies to: BioPipeline2 0.1.0
Owner: TBD
Status: Implemented. ADR 0005 accepted; amended to 2.0 by ADR 0032.

This is the boundary between the platform and scientific code. It is a
versioned contract, not an implementation detail: task images depend on it, so
it cannot change silently.

Machine-readable definition: [`backend/app/domain/task_contract.py`](../../backend/app/domain/task_contract.py).

## Why this document exists

The migration plan committed to two things at once:

1. Scientific code stays **external** to the platform. Today a pipeline YAML
   names a callable such as `labUtils.qc.run` and the engine imports it.
2. Tasks run in **isolated containers**.

Nothing in documents 01-09 said how a workflow names a callable across that
gap. That gap (gap `G20`) blocked both the compiler and the execution adapter,
because neither can be built without knowing what a task *is*.

## Protocol

```
worker                                   task container
  |                                            |
  |-- write /work/.bp/task.json -------------->|
  |-- start container ------------------------>|
  |                                    read task.json
  |                                    do the work
  |                                    write outputs under /work/outputs
  |<-- write /work/.bp/result.json ------------|
  |<-- exit ------------------------------------|
  |                                            |
  |-- stat every declared output               |
  |-- promote outputs to artifacts             |
```

1. The worker writes a `TaskSpec` to `/work/.bp/task.json`.
2. The worker starts the container.
3. The image's entry point reads the spec, runs **every step of the stage in
   order, sharing one payload**, and writes a `TaskResult` to
   `/work/.bp/result.json`.
4. Exit code `0` **and** a valid result means success. Anything else fails.
5. The worker independently verifies every declared output before promoting
   anything to an artifact. **The task's own report is never trusted for
   this** — the worker stats the workspace itself.

## Filesystem layout

| Path | Owner | Purpose |
| --- | --- | --- |
| `/work` | platform | Workspace root, mounted read-write |
| `/work/inputs` | platform | Materialised inputs |
| `/work/<declared path>` | task | Declared outputs are written here |
| `/work/.bp` | platform | `task.json`, `result.json`. Do not write elsewhere in it |
| shared roots | platform | Attested storage roots, mounted **read-only at their own absolute path** |
| library paths | platform | Science libraries, mounted read-only and on `PYTHONPATH` |

**Output** paths are workspace-relative, always. A task writes only where the
platform can verify it and deliver from; shared roots are mounted read-only, so
a task cannot write into institutional storage even by accident, and a run's
results are checked before anything is copied anywhere.

**Input** paths may be workspace-relative *or* absolute, because a shared root
is mounted at its own path. That is deliberate: `sources: [shared]` exists so a
multi-gigabyte dataset is read where it lies rather than copied, and a path an
author wrote about the lab's filesystem has to mean the same thing inside the
container as outside it.

Both are validated in code rather than by a regular expression: `..` segments,
drive letters, backslashes and NUL bytes are rejected either way, and the
worker additionally refuses to launch a task whose absolute input is not inside
a mount the container will actually have. Coercing an absolute path into a
relative one -- which an earlier version did, by stripping the leading slash --
produces a container that reports a missing file at a path nobody wrote.

## What the container may assume

- The workspace is at `/work`, is writable, and is the working directory, so a
  relative path in a parameter means the same thing however the runner started.
- The runner is importable from site-packages, **not** through `PYTHONPATH`: a
  task legitimately sets that variable to reach its science code, and the
  platform's entry point must not break when it does.
- **No outbound network** unless the workflow revision explicitly requested it
  (`limits.network = "egress"`).
- Only the environment variables in `TaskSpec.environment`, plus
  `BP_TASK_SPEC`, `BP_RESULT_PATH`, and `BP_WORKSPACE`. Everything else is
  scrubbed. The spec model itself rejects credential-shaped variable names as
  defence in depth, so a mistake in the worker's allowlist fails a test rather
  than reaching a container.
- The process may run as a non-root user with a read-only root filesystem, so
  do not write outside `/work`.
- Resource limits from `limits` are enforced by the runtime, not advisory.

## One container per stage, not per step

A stage is a graph of calls that pass **live Python objects** to one another: a
parameter naming an earlier step receives that step's return value. The
growth-rate pipelines chain nine DataFrames this way; the FBA pipelines pass a
`cobra.Model`, which has no honest round-trip through a file.

Version 1.0 ran one container per step. That cannot work — a fresh process has
an empty payload, so the next step would receive the string `"df_parsed"`
instead of the DataFrame.

### Passing by path, for data too large to hold

A step may write its result to disk and return the path instead of the object:

```yaml
- spilled:
    package: labUtils.align
    method: write_counts      # returns "outputs/counts.parquet"
- counted:
    package: labUtils.summarise
    method: load_counts
    parameters:
      path: spilled           # receives the path string
```

Nothing special is required: the path is an ordinary payload value. The
platform needs no serialisation format of its own, and the pipeline author
decides where the memory/IO trade-off sits.

### Payload eviction

`StepSpec.retain` lists the payload names still needed after a step returns;
everything else is dropped immediately. The compiler computes it by liveness
analysis over the stage.

Without it a stage holds every intermediate until it finishes, so returning a
path to release a DataFrame would release nothing — the memory saving would be
imaginary.

## Naming the science code

```python
StepSpec(
    name="df_parsed",
    callable_ref=CallableRef(
        kind="python_callable", module="labUtils.media_bot", attribute="parse"
    ),
    parameters={"raw_data": "raw_data"},   # names an input or an earlier step
    retain=["raw_data"],                   # what must survive this step
)
```

`python_callable` is the direct successor to the current system's
import-by-name, so an existing science function is adapted rather than
rewritten. `command` covers tools that are not Python. Relative module names
are rejected.

## Declaring outputs

Outputs are declared up front, which is what makes a run auditable — the
worker knows what to look for, and a task that exits `0` without producing a
required output fails.

```python
OutputDeclaration(key="report", kind="file", path="outputs/qc.html", min_bytes=1024)
```

`verify_outputs()` returns a verdict per declaration: missing-and-required
fails, missing-and-optional passes, and present-but-under-`min_bytes` fails.
`min_bytes` catches the common failure where a tool creates an empty file and
exits successfully.

### `output_dir`

The runner passes `output_dir` to any callable that accepts it, because the
existing engine does and pipelines already rely on it.

It points at the task's **declared output directory** when the task declares
exactly one, and at `outputs/` otherwise. The distinction matters as soon as a
stage fans out: every task of a run shares one workspace, so six tasks writing
plate-reader results into a fixed `outputs/` would overwrite each other and
then fail verification having produced perfectly good files in the wrong place.
The declared path already carries whatever separates a task from its siblings
(`processed/{variant}/{item.stem}`), because that is what it is for.

A task declaring several outputs is given `outputs/` and must write each
declared path itself: there is no single directory that could be meant.

## Reporting failure

```python
TaskError(code="sheet.malformed", message="Column 'Sample_ID' missing", kind="input_invalid")
```

`kind` is what lets the UI tell a researcher *"your sample sheet is
malformed"* instead of *"exit code 1"*:

| kind | Meaning | Retry? |
| --- | --- | --- |
| `input_invalid` | The inputs are wrong. | No — retrying cannot help |
| `science_error` | The computation failed legitimately | No |
| `resource_exhausted` | Out of memory, disk, or time | Maybe, with more resources |
| `internal` | Anything else | Yes |

A `failed` result must carry an error, and a `succeeded` result must not. Both
are enforced by the model.

## Versioning

`contract_version` is checked by both sides, and unknown fields are rejected in
both directions — a field the other side does not know is a version mismatch,
not noise. A task image declares which contract versions it supports in
`runtime_environments.contract_versions`; the worker refuses to launch on a
mismatch rather than producing undefined behaviour.

**Never change the meaning of a field without incrementing the version.**

## Open questions this does not settle

- **ADR 0005** is still `Proposed`. This contract is the recommended option
  implemented in code so the decision is concrete rather than abstract; accept,
  amend, or supersede it.
- **ADR 0023** (task secret model) is open. This contract currently assumes
  tasks need **no** secrets, and actively rejects credential-shaped
  environment variables. If a task must reach an external service, that
  assumption changes and this document changes with it.
- **ADR 0008** decides Docker versus rootless Podman, which affects how the
  limits and mount flags are applied but not the contract shape.
