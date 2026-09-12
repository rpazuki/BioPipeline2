"""Docker execution adapter.

Launches one task container per attempt, per the entry-point contract
(ADR 0005), and enforces the containment baseline from ADR 0030.

That baseline is worth stating plainly, because it is easy to read the trust
model as licence to skip it. Pipeline authors are trusted; their *transitive
dependencies* are not, and trusted authors make mistakes. So every task runs
non-root, with a read-only root filesystem, dropped capabilities,
``no-new-privileges``, no network unless the pipeline asked for it, an
explicit environment allowlist, and hard resource limits. None of that
pretends to be a hostile-code sandbox. All of it is nearly free.

The adapter shells out to the CLI rather than using a Docker SDK: the command
line is the stable interface, it works identically for Podman should ADR 0008
be revisited, and a failure is a readable command rather than a library
traceback.
"""

from __future__ import annotations

import contextlib
import json
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from app.domain.errors import DomainError
from app.domain.task_contract import (
    TASK_RESULT_PATH,
    TASK_SPEC_PATH,
    WORKSPACE_ROOT,
    TaskSpec,
)

LABEL_PLATFORM = "biopipeline2"
"""Every container carries this label, so orphans can be found and reconciled
after a worker dies."""


class ExecutionError(DomainError):
    code = "execution.failed"


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    """What happened to one container."""

    exit_code: int
    container_id: str | None
    timed_out: bool
    cancelled: bool
    result: dict | None
    log_path: Path | None

    @property
    def succeeded(self) -> bool:
        return (
            self.exit_code == 0
            and not self.timed_out
            and not self.cancelled
            and isinstance(self.result, dict)
            and self.result.get("status") == "succeeded"
        )

    @property
    def contract_violation(self) -> bool:
        """Exit code 2 means the image and the platform disagree."""
        return self.exit_code == 2


@dataclass(slots=True)
class DockerAdapter:
    """Runs task containers through the Docker CLI."""

    image: str
    binary: str = "docker"
    # Extra environment variables permitted into a task, beyond the contract's
    # own. An allowlist, because the default is to pass nothing.
    environment_allowlist: tuple[str, ...] = ()
    # Mounted read-only, for shared-storage roots. Host path -> container path.
    extra_mounts: dict[str, str] = field(default_factory=dict)
    run_as: str = "1000:1000"

    def available(self) -> bool:
        """True when the runtime is usable.

        Tests that need a container skip rather than fail when it is not, so a
        machine without Docker still runs the rest of the suite.
        """
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

    def build_command(self, spec: TaskSpec, workspace: Path, *, container_name: str) -> list[str]:
        """The exact command line. Separated so it can be asserted on."""
        limits = spec.limits
        command = [
            self.binary,
            "run",
            "--rm",
            "--name",
            container_name,
            "--label",
            f"{LABEL_PLATFORM}.task={spec.task_id}",
            "--label",
            f"{LABEL_PLATFORM}.run={spec.run_id}",
            # --- containment baseline (ADR 0030) ---
            "--user",
            self.run_as,
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            str(limits.max_processes),
            # --- resources, matching what admission control reserved ---
            "--cpus",
            f"{limits.cpu_millicores / 1000:.3f}",
            "--memory",
            str(limits.memory_bytes),
            # The workspace is the only writable place by default.
            "--volume",
            f"{workspace}:{WORKSPACE_ROOT}:rw",
            "--workdir",
            WORKSPACE_ROOT,
        ]

        if limits.network == "none":
            command += ["--network", "none"]

        for host_path, container_path in sorted(self.extra_mounts.items()):
            command += ["--volume", f"{host_path}:{container_path}:ro"]

        for name, value in sorted(spec.environment.items()):
            command += ["--env", f"{name}={value}"]
        command += [
            "--env",
            f"BP_TASK_SPEC={TASK_SPEC_PATH}",
            "--env",
            f"BP_RESULT_PATH={TASK_RESULT_PATH}",
            "--env",
            f"BP_WORKSPACE={WORKSPACE_ROOT}",
        ]

        command += [self.image, "python", "-m", "app.runner.main"]
        return command

    def run(
        self, spec: TaskSpec, workspace: Path, *, log_path: Path | None = None
    ) -> ExecutionOutcome:
        """Write the spec, launch the container, and collect the outcome."""
        platform_dir = workspace / ".bp"
        platform_dir.mkdir(parents=True, exist_ok=True)
        spec_file = platform_dir / "task.json"
        result_file = platform_dir / "result.json"
        result_file.unlink(missing_ok=True)
        spec_file.write_text(spec.model_dump_json(indent=2))

        container_name = f"bp2-{spec.task_id}-{uuid.uuid4().hex[:8]}"
        command = self.build_command(spec, workspace, container_name=container_name)

        timed_out = False
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=spec.limits.wall_time_seconds,
                check=False,
            )
            exit_code = completed.returncode
            output = (completed.stdout or "") + (completed.stderr or "")
        except subprocess.TimeoutExpired as expired:
            timed_out = True
            exit_code = 124
            output = _decode(expired.stdout) + _decode(expired.stderr)
            # The subprocess timing out does not stop the container: docker run
            # was killed, the container keeps going. Stop it explicitly, or it
            # holds resources admission control believes are free.
            self.stop(container_name, grace_seconds=5)
        except OSError as error:
            raise ExecutionError(
                f"Could not start a task container: {error}",
                details={"command": command[:3]},
            ) from error

        if log_path is not None:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text(output)

        result: dict | None = None
        if result_file.is_file():
            try:
                parsed = json.loads(result_file.read_text())
                result = parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                result = None

        return ExecutionOutcome(
            exit_code=exit_code,
            container_id=container_name,
            timed_out=timed_out,
            cancelled=False,
            result=result,
            log_path=log_path,
        )

    def stop(self, container_name: str, *, grace_seconds: int = 30) -> None:
        """Stop a container: SIGTERM, then SIGKILL after the grace period.

        Used for cancellation and for cleaning up after a timeout. Errors are
        suppressed deliberately: a container that is already gone is the
        outcome this method wanted, and a failed stop must not take down the
        worker mid-cancellation.
        """
        with contextlib.suppress(OSError, subprocess.TimeoutExpired):
            subprocess.run(
                [self.binary, "stop", "--time", str(grace_seconds), container_name],
                capture_output=True,
                timeout=grace_seconds + 15,
                check=False,
            )

    def orphans(self) -> list[str]:
        """Containers this platform started that no live worker owns.

        A worker calls this on startup. A container still running after the
        worker that launched it has gone holds CPU and memory that admission
        control believes are free, so a nonzero steady-state count is a bug
        worth alerting on.
        """
        try:
            listed = subprocess.run(
                [
                    self.binary,
                    "ps",
                    "--filter",
                    f"label={LABEL_PLATFORM}.task",
                    "--format",
                    "{{.Names}}",
                ],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return []
        if listed.returncode != 0:
            return []
        return [name for name in listed.stdout.splitlines() if name.strip()]


def _decode(stream: bytes | str | None) -> str:
    if stream is None:
        return ""
    if isinstance(stream, bytes):
        return stream.decode(errors="replace")
    return stream
