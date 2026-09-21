"""Building a generation of a runtime environment, inside the task image.

The mechanism ADR 0028 chose, and the reasons it chose it are load-bearing
enough to restate.

**Built inside the same image tasks run in.** A virtualenv is not portable
across interpreters: a native wheel is compiled against a specific Python,
libc and architecture. Building it anywhere other than the image that will
run it is how an environment works on the machine that made it and fails in
the container.

**Always mounted at the same container path.** A virtualenv embeds absolute
paths in its scripts and its `pyvenv.cfg`, so moving one breaks it. Every
generation lives at a different path on the host and at `/env` inside the
container, which is what makes copying one to make the next one safe.

**Copied, not hardlinked.** pip rewrites and removes files in place while
installing, so a hardlinked copy would corrupt the generation it was cloned
from — the isolation the whole design exists for. The cost is disk per
install, which ADR 0028 accepted and which the janitor reclaims once nothing
references a generation.

**Never mutated after it is built.** An install builds the next generation
out of place and the environment's pointer moves when it succeeds. A task
that has been running for two days goes on seeing the generation it pinned,
because that generation is still exactly where it was and still exactly what
it was.
"""

from __future__ import annotations

import contextlib
import json
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.domain.errors import DomainError
from app.domain.packaging import Package, digest_of, read_inventory
from app.infrastructure.reclaim import OutsideRoot, remove_within

# Where a generation is mounted while it is being built and while a task uses
# it. The same path in both, always: see the module docstring.
CONTAINER_PATH = "/env"
SITE_PACKAGES = "lib/python{major}.{minor}/site-packages"


class BuildFailed(DomainError):
    code = "environment.build_failed"

    def __init__(self, message: str, *, log: str = "") -> None:
        super().__init__(message, details={"log": log[-4000:]})
        self.log = log


@dataclass(frozen=True, slots=True)
class BuiltGeneration:
    """A generation on disk, inventoried and hashed."""

    path: Path
    digest: str
    packages: list[Package]
    python_version: str
    log: str = ""

    @property
    def editable(self) -> bool:
        return any(package.is_editable for package in self.packages)


@dataclass
class GenerationBuilder:
    """Builds generations by running the task image against a directory."""

    image: str
    root: Path
    binary: str = "docker"
    # Long, because an install can compile native extensions: numpy from
    # source on a small VM is minutes, not seconds.
    timeout_seconds: int = 30 * 60
    run_as: str = "1000:1000"
    environment_allowlist: tuple[str, ...] = field(default_factory=tuple)

    def available(self) -> bool:
        if shutil.which(self.binary) is None:
            return False
        try:
            probe = subprocess.run(
                [self.binary, "info", "--format", "{{.ServerVersion}}"],
                capture_output=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return probe.returncode == 0

    def path_for(self, environment_id: uuid.UUID, generation_id: uuid.UUID) -> Path:
        return self.root / str(environment_id) / str(generation_id)

    # --- the container ---------------------------------------------------

    def _run(
        self, path: Path, script: str, *, writable: bool = True
    ) -> subprocess.CompletedProcess[str]:
        """Run one shell fragment against a generation directory.

        `sh -c`, and the only thing interpolated into it is a specifier that
        `check_specifier` has already refused anything shell-shaped from.
        """
        command = [
            self.binary,
            "run",
            "--rm",
            "--user",
            self.run_as,
            "--volume",
            f"{path}:{CONTAINER_PATH}:{'rw' if writable else 'ro'}",
            "--workdir",
            "/tmp",
            self.image,
            "sh",
            "-c",
            script,
        ]
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=self.timeout_seconds,
            check=False,
        )

    def create(self, path: Path) -> None:
        """Make the first generation of an environment: an empty virtualenv."""
        path.mkdir(parents=True, exist_ok=True)
        result = self._run(
            path, f"python -m venv {CONTAINER_PATH} && {CONTAINER_PATH}/bin/pip --version"
        )
        if result.returncode != 0:
            raise BuildFailed(
                "The environment could not be created.", log=result.stdout + result.stderr
            )

    def copy(self, source: Path, destination: Path) -> None:
        """Copy a generation so the next one can be built from it.

        On the host rather than in the container: the container runs as a
        fixed uid that owns the directory contents, and copying with
        `shutil` keeps the modes without needing a second mount.
        """
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, destination, symlinks=True)

    def install(self, path: Path, specifier: str, *, upgrade: bool = False) -> str:
        flag = " --upgrade" if upgrade else ""
        result = self._run(
            path,
            f"{CONTAINER_PATH}/bin/pip install --no-input --disable-pip-version-check"
            f"{flag} -- '{specifier}'",
        )
        log = result.stdout + result.stderr
        if result.returncode != 0:
            raise BuildFailed(f"Installing '{specifier}' failed.", log=log)
        return log

    def uninstall(self, path: Path, specifier: str) -> str:
        result = self._run(
            path,
            f"{CONTAINER_PATH}/bin/pip uninstall --yes --disable-pip-version-check"
            f" -- '{specifier}'",
        )
        log = result.stdout + result.stderr
        if result.returncode != 0:
            raise BuildFailed(f"Uninstalling '{specifier}' failed.", log=log)
        return log

    def inventory(self, path: Path) -> tuple[list[Package], str]:
        """What is installed, and which Python it is installed for."""
        result = self._run(
            path,
            f"{CONTAINER_PATH}/bin/pip list --format=json --disable-pip-version-check && "
            f'echo "---" && {CONTAINER_PATH}/bin/python -c '
            "'import sys; print(\"%d.%d\" % sys.version_info[:2])'",
            writable=False,
        )
        if result.returncode != 0:
            raise BuildFailed(
                "The environment could not be inventoried.", log=result.stdout + result.stderr
            )
        raw, _, version = result.stdout.rpartition("---")
        try:
            packages = read_inventory(json.loads(raw.strip() or "[]"))
        except (json.JSONDecodeError, ValueError) as error:
            raise BuildFailed(f"The package list could not be read: {error}") from error
        return packages, version.strip()

    def finish(self, path: Path, log: str = "") -> BuiltGeneration:
        packages, python_version = self.inventory(path)
        return BuiltGeneration(
            path=path,
            digest=digest_of(packages),
            packages=packages,
            python_version=python_version,
            log=log,
        )

    def discard(self, path: Path) -> None:
        """Remove a generation that will not be used.

        A failed build leaves a directory that nothing points at, and for a
        multi-gigabyte environment that is real disk. Best effort on purpose:
        the caller is already handling a failure and a second one here would
        replace a useful message from pip with a useless one about a
        directory.
        """
        with contextlib.suppress(OSError, OutsideRoot):
            remove_generation(path, root=self.root)


def remove_generation(path: Path | str, *, root: Path | str) -> bool:
    """Remove one generation's directory. True when there was one to remove.

    The containment check is `remove_within`: the path comes out of a database
    row, and every sweep in this system has the same reason not to trust one.
    """
    return remove_within(path, root=root)


def site_packages_of(generation_path: Path | str, python_version: str | None) -> str:
    """Where a generation's libraries are, inside the container.

    Returned as a container path rather than a host one: this is what goes on
    PYTHONPATH for a task, and the container only ever sees `/env`.
    """
    major, _, minor = (python_version or "3.12").partition(".")
    return f"{CONTAINER_PATH}/{SITE_PACKAGES.format(major=major, minor=minor or '12')}"


# --- introspection ---------------------------------------------------------
#
# "What can I call?" is the authoring experience in a generic Python executor
# (document 09). An author writing `package: labUtils.demo, method: run` is
# guessing unless something can tell them what exists and what it takes.
#
# Done by running a script **inside the generation**, because the answer
# depends on what is installed there and the API process has none of it. The
# script is a constant in this file, never anything a caller supplies, and it
# imports only what it is asked for by name.

INTROSPECT = r"""
import importlib, inspect, json, pkgutil, sys

def describe(obj, name):
    try:
        signature = str(inspect.signature(obj))
    except (TypeError, ValueError):
        signature = "(...)"
    doc = (inspect.getdoc(obj) or "").strip().splitlines()
    return {"name": name, "signature": signature, "summary": doc[0] if doc else ""}

target = sys.argv[1] if len(sys.argv) > 1 else ""
if not target:
    # Only what is installed *here*. Listing every importable module puts
    # `antigravity` in front of an author looking for the library an admin
    # installed for them; the standard library is always available and is
    # not what this screen is answering.
    here = [p for p in sys.path if "site-packages" in p]
    modules = sorted(
        {module.name for module in pkgutil.iter_modules(here) if not module.name.startswith("_")}
    )
    print(json.dumps({"modules": modules}))
else:
    module = importlib.import_module(target)
    callables = [
        describe(value, name)
        for name, value in sorted(vars(module).items())
        if not name.startswith("_")
        and callable(value)
        and getattr(value, "__module__", "") == target
    ]
    print(json.dumps({"module": target, "callables": callables}))
"""


def introspect(builder: GenerationBuilder, path: Path, module: str = "") -> dict[str, Any]:
    """List importable modules, or the callables of one.

    An import executes module-level code, which is why this happens in the
    task container rather than in the API process: the code is
    admin-installed and trusted to *run*, in the place it was installed to
    run, and not trusted enough to run where the platform's own credentials
    are.
    """
    script = INTROSPECT.replace("'", "'\\''")
    safe = module.replace("'", "")
    result = builder._run(
        path,
        f"{CONTAINER_PATH}/bin/python -c '{script}' '{safe}'",
        writable=False,
    )
    if result.returncode != 0:
        trouble = (
            f"'{module}' could not be inspected."
            if module
            else "The environment could not be listed."
        )
        raise BuildFailed(trouble, log=result.stdout + result.stderr)
    try:
        parsed: dict[str, Any] = json.loads(result.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as error:
        raise BuildFailed(f"The introspection output could not be read: {error}") from error
    return parsed
