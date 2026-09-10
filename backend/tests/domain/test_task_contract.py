"""Tests for the task entry-point contract (G20)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.domain.task_contract import (
    CONTRACT_VERSION,
    CallableRef,
    InputBinding,
    OutputDeclaration,
    ResourceLimits,
    TaskError,
    TaskResult,
    TaskSpec,
    verify_outputs,
)


def _limits(**overrides) -> ResourceLimits:
    base = {"cpu_millicores": 2000, "memory_bytes": 4 << 30, "wall_time_seconds": 3600}
    return ResourceLimits(**{**base, **overrides})


def _spec(**overrides) -> TaskSpec:
    base = dict(
        task_id="t-1",
        run_id="r-1",
        attempt=1,
        stage_key="qc",
        task_key="qc:0",
        callable_ref=CallableRef(kind="python_callable", module="labUtils.qc", attribute="run"),
        limits=_limits(),
    )
    return TaskSpec(**{**base, **overrides})


# --- callable reference ---------------------------------------------------


def test_python_callable_requires_module_and_attribute():
    with pytest.raises(ValidationError):
        CallableRef(kind="python_callable", module="labUtils.qc")


def test_command_requires_a_command_list():
    with pytest.raises(ValidationError):
        CallableRef(kind="command")


def test_relative_import_is_rejected():
    with pytest.raises(ValidationError):
        CallableRef(kind="python_callable", module=".relative", attribute="run")


# --- path containment -----------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["/etc/passwd", "../outside", "a/../../b", "..", "nested/../../escape"],
)
def test_output_paths_may_not_escape_the_workspace(path: str):
    with pytest.raises(ValidationError):
        OutputDeclaration(key="out", kind="file", path=path)


def test_ordinary_relative_paths_are_accepted():
    declaration = OutputDeclaration(key="out", kind="file", path="outputs/report.html")
    assert declaration.path == "outputs/report.html"


def test_a_path_merely_containing_dots_is_fine():
    """'..' must be rejected as a *segment*, not as a substring."""
    assert OutputDeclaration(key="o", kind="file", path="s..ample/x.txt").path


# --- spec invariants ------------------------------------------------------


def test_spec_defaults_to_the_current_contract_version():
    assert _spec().contract_version == CONTRACT_VERSION


def test_unsupported_contract_version_is_refused():
    with pytest.raises(ValidationError, match="unsupported contract version"):
        _spec(contract_version="99.0")


def test_duplicate_input_keys_are_refused():
    with pytest.raises(ValidationError, match="input keys must be unique"):
        _spec(
            inputs=[
                InputBinding(key="a", kind="value", value=1),
                InputBinding(key="a", kind="value", value=2),
            ]
        )


def test_duplicate_output_keys_are_refused():
    with pytest.raises(ValidationError, match="output keys must be unique"):
        _spec(
            outputs=[
                OutputDeclaration(key="o", kind="file", path="a"),
                OutputDeclaration(key="o", kind="file", path="b"),
            ]
        )


def test_file_input_requires_a_path():
    with pytest.raises(ValidationError):
        InputBinding(key="sheet", kind="file")


def test_value_input_may_not_carry_a_path():
    with pytest.raises(ValidationError):
        InputBinding(key="n", kind="value", value=1, path="somewhere")


def test_unknown_fields_are_rejected_in_both_directions():
    """A field the other side does not know is a version mismatch, not noise."""
    with pytest.raises(ValidationError):
        TaskSpec.model_validate({**_spec().model_dump(), "surprise": True})


# --- secret scrubbing -----------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["DATABASE_URL", "BP_SESSION_SECRET", "ANTHROPIC_API_KEY", "pg_password", "SOME_TOKEN"],
)
def test_credential_shaped_environment_variables_are_refused(name: str):
    with pytest.raises(ValidationError, match="looks like a credential"):
        _spec(environment={name: "value"})


def test_ordinary_environment_variables_are_allowed():
    spec = _spec(environment={"OMP_NUM_THREADS": "4", "SAMPLE_ID": "s1"})
    assert spec.environment["OMP_NUM_THREADS"] == "4"


# --- results --------------------------------------------------------------


def test_failed_result_must_carry_an_error():
    with pytest.raises(ValidationError, match="must carry an error"):
        TaskResult(task_id="t-1", attempt=1, status="failed")


def test_succeeded_result_must_not_carry_an_error():
    with pytest.raises(ValidationError, match="must not carry an error"):
        TaskResult(
            task_id="t-1",
            attempt=1,
            status="succeeded",
            error=TaskError(code="x", message="y"),
        )


def test_error_kind_distinguishes_bad_input_from_a_crash():
    result = TaskResult(
        task_id="t-1",
        attempt=1,
        status="failed",
        error=TaskError(code="sheet.malformed", message="bad header", kind="input_invalid"),
    )
    assert result.error is not None
    assert result.error.kind == "input_invalid"


def test_checksum_must_be_lowercase_sha256_hex():
    from app.domain.task_contract import OutputReport

    with pytest.raises(ValidationError):
        OutputReport(key="o", path="out.txt", checksum_sha256="NOTAHASH")


# --- output verification --------------------------------------------------


def test_missing_required_output_is_unsatisfied():
    declarations = [OutputDeclaration(key="report", kind="file", path="outputs/r.html")]
    [verdict] = verify_outputs(declarations, {"report": None})
    assert not verdict.present
    assert not verdict.satisfied
    assert verdict.reason == "declared output was not produced"


def test_missing_optional_output_is_satisfied():
    declarations = [OutputDeclaration(key="extra", kind="file", path="outputs/x", required=False)]
    [verdict] = verify_outputs(declarations, {"extra": None})
    assert verdict.satisfied


def test_output_below_the_declared_minimum_is_unsatisfied():
    declarations = [OutputDeclaration(key="bam", kind="file", path="outputs/a.bam", min_bytes=1024)]
    [verdict] = verify_outputs(declarations, {"bam": 10})
    assert verdict.present
    assert not verdict.satisfied
    assert "below the declared minimum" in (verdict.reason or "")


def test_a_produced_output_is_satisfied():
    declarations = [OutputDeclaration(key="bam", kind="file", path="outputs/a.bam")]
    [verdict] = verify_outputs(declarations, {"bam": 4096})
    assert verdict.satisfied and verdict.reason is None
