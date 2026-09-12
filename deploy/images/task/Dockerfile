# The task image: a thin runner plus whatever science libraries an admin
# installs into the mounted environment.
#
# Deliberately minimal. The libraries do NOT live here -- they live in the
# runtime environment's virtualenv, which is mounted in at run time (ADR
# 0028), so adding a package is an install rather than an image build.
#
# The runner is standard-library only, so this image never has to carry a
# Pydantic or SQLAlchemy version that could conflict with the science code.
FROM python:3.12-slim

# A non-root user with a fixed uid, matching DockerAdapter.run_as. The
# workspace is bind-mounted from the host, so the uid has to be predictable
# for the container to be able to write to it.
RUN useradd --uid 1000 --create-home --shell /usr/sbin/nologin task

# Only the runner. Copying the whole application would drag its dependencies
# into every task image for no benefit.
COPY --chown=root:root backend/app/runner /opt/biopipeline2/app/runner
RUN touch /opt/biopipeline2/app/__init__.py

ENV PYTHONPATH=/opt/biopipeline2 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER task
WORKDIR /work

# CMD, not ENTRYPOINT: the worker passes the command explicitly, so an
# entrypoint would turn that command into arguments to itself. As a default it
# still makes `docker run <image>` do the obvious thing.
CMD ["python", "-m", "app.runner.main"]
