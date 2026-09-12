"""The in-container task runner.

Tested in-process: the runner is plain Python with no container dependency,
so its behaviour can be pinned down without one. The container tests
elsewhere prove the same code works when actually launched.
"""

from __future__ import annotations

import ast
import json
import pathlib
import sys

from app.runner.main import EXIT_CONTRACT, EXIT_FAILED, EXIT_OK, main

RUNNER = pathlib.Path(__file__).resolve().parents[2] / "app/runner/main.py"


def _spec(workspace: pathlib.Path, **overrides) -> pathlib.Path:
    spec = {
        "contract_version": "1.0",
        "task_id": "t-1",
        "run_id": "r-1",
        "attempt": 1,
        "stage_key": "s",
        "task_key": "s:0",
        "callable_ref": {
            "kind": "python_callable",
            "module": "json",
            "attribute": "dumps",
        },
        "parameters": {"obj": {"hello": "world"}},
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
    result_path = workspace / ".bp" / "result.json"
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


def test_path_inputs_are_handed_over_as_absolute_paths(tmp_path):
    """Science code should not have to know the workspace layout."""
    _spec(
        tmp_path,
        callable_ref={
            "kind": "python_callable",
            "module": "tests.domain.helpers_runner",
            "attribute": "writes_output",
        },
        parameters={"content": "hello"},
        inputs=[{"key": "path", "kind": "file", "path": "outputs/written.txt"}],
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
        callable_ref={
            "kind": "python_callable",
            "module": "tests.domain.helpers_runner",
            "attribute": "returns_metrics",
        },
        parameters={},
    )
    code, result = _invoke(tmp_path)
    assert code == EXIT_OK
    assert result["metrics"] == {"rows": 3.0, "seconds": 1.5}


# --- failures -------------------------------------------------------------


def test_a_raising_callable_is_a_science_error_not_a_crash(tmp_path):
    _spec(
        tmp_path,
        callable_ref={
            "kind": "python_callable",
            "module": "tests.domain.helpers_runner",
            "attribute": "always_raises",
        },
        parameters={},
    )
    code, result = _invoke(tmp_path)
    assert code == EXIT_FAILED
    assert result["status"] == "failed"
    assert result["error"]["kind"] == "science_error"
    assert "traceback" in result["error"]["details"]


def test_a_signature_mismatch_is_reported_as_bad_input(tmp_path):
    """The fix is in the pipeline, not the science code, so it must not look
    like the science failed."""
    _spec(tmp_path, parameters={"not_a_real_argument": 1})
    code, result = _invoke(tmp_path)
    assert code == EXIT_FAILED
    assert result["error"]["kind"] == "input_invalid"
    assert result["error"]["code"] == "callable.signature_mismatch"
    assert "arguments" in result["error"]["details"]


def test_an_unimportable_module_says_so_usefully(tmp_path):
    _spec(
        tmp_path,
        callable_ref={
            "kind": "python_callable",
            "module": "labUtils.not_installed",
            "attribute": "run",
        },
        parameters={},
    )
    code, result = _invoke(tmp_path)
    assert code == EXIT_CONTRACT
    assert "runtime environment" in result["error"]["message"]


def test_a_missing_attribute_is_reported(tmp_path):
    _spec(
        tmp_path,
        callable_ref={"kind": "python_callable", "module": "json", "attribute": "nope"},
        parameters={},
    )
    code, result = _invoke(tmp_path)
    assert code == EXIT_CONTRACT
    assert "has no attribute" in result["error"]["message"]


def test_a_non_callable_target_is_rejected(tmp_path):
    _spec(
        tmp_path,
        callable_ref={
            "kind": "python_callable",
            "module": "json",
            "attribute": "__name__",
        },
        parameters={},
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
