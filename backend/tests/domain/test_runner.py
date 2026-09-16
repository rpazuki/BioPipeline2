"""The in-container task runner.

Tested in-process: the runner is plain Python with no container dependency,
so its behaviour can be pinned down without one. The container tests
elsewhere prove the same code works when actually launched.
"""

from __future__ import annotations

import ast
import json
import os
import pathlib
import sys

from app.runner.main import EXIT_CONTRACT, EXIT_FAILED, EXIT_OK, main

RUNNER = pathlib.Path(__file__).resolve().parents[2] / "app/runner/main.py"


def _spec(workspace: pathlib.Path, **overrides) -> pathlib.Path:
    spec = {
        "contract_version": "2.0",
        "task_id": "t-1",
        "run_id": "r-1",
        "attempt": 1,
        "stage_key": "s",
        "task_key": "s:0",
        "steps": [
            {
                "name": "encoded",
                "callable_ref": {
                    "kind": "python_callable",
                    "module": "json",
                    "attribute": "dumps",
                },
                "parameters": {"obj": {"hello": "world"}},
            }
        ],
        "inputs": [],
        "outputs": [],
        "limits": {
            "cpu_millicores": 1000,
            "memory_bytes": 1073741824,
            "wall_time_seconds": 60,
        },
    }
    spec.update(overrides)
    path = workspace / ".bp" / "task.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(spec))
    return path


def _invoke(workspace: pathlib.Path) -> tuple[int, dict]:
    """Run the runner in-process.

    It chdirs to the workspace, as the container's --workdir does, so the
    original directory is restored here to keep later tests unaffected.
    """
    origin = os.getcwd()
    result_path = workspace / ".bp" / "result.json"
    try:
        code = main(
            [
                "--spec",
                str(workspace / ".bp" / "task.json"),
                "--result",
                str(result_path),
                "--workspace",
                str(workspace),
            ]
        )
    finally:
        os.chdir(origin)
    return code, json.loads(result_path.read_text())


# --- the dependency constraint -------------------------------------------


def test_the_runner_imports_nothing_outside_the_standard_library():
    """It runs inside every task image, so anything it imports becomes a
    dependency of every image an admin builds, and a potential conflict with
    the science code it exists to call."""
    tree = ast.parse(RUNNER.read_text())
    imported = {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    imported |= {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert not imported - set(sys.stdlib_module_names)


# --- the happy path -------------------------------------------------------


def test_a_task_that_succeeds_reports_success(tmp_path):
    _spec(tmp_path)
    code, result = _invoke(tmp_path)
    assert code == EXIT_OK
    assert result["status"] == "succeeded"
    assert "error" not in result or result["error"] is None


def test_declared_inputs_seed_the_payload_and_are_referenced_by_name(tmp_path):
    """Inputs behave exactly like step results: a parameter naming an input
    receives its value. That is how the existing `Inputs:` blocks work."""
    _spec(
        tmp_path,
        steps=[
            {
                "name": "written",
                "callable_ref": {
                    "kind": "python_callable",
                    "module": "tests.domain.helpers_runner",
                    "attribute": "writes_output",
                },
                "parameters": {"path": "target", "content": "hello"},
            }
        ],
        inputs=[{"key": "target", "kind": "file", "path": "outputs/written.txt"}],
        outputs=[{"key": "out", "kind": "file", "path": "outputs/written.txt"}],
    )
    code, result = _invoke(tmp_path)
    assert code == EXIT_OK, result
    # The callable received an absolute path, and wrote where it was told.
    assert (tmp_path / "outputs" / "written.txt").read_text() == "hello"
    assert result["outputs"][0]["key"] == "out"


def test_numeric_returns_are_captured_as_metrics(tmp_path):
    _spec(
        tmp_path,
        steps=[
            {
                "name": "only",
                "callable_ref": {
                    "kind": "python_callable",
                    "module": "tests.domain.helpers_runner",
                    "attribute": "returns_metrics",
                },
                "parameters": {},
            }
        ],
    )
    code, result = _invoke(tmp_path)
    assert code == EXIT_OK
    assert result["metrics"] == {"rows": 3.0, "seconds": 1.5}


# --- failures -------------------------------------------------------------


def test_a_raising_callable_is_a_science_error_not_a_crash(tmp_path):
    _spec(
        tmp_path,
        steps=[
            {
                "name": "only",
                "callable_ref": {
                    "kind": "python_callable",
                    "module": "tests.domain.helpers_runner",
                    "attribute": "always_raises",
                },
                "parameters": {},
            }
        ],
    )
    code, result = _invoke(tmp_path)
    assert code == EXIT_FAILED
    assert result["status"] == "failed"
    assert result["error"]["kind"] == "science_error"
    assert "traceback" in result["error"]["details"]


def test_a_signature_mismatch_is_reported_as_bad_input(tmp_path):
    """The fix is in the pipeline, not the science code, so it must not look
    like the science failed."""
    _spec(
        tmp_path,
        steps=[
            {
                "name": "only",
                "callable_ref": {"kind": "python_callable", "module": "json", "attribute": "dumps"},
                "parameters": {"not_a_real_argument": 1},
            }
        ],
    )
    code, result = _invoke(tmp_path)
    assert code == EXIT_FAILED
    assert result["error"]["kind"] == "input_invalid"
    assert result["error"]["code"] == "callable.signature_mismatch"
    assert "arguments" in result["error"]["details"]


def test_an_unimportable_module_says_so_usefully(tmp_path):
    _spec(
        tmp_path,
        steps=[
            {
                "name": "only",
                "callable_ref": {
                    "kind": "python_callable",
                    "module": "labUtils.not_installed",
                    "attribute": "run",
                },
                "parameters": {},
            }
        ],
    )
    code, result = _invoke(tmp_path)
    assert code == EXIT_CONTRACT
    assert "runtime environment" in result["error"]["message"]


def test_a_missing_attribute_is_reported(tmp_path):
    _spec(
        tmp_path,
        steps=[
            {
                "name": "only",
                "callable_ref": {"kind": "python_callable", "module": "json", "attribute": "nope"},
                "parameters": {},
            }
        ],
    )
    code, result = _invoke(tmp_path)
    assert code == EXIT_CONTRACT
    assert "has no attribute" in result["error"]["message"]


def test_a_non_callable_target_is_rejected(tmp_path):
    _spec(
        tmp_path,
        steps=[
            {
                "name": "only",
                "callable_ref": {
                    "kind": "python_callable",
                    "module": "json",
                    "attribute": "__name__",
                },
                "parameters": {},
            }
        ],
    )
    code, _ = _invoke(tmp_path)
    assert code == EXIT_CONTRACT


# --- contract violations --------------------------------------------------


def test_a_missing_specification_is_a_contract_violation(tmp_path):
    (tmp_path / ".bp").mkdir()
    code, result = _invoke(tmp_path)
    assert code == EXIT_CONTRACT
    assert result["error"]["code"] == "contract.violation"


def test_an_unsupported_contract_version_is_refused(tmp_path):
    """The image and the platform disagreeing must fail loudly rather than
    produce undefined behaviour."""
    _spec(tmp_path, contract_version="99.0")
    code, result = _invoke(tmp_path)
    assert code == EXIT_CONTRACT
    assert "99.0" in result["error"]["message"]


def test_a_malformed_specification_is_refused(tmp_path):
    path = tmp_path / ".bp" / "task.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not json")
    code, result = _invoke(tmp_path)
    assert code == EXIT_CONTRACT
    assert "unreadable" in result["error"]["message"]


def test_a_contract_violation_exits_differently_from_a_failure(tmp_path):
    """The worker treats them differently: one means the image is wrong, the
    other means the science failed."""
    assert EXIT_CONTRACT != EXIT_FAILED


# --- output reporting -----------------------------------------------------


def test_declared_outputs_that_exist_are_reported(tmp_path):
    (tmp_path / "outputs").mkdir()
    (tmp_path / "outputs" / "report.txt").write_text("x" * 10)
    _spec(
        tmp_path,
        outputs=[{"key": "report", "kind": "file", "path": "outputs/report.txt"}],
    )
    code, result = _invoke(tmp_path)
    assert code == EXIT_OK
    assert result["outputs"] == [{"key": "report", "path": "outputs/report.txt", "size_bytes": 10}]


def test_a_declared_output_that_was_not_produced_is_simply_absent(tmp_path):
    """The runner reports; the worker decides. Only the worker's own stat of
    the workspace determines whether a required output is missing."""
    _spec(tmp_path, outputs=[{"key": "gone", "kind": "file", "path": "outputs/x"}])
    code, result = _invoke(tmp_path)
    assert code == EXIT_OK
    assert result["outputs"] == []


# --- the reason contract 2.0 exists ---------------------------------------


def _steps(*steps) -> list[dict]:
    return list(steps)


def _step(name, attribute, parameters=None, retain=None):
    return {
        "name": name,
        "callable_ref": {
            "kind": "python_callable",
            "module": "tests.domain.helpers_runner",
            "attribute": attribute,
        },
        "parameters": parameters or {},
        "retain": retain or [],
    }


def test_a_step_receives_an_earlier_steps_object_not_its_name(tmp_path):
    """The whole reason a stage runs in one container. Under one-container-
    per-step this passed the literal string 'table' and the callable failed."""
    _spec(
        tmp_path,
        steps=_steps(
            _step("table", "make_table", {"rows": 4}, retain=["table"]),
            _step("counted", "count_rows", {"table": "table"}),
        ),
    )
    code, result = _invoke(tmp_path)
    assert code == EXIT_OK, result


def test_a_step_may_hand_over_a_path_instead_of_an_object(tmp_path):
    """For data too large to hold in memory: spill to disk, return the path,
    and the next step opens it. No special support needed -- the path is just
    a payload value."""
    _spec(
        tmp_path,
        steps=_steps(
            _step(
                "spilled",
                "write_table",
                {"path": "outputs/big.txt", "rows": 5},
                retain=["spilled"],
            ),
            _step("lines", "count_lines", {"path": "spilled"}),
        ),
    )
    code, result = _invoke(tmp_path)
    assert code == EXIT_OK, result
    assert (tmp_path / "outputs" / "big.txt").is_file()


def test_a_payload_entry_is_released_once_nothing_refers_to_it(tmp_path, capsys):
    """Without eviction the stage holds every intermediate until it ends, so
    returning a path to save memory would save nothing."""
    _spec(
        tmp_path,
        steps=_steps(
            _step("table", "make_table", {"rows": 2}, retain=["table"]),
            # 'table' is absent from retain, so it is dropped after this step.
            _step("counted", "count_rows", {"table": "table"}, retain=["counted"]),
            _step("again", "count_rows", {"table": "counted"}),
        ),
    )
    code, _ = _invoke(tmp_path)
    captured = capsys.readouterr().out
    assert "released table" in captured, captured
    # 'counted' is an int, so the third step raises rather than silently
    # accepting the wrong type.
    assert code == EXIT_FAILED


def test_the_last_step_retains_nothing(tmp_path):
    """Nothing follows it, so nothing needs to survive it. With a single step
    there is simply nothing to release."""
    _spec(tmp_path, steps=_steps(_step("only", "make_table", {"rows": 1})))
    code, result = _invoke(tmp_path)
    assert code == EXIT_OK
    assert result["status"] == "succeeded"


def test_a_reference_inside_a_list_resolves(tmp_path):
    """One parameter can gather several upstream results, keeping its shape."""
    _spec(
        tmp_path,
        steps=_steps(
            _step("table", "make_table", {"rows": 1}, retain=["table"]),
            _step("gathered", "count_rows", {"table": "table"}),
        ),
    )
    assert _invoke(tmp_path)[0] == EXIT_OK


def test_a_failing_step_names_itself_and_shows_the_payload(tmp_path):
    """Debugging a ten-step stage needs to know which step broke and what was
    available to it."""
    _spec(
        tmp_path,
        steps=_steps(
            _step("table", "make_table", {"rows": 1}, retain=["table"]),
            _step("boom", "count_rows", {"wrong_argument": "table"}),
        ),
    )
    code, result = _invoke(tmp_path)
    assert code == EXIT_FAILED
    assert result["error"]["details"]["step"] == "boom"
    assert "table" in result["error"]["details"]["payload"]


def test_steps_run_in_order(tmp_path):
    """A step may only reference results that already exist."""
    _spec(
        tmp_path,
        steps=_steps(
            _step("first", "count_rows", {"table": "second"}),
            _step("second", "make_table", {"rows": 1}),
        ),
    )
    code, result = _invoke(tmp_path)
    # 'second' has not run yet, so the reference is passed through literally
    # and count_rows rejects the string.
    assert code == EXIT_FAILED
    assert result["error"]["details"]["step"] == "first"


# --- where output_dir points ----------------------------------------------
#
# Found by the Phase 0b spike, and only by it: six fanned-out tasks share one
# workspace, so a fixed `outputs/` meant every task of a run wrote over the
# previous one and then failed verification having produced good files in the
# wrong place. Nothing caught it because the unit fixtures declare one task.


def test_output_dir_is_the_declared_output_directory(tmp_path):
    from app.runner.main import _output_dir

    spec = {"outputs": [{"key": "results", "kind": "directory", "path": "processed/rep/p01"}]}
    assert _output_dir(spec, tmp_path) == tmp_path / "processed/rep/p01"


def test_two_fanned_out_tasks_do_not_share_an_output_directory(tmp_path):
    from app.runner.main import _output_dir

    first = {"outputs": [{"key": "r", "kind": "directory", "path": "processed/rep/p01"}]}
    second = {"outputs": [{"key": "r", "kind": "directory", "path": "processed/rep/p02"}]}
    assert _output_dir(first, tmp_path) != _output_dir(second, tmp_path)


def test_several_declared_outputs_fall_back_to_the_outputs_directory(tmp_path):
    """No single directory could be meant, so the task must write each path."""
    from app.runner.main import _output_dir

    spec = {
        "outputs": [
            {"key": "a", "kind": "directory", "path": "one"},
            {"key": "b", "kind": "directory", "path": "two"},
        ]
    }
    assert _output_dir(spec, tmp_path) == tmp_path / "outputs"


def test_no_declared_output_falls_back_to_the_outputs_directory(tmp_path):
    from app.runner.main import _output_dir

    assert _output_dir({"outputs": []}, tmp_path) == tmp_path / "outputs"


def test_a_callable_that_accepts_output_dir_is_given_the_declared_one(tmp_path):
    """End to end through `run()`, because the injection and the directory
    choice are two separate things that both have to be right."""
    from app.runner.main import run

    workspace = tmp_path / "ws"
    workspace.mkdir()
    spec = {
        "contract_version": "2.0",
        "task_id": "t",
        "run_id": "r",
        "attempt": 1,
        "stage_key": "s",
        "task_key": "s:0",
        "inputs": [],
        "outputs": [{"key": "results", "kind": "directory", "path": "processed/variant/item"}],
        "steps": [
            {
                "name": "written",
                "callable_ref": {
                    "kind": "python_callable",
                    "module": "tests.domain.helpers_runner",
                    "attribute": "write_marker",
                },
                "parameters": {},
            }
        ],
        "limits": {"cpu_millicores": 1, "memory_bytes": 1, "wall_time_seconds": 60},
    }
    result = run(spec, workspace)
    assert result["status"] == "succeeded", result
    assert (workspace / "processed/variant/item/marker.txt").is_file()
