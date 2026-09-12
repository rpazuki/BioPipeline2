# Task image

Built once and reused. Science libraries are **not** baked in: they come from
the runtime environment's virtualenv, mounted at run time, so installing a
package is an install rather than an image rebuild (ADR 0028).

```bash
docker build -f deploy/images/task/Dockerfile -t biopipeline2/task-base:dev .
```

Build from the repository root — the Dockerfile copies `backend/app/runner`.

The image carries only the runner, which is standard-library only. That is
deliberate: anything it imported would become a dependency of every task
image, and could conflict with the science code it is there to call.
