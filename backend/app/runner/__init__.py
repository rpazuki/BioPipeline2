"""The in-container task runner.

**Standard library only.** This package runs inside every task image, so any
dependency it takes becomes a dependency of every image an admin builds. It
reads the task specification, calls the science code, and writes the result,
using nothing but the standard library.

The shapes it reads and writes are defined by
``app.domain.task_contract``; a shared test asserts the two agree, since the
runner cannot import it.
"""
