# Task Entry-Point Contract

Version: 1.0
Last reviewed: 2026-09-10
Applies to: BioPipeline2 0.1.0
Owner: TBD
Status: Implemented, pending ADR 0005 acceptance

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
3. The image's entry point reads the spec, runs the work, writes a
   `TaskResult` to `/work/.bp/result.json`.
4. Exit code `0` **and** a valid result means success. Anything else fails.
5. The worker independently verifies every declared output before promoting
   anything to an artifact. **The task's own report is never trusted for
   this** — the worker stats the workspace itself.

## Filesystem layout

| Path | Owner | Purpose |
| --- | --- | --- |
| `/work` | platform | Workspace root, mounted read-write |
| `/work/inputs` | platform | Materialised inputs |
| `/work/outputs` | task | Declared outputs must be written here |
| `/work/.bp` | platform | `task.json`, `result.json`. Do not write elsewhere in it |

Every path in a spec is **workspace-relative**. Absolute paths, `..` segments,
drive letters, backslashes, and NUL bytes are rejected before the container
starts. Containment is validated in code rather than by a regular expression,
because it is the rule that keeps a task inside its workspace.

## What the container may assume

- The workspace is at `/work` and is writable.
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

## Naming the science code

```python
CallableRef(kind="python_callable", module="labUtils.qc", attribute="run")
CallableRef(kind="command", command=["fastqc", "--outdir", "/work/outputs"])
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
