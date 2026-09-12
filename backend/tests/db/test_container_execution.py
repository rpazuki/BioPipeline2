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

from app.domain.task_contract import (
    CallableRef,
    ResourceLimits,
    StepSpec,
    TaskSpec,
)
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
        steps=[
            StepSpec(
                name="only",
                callable_ref=CallableRef(kind="python_callable", module="json", attribute="dumps"),
                parameters={"obj": {"ok": True}},
            )
        ],
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
    assert result["contract_version"] == "2.0"


def test_logs_are_captured(adapter, workspace):
    log_path = workspace.logs / "task.log"
    outcome = adapter.run(_spec(), workspace.root, log_path=log_path)
    assert outcome.log_path == log_path
    assert log_path.is_file()


def test_a_science_error_fails_the_task_without_crashing_the_worker(adapter, workspace):
    outcome = adapter.run(
        _spec(
            steps=[
                StepSpec(
                    name="only",
                    callable_ref=CallableRef(
                        kind="python_callable", module="json", attribute="loads"
                    ),
                    parameters={"s": "{not json"},
                )
            ],
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
            steps=[
                StepSpec(
                    name="only",
                    callable_ref=CallableRef(
                        kind="python_callable", module="labUtils.absent", attribute="run"
                    ),
                    parameters={},
                )
            ],
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
            steps=[
                StepSpec(
                    name="only",
                    callable_ref=CallableRef(
                        kind="python_callable", module="pathlib", attribute="Path"
                    ),
                    parameters={},
                )
            ],
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
        steps=[
            StepSpec(
                name="only",
                callable_ref=CallableRef(
                    kind="python_callable", module="pathlib", attribute="Path"
                ),
                parameters={},
            )
        ],
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
            steps=[
                StepSpec(
                    name="only",
                    callable_ref=CallableRef(
                        kind="python_callable", module="signal", attribute="pause"
                    ),
                    parameters={},
                )
            ],
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


# --- why contract 2.0 exists, proven in a container ------------------------


def _science_module(workspace) -> None:
    """Write a module the container can import, standing in for labUtils.

    Mounted through the workspace rather than baked into the image, which is
    also how a real runtime environment supplies science code.
    """
    module = workspace.root / "labfake.py"
    module.write_text(
        "import pathlib\n"
        "def make_table(rows=3):\n"
        "    return [{'n': i} for i in range(rows)]\n"
        "def count_rows(table):\n"
        "    if not isinstance(table, list):\n"
        "        raise TypeError(f'expected a table, got {type(table).__name__}')\n"
        "    pathlib.Path('outputs/count.txt').write_text(str(len(table)))\n"
        "    return len(table)\n"
        "def write_table(path, rows=3):\n"
        "    p = pathlib.Path(path)\n"
        "    p.parent.mkdir(parents=True, exist_ok=True)\n"
        "    p.write_text('\\n'.join(str(i) for i in range(rows)))\n"
        "    return str(p)\n"
        "def count_lines(path):\n"
        "    n = len(pathlib.Path(path).read_text().splitlines())\n"
        "    pathlib.Path('outputs/lines.txt').write_text(str(n))\n"
        "    return n\n"
    )


def _step(name, attribute, parameters=None, retain=None) -> StepSpec:
    return StepSpec(
        name=name,
        callable_ref=CallableRef(kind="python_callable", module="labfake", attribute=attribute),
        parameters=parameters or {},
        retain=retain or [],
    )


def _with_pythonpath(adapter: DockerAdapter) -> DockerAdapter:
    """The workspace is on sys.path, so the fake science module is importable
    exactly as a mounted runtime environment would be."""
    return DockerAdapter(image=adapter.image)


def test_a_live_object_passes_between_steps_in_one_container(adapter, workspace):
    """The behaviour one-container-per-step could not provide: the second step
    receives the list the first returned, not the string 'table'."""
    _science_module(workspace)
    spec = _spec(
        steps=[
            _step("table", "make_table", {"rows": 4}, retain=["table"]),
            _step("counted", "count_rows", {"table": "table"}),
        ],
        environment={"PYTHONPATH": "/work"},
    )
    outcome = adapter.run(spec, workspace.root)
    assert outcome.succeeded, outcome.result
    assert (workspace.outputs / "count.txt").read_text() == "4"


def test_a_step_can_spill_to_disk_and_hand_over_a_path(adapter, workspace):
    """For data too large to hold in memory. The path is an ordinary payload
    value; the platform needs no serialisation format of its own."""
    _science_module(workspace)
    spec = _spec(
        steps=[
            _step(
                "spilled",
                "write_table",
                {"path": "outputs/big.txt", "rows": 6},
                retain=["spilled"],
            ),
            _step("lines", "count_lines", {"path": "spilled"}),
        ],
        environment={"PYTHONPATH": "/work"},
    )
    outcome = adapter.run(spec, workspace.root)
    assert outcome.succeeded, outcome.result
    assert (workspace.outputs / "big.txt").is_file()
    assert (workspace.outputs / "lines.txt").read_text() == "6"


def test_relative_paths_resolve_against_the_workspace(adapter, workspace):
    """`outputs/big.txt` means the same thing in a container and in-process,
    because both work from the workspace."""
    _science_module(workspace)
    spec = _spec(
        steps=[_step("spilled", "write_table", {"path": "outputs/rel.txt"})],
        environment={"PYTHONPATH": "/work"},
    )
    outcome = adapter.run(spec, workspace.root)
    assert outcome.succeeded, outcome.result
    assert (workspace.outputs / "rel.txt").is_file()


def test_a_failing_step_is_identified_by_name(adapter, workspace):
    _science_module(workspace)
    spec = _spec(
        steps=[
            _step("table", "make_table", {"rows": 1}, retain=["table"]),
            _step("boom", "count_rows", {"table": "not_a_reference"}),
        ],
        environment={"PYTHONPATH": "/work"},
    )
    outcome = adapter.run(spec, workspace.root)
    assert not outcome.succeeded
    assert outcome.result["error"]["details"]["step"] == "boom"


def test_a_task_setting_pythonpath_cannot_break_the_runner(adapter, workspace):
    """A task legitimately sets PYTHONPATH to reach its science code. When the
    runner was reached through PYTHONPATH too, doing so overrode the image's
    value and made the runner itself unimportable. It now lives in
    site-packages, so the platform's entry point does not depend on a variable
    a task can set."""
    _science_module(workspace)
    spec = _spec(
        steps=[_step("table", "make_table", {"rows": 1})],
        environment={"PYTHONPATH": "/work"},
    )
    outcome = adapter.run(spec, workspace.root)
    assert outcome.succeeded, outcome.result
