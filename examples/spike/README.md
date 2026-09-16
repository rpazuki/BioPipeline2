# The Phase 0b spike

Runs a real-shaped pipeline all the way through the platform: compile,
fan-out, materialise, claim, container, chained steps, declared outputs,
verification, artifacts, deliveries.

```bash
make db-up && make migrate && make task-image
make spike
```

## What is real here, and what is not

**Real:** the pipeline document, the component library, the compiler, the
matrix, the `mapping_file` fan-out, the task contract, the container and its
containment baseline, output verification, artifact promotion with checksums,
and delivery planning. The step-chaining style (`raw_data: raw_data`,
`df: df_parsed`) is copied from the lab's own
`growth_rates_pipeline.yaml`, so the data flow the runner implements is the
data flow the real pipelines already write.

**Not real:** `stand_in/labUtils` is *not* the lab's library. It is a
standard-library stub with the same module paths, the same call names and the
same argument names, and arithmetic simple enough to check by eye. It exists so
the platform path can be exercised without the lab's private package.

So the spike proves the **platform** carries a pipeline of this shape end to
end. It does not prove anything about `labUtils` itself, and it cannot compare
scientific output against the current system — that needs the real library and
a reference run, neither of which is available here.

## Why a stub rather than the real package

Science libraries are mounted at run time rather than baked into the image
(ADR 0028), so `BP_TASK_LIBRARY_PATHS` points at whatever directory holds
them. The spike points it at `stand_in/`. A deployment points it at the real
environment, and nothing else changes.
