# Task image

Built once and reused. Science libraries are **not** baked in: they come from
the runtime environment's virtualenv, mounted at run time, so installing a
package is an install rather than an image rebuild (ADR 0028).

```bash
docker build -f deploy/images/task/Dockerfile -t biopipeline2/task-base:dev .
```

Build from the repository root — the Dockerfile copies `backend/app/runner`.

The build normalises the packaged source permissions, then imports the runner as
the image's non-root user and checks that every Python source file is readable
and every package directory is traversable by other task users. A failed check
stops the build, including when the source checkout has private permissions.

Before starting workers on each host, run the import and workspace-write check
in [the deployment instructions](../../../docs/operations/deployment.md#6-the-task-image).
Run it again after replacing the image, moving storage, or changing the worker
account. It checks host mount access, which an image build cannot verify.

The image carries only the runner, which is standard-library only. That is
deliberate: anything it imported would become a dependency of every task
image, and could conflict with the science code it is there to call.
