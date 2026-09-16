"""The Docker adapter's command construction.

Asserted without launching anything: the containment baseline is the part
that must not regress, and it is fully determined by the command line.
"""

from __future__ import annotations

import pathlib

import pytest

from app.domain.task_contract import (
    CallableRef,
    ResourceLimits,
    StepSpec,
    TaskSpec,
)
from app.infrastructure.execution.docker import LABEL_PLATFORM, DockerAdapter


def _spec(**overrides) -> TaskSpec:
    base = dict(
        task_id="t-1",
        run_id="r-1",
        attempt=1,
        stage_key="s",
        task_key="s:0",
        steps=[
            StepSpec(
                name="qc",
                callable_ref=CallableRef(
                    kind="python_callable", module="labUtils.qc", attribute="run"
                ),
            )
        ],
        limits=ResourceLimits(
            cpu_millicores=2000, memory_bytes=4 * 1024**3, wall_time_seconds=3600
        ),
    )
    base.update(overrides)
    return TaskSpec(**base)


@pytest.fixture
def command(tmp_path):
    adapter = DockerAdapter(image="biopipeline2/task-base:dev")
    return adapter.build_command(_spec(), tmp_path, container_name="bp2-test")


def _value_after(command: list[str], flag: str) -> str | None:
    return command[command.index(flag) + 1] if flag in command else None


# --- the containment baseline (ADR 0030) ---------------------------------
#
# Trusted authors, untrusted transitive dependencies. None of this claims to
# be a hostile-code sandbox; all of it is nearly free, and a regression here
# would be silent without these assertions.


def test_the_task_runs_as_a_non_root_user(command):
    assert _value_after(command, "--user") == "1000:1000"


def test_the_root_filesystem_is_read_only(command):
    assert "--read-only" in command


def test_all_capabilities_are_dropped(command):
    assert _value_after(command, "--cap-drop") == "ALL"


def test_privilege_escalation_is_blocked(command):
    assert _value_after(command, "--security-opt") == "no-new-privileges"


def test_there_is_no_network_by_default(command):
    assert _value_after(command, "--network") == "none"


def test_the_process_count_is_capped(command):
    assert _value_after(command, "--pids-limit") is not None


def test_no_docker_socket_is_ever_mounted(command):
    assert not any("docker.sock" in argument for argument in command)


def test_the_container_is_not_privileged(command):
    assert "--privileged" not in command


# --- resources ------------------------------------------------------------


def test_cpu_and_memory_match_what_admission_control_reserved(command):
    assert _value_after(command, "--cpus") == "2.000"
    assert _value_after(command, "--memory") == str(4 * 1024**3)


def test_the_workspace_is_the_only_writable_mount(tmp_path):
    adapter = DockerAdapter(image="i", extra_mounts={"/shared/data": "/shared"})
    command = adapter.build_command(_spec(), tmp_path, container_name="c")
    mounts = [
        command[index + 1] for index, argument in enumerate(command) if argument == "--volume"
    ]
    writable = [mount for mount in mounts if mount.endswith(":rw")]
    assert writable == [f"{tmp_path}:/work:rw"]
    assert "/shared/data:/shared:ro" in mounts


# --- network opt-in -------------------------------------------------------


def test_a_pipeline_can_ask_for_network_access(tmp_path):
    """Some pipelines fetch models from public endpoints, so egress is
    available -- but only when the workflow asked for it."""
    adapter = DockerAdapter(image="i")
    spec = _spec(
        limits=ResourceLimits(
            cpu_millicores=1000,
            memory_bytes=1024**3,
            wall_time_seconds=60,
            network="egress",
        )
    )
    command = adapter.build_command(spec, tmp_path, container_name="c")
    assert _value_after(command, "--network") != "none"


# --- environment ----------------------------------------------------------


def test_only_the_declared_environment_is_passed(tmp_path):
    adapter = DockerAdapter(image="i")
    spec = _spec(environment={"OMP_NUM_THREADS": "4"})
    command = adapter.build_command(spec, tmp_path, container_name="c")
    passed = [command[index + 1] for index, argument in enumerate(command) if argument == "--env"]
    assert "OMP_NUM_THREADS=4" in passed
    # Only the contract's own variables accompany it.
    assert {p.split("=")[0] for p in passed} == {
        "OMP_NUM_THREADS",
        "BP_TASK_SPEC",
        "BP_RESULT_PATH",
        "BP_WORKSPACE",
    }


def test_a_credential_shaped_variable_cannot_reach_a_task():
    """Defence in depth: the spec model refuses it before the adapter sees it."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="looks like a credential"):
        _spec(environment={"DATABASE_URL": "postgresql://..."})


# --- identification -------------------------------------------------------


def test_containers_are_labelled_so_orphans_can_be_found(command):
    labels = [command[index + 1] for index, argument in enumerate(command) if argument == "--label"]
    assert any(label.startswith(f"{LABEL_PLATFORM}.task=") for label in labels)
    assert any(label.startswith(f"{LABEL_PLATFORM}.run=") for label in labels)


def test_the_runner_is_what_gets_executed(command):
    assert command[-3:] == ["python", "-m", "app.runner.main"]


# --- science libraries (ADR 0028) ------------------------------------------


def test_a_library_directory_is_mounted_read_only():
    """A task that can write to the library directory can change what every
    later task imports."""
    adapter = DockerAdapter(image="i", library_paths=("/opt/science",))
    command = adapter.build_command(_spec(), pathlib.Path("/ws"), container_name="c")
    assert "/opt/science:/opt/science:ro" in command


def test_a_library_directory_reaches_pythonpath():
    """Otherwise it is mounted and unimportable, which is the same as absent."""
    adapter = DockerAdapter(image="i", library_paths=("/opt/science",))
    command = adapter.build_command(_spec(), pathlib.Path("/ws"), container_name="c")
    assert "PYTHONPATH=/opt/science" in command


def test_a_task_that_sets_its_own_pythonpath_keeps_it():
    """Merged, not overwritten. A task legitimately points PYTHONPATH at its
    own code, and dropping either side breaks one of them."""
    adapter = DockerAdapter(image="i", library_paths=("/opt/science",))
    command = adapter.build_command(
        _spec(environment={"PYTHONPATH": "/work/code"}), pathlib.Path("/ws"), container_name="c"
    )
    assert "PYTHONPATH=/work/code:/opt/science" in command


def test_no_library_directory_means_no_pythonpath():
    command = DockerAdapter(image="i").build_command(
        _spec(), pathlib.Path("/ws"), container_name="c"
    )
    assert not any(part.startswith("PYTHONPATH=") for part in command)
