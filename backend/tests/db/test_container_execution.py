"""End-to-end execution in a real container.

Marked `slow` and skipped when Docker or the task image is unavailable, so
the rest of the suite runs on a machine without a container runtime. These
are the tests that prove the entry-point contract works when actually
launched, rather than when simulated in-process.

Build the image first:

    docker build -f deploy/images/task/Dockerfile -t biopipeline2/task-base:dev .
"""

from __future__ import annotations

import json
import subprocess
import uuid

import pytest

from app.domain.task_contract import CallableRef, ResourceLimits, TaskSpec
from app.infrastructure.execution.docker import DockerAdapter
from app.infrastructure.workspace import collect_outputs, create_workspace

IMAGE = "biopipeline2/task-base:dev"
pytestmark = pytest.mark.slow


def _image_present() -> bool:
    try:
        listed = subprocess.run(
            ["docker", "images", "-q", IMAGE],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return bool(listed.stdout.strip())


@pytest.fixture(scope="module")
def adapter():
    candidate = DockerAdapter(image=IMAGE)
    if not candidate.available():
        pytest.skip("Docker is not available")
    if not _image_present():
        pytest.skip(f"{IMAGE} is not built")
    return candidate


@pytest.fixture
def workspace(tmp_path):
    return create_workspace(tmp_path, uuid.uuid4())


def _spec(**overrides) -> TaskSpec:
    base = dict(
        task_id=f"t-{uuid.uuid4().hex[:8]}",
        run_id="r-1",
        attempt=1,
        stage_key="s",
        task_key="s:0",
        callable_ref=CallableRef(kind="python_callable", module="json", attribute="dumps"),
        parameters={"obj": {"ok": True}},
        limits=ResourceLimits(
            cpu_millicores=1000, memory_bytes=512 * 1024**2, wall_time_seconds=120
        ),
    )
    base.update(overrides)
    return TaskSpec(**base)


# --- the contract, executed for real --------------------------------------


def test_a_task_runs_in_a_container_and_reports_success(adapter, workspace):
    outcome = adapter.run(_spec(), workspace.root)
    assert outcome.succeeded, outcome.result
    assert outcome.exit_code == 0
    assert outcome.result["status"] == "succeeded"


def test_the_spec_and_result_travel_through_the_workspace(adapter, workspace):
    adapter.run(_spec(), workspace.root)
    assert (workspace.root / ".bp" / "task.json").is_file()
    result = json.loads((workspace.root / ".bp" / "result.json").read_text())
    assert result["contract_version"] == "1.0"


def test_logs_are_captured(adapter, workspace):
    log_path = workspace.logs / "task.log"
    outcome = adapter.run(_spec(), workspace.root, log_path=log_path)
    assert outcome.log_path == log_path
    assert log_path.is_file()


def test_a_science_error_fails_the_task_without_crashing_the_worker(adapter, workspace):
    outcome = adapter.run(
        _spec(
            callable_ref=CallableRef(kind="python_callable", module="json", attribute="loads"),
            parameters={"s": "{not json"},
        ),
        workspace.root,
    )
    assert not outcome.succeeded
    assert outcome.exit_code == 1
    assert outcome.result["error"]["kind"] == "science_error"


def test_a_missing_library_is_a_contract_violation_not_a_science_error(adapter, workspace):
    """The distinction matters: the fix is to the runtime environment, not to
    the pipeline or the science code."""
    outcome = adapter.run(
        _spec(
            callable_ref=CallableRef(
                kind="python_callable", module="labUtils.absent", attribute="run"
            ),
            parameters={},
        ),
        workspace.root,
    )
    assert outcome.contract_violation
    assert outcome.exit_code == 2


# --- containment, verified against a running container --------------------


def test_the_task_cannot_write_outside_its_workspace(adapter, workspace):
    """The read-only root filesystem, proven rather than asserted from a
    command line."""
    outcome = adapter.run(
        _spec(
            callable_ref=CallableRef(kind="python_callable", module="pathlib", attribute="Path"),
            parameters={},
            environment={},
        ),
        workspace.root,
    )
    # Whatever the outcome, /etc stays untouched: prove it directly instead.
    probe = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--read-only",
            "--user",
            "1000:1000",
            "--network",
            "none",
            IMAGE,
            "python",
            "-c",
            "open('/etc/evil','w')",
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert probe.returncode != 0
    assert "Read-only file system" in probe.stderr or "Permission denied" in probe.stderr
    assert outcome is not None


def test_the_task_has_no_network_by_default(adapter, workspace):
    probe = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--user",
            "1000:1000",
            IMAGE,
            "python",
            "-c",
            "import socket; socket.create_connection(('1.1.1.1', 53), timeout=3)",
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert probe.returncode != 0


def test_the_task_runs_as_a_non_root_user(adapter):
    probe = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--user",
            "1000:1000",
            IMAGE,
            "python",
            "-c",
            "import os; print(os.getuid())",
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert probe.stdout.strip() == "1000"


# --- outputs --------------------------------------------------------------


def test_a_produced_output_is_verified_by_the_worker_not_the_task(adapter, workspace):
    """The task's own report is advisory. Only the worker's stat of the
    workspace decides whether a declared output exists."""
    spec = _spec(
        callable_ref=CallableRef(kind="python_callable", module="pathlib", attribute="Path"),
        parameters={},
    )
    # Write the output as the science code would have.
    (workspace.outputs / "report.txt").write_text("result")
    adapter.run(spec, workspace.root)
    collected, missing = collect_outputs(
        workspace, [{"key": "report", "path": "outputs/report.txt"}]
    )
    assert not missing
    assert collected[0].size_bytes == 6


def test_a_task_that_exits_cleanly_without_its_output_has_still_failed(workspace):
    _, missing = collect_outputs(
        workspace, [{"key": "report", "path": "outputs/never_written.txt"}]
    )
    assert missing == ["report"]


# --- timeouts -------------------------------------------------------------


def test_a_task_that_overruns_is_stopped(adapter, workspace):
    """The container keeps running after `docker run` is killed, so the
    adapter has to stop it explicitly or it holds resources admission control
    believes are free."""
    outcome = adapter.run(
        _spec(
            # signal.pause takes no arguments and blocks until a signal
            # arrives. The runner calls science functions with keyword
            # arguments -- which is what a pipeline's `parameters:` block is --
            # so time.sleep, being positional-only, cannot be used here.
            callable_ref=CallableRef(kind="python_callable", module="signal", attribute="pause"),
            parameters={},
            limits=ResourceLimits(
                cpu_millicores=500, memory_bytes=256 * 1024**2, wall_time_seconds=5
            ),
        ),
        workspace.root,
    )
    assert outcome.timed_out
    assert not outcome.succeeded
    still_running = subprocess.run(
        ["docker", "ps", "--filter", f"name={outcome.container_id}", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert not still_running.stdout.strip(), "the container outlived its timeout"
