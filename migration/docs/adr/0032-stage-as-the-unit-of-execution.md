# ADR 0032: A stage, not a step, is the unit of container execution

Date: 2026-09-12
Status: Accepted
Decision owner: Roozbeh Pazuki
Supersedes part of: [ADR 0005](./0005-task-entry-point-contract.md)

## Context

Contract 1.0 ran one container per step. Reviewing the existing pipeline engine
showed that cannot work.

A pipeline graph runs in a single Python process, accumulating a payload:

```python
payload_kwargs = Dict(**kwargs)
for process in self.processes:
    payload_kwargs |= process(**payload_kwargs)
```

and resolution substitutes the live object, not a path:

```python
if is_hashable(value) and value in payload:
    return payload[value]
```

So `df: df_parsed` receives the DataFrame itself. A real run's log confirms it:
*"Result payload contains 9 items: raw_data: DataFrame, df_parsed: DataFrame, …"*.
The FBA pipelines go further and pass a `cobra.Model`, an object graph with a
solver attached.

Under one container per step, each step is a fresh process with an empty
payload, so `df` would receive the string `"df_parsed"`.

## Options

- Option A: one container per stage; the runner executes the graph.
- Option B: one container per step, serialising values between them.
- Option C: hybrid, with author-declared split points.

## Decision

**Option A**, with explicit support for passing by path.

The runner executes the whole stage in one process, sharing a payload, matching
the existing engine's semantics including reference resolution into lists and
mappings and `output_dir` injection.

A step may return a path instead of an object, and the next step opens it. That
is how a stage handles data too large to hold in memory. It needs no platform
support: a path is an ordinary payload value.

`StepSpec.retain` carries liveness analysis from the compiler, so a payload
entry is dropped as soon as nothing refers to it.

## Consequences

- `labUtils` is untouched; pipelines port one-to-one.
- **The stage is the retry unit.** A failure at step 7 of 10 reruns all ten.
  Accepted: graphs are 1-10 steps and currently complete in under a minute, and
  a heavy RNA-seq stage will typically be a single step anyway.
- Resource requests are per stage, which is what admission control already
  assumed.
- Without `retain`, passing by path would not actually save memory, because the
  payload would still hold every earlier result.
- Option B would have required rewriting the science library so every function
  takes and returns paths — work on exactly the code the platform is supposed
  to leave alone.

## Follow-up updates required

- `docs/architecture/task-entry-point-contract.md` describes 2.0. Done.
- Task images must be rebuilt: the runner changed shape.
