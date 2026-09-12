"""Task runner: the entry point of every task container.

Reads ``/work/.bp/task.json``, runs every step of the stage in order, writes
``/work/.bp/result.json``, and exits. That is the whole contract (ADR 0005).

**Why the whole stage runs here, in one process.** A stage's steps pass live
Python objects to one another: a parameter naming an earlier step receives
that step's return value. In the growth-rate pipelines that is a chain of nine
DataFrames; in the FBA pipelines it is a ``cobra.Model``, which has no honest
round-trip through a file. One container per step would hand the next step the
*string* ``"df_parsed"`` instead of the DataFrame, so the stage is the unit of
execution.

**Passing by path.** A step may write its result to disk and return the path
instead of the object. Nothing special is required: the path lands in the
payload like any other value and the next step opens it. That is how a stage
handles data too large to hold in memory, and the payload eviction below is
what makes it actually save memory.

Deliberately dependency-free: it is the platform's code executing inside an
image whose other contents are chosen by an admin, so it must not impose a
Pydantic or SQLAlchemy version on that image.

Exit codes:

* ``0``  the work succeeded and the result says so
* ``1``  the work failed; ``result.json`` explains why
* ``2``  the contract itself was violated -- no spec, unreadable spec, wrong
         contract version. The worker treats this differently because it means
         the image and the platform disagree, not that the science failed.
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any

CONTRACT_VERSION = "2.0"
SUPPORTED_CONTRACT_VERSIONS = frozenset({"2.0"})

DEFAULT_SPEC = "/work/.bp/task.json"
DEFAULT_RESULT = "/work/.bp/result.json"

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_CONTRACT = 2


class ContractViolation(Exception):
    """The platform and the image disagree about the contract."""


def _load_spec(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ContractViolation(f"No task specification at {path}")
    try:
        spec = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ContractViolation(f"Task specification is unreadable: {error}") from error
    if not isinstance(spec, dict):
        raise ContractViolation("Task specification must be a JSON object")
    version = spec.get("contract_version")
    if version not in SUPPORTED_CONTRACT_VERSIONS:
        raise ContractViolation(
            f"Task specification declares contract version {version!r}; this "
            f"image supports {sorted(SUPPORTED_CONTRACT_VERSIONS)}"
        )
    return spec


def _resolve_callable(reference: dict[str, Any]) -> Any:
    """Import the named callable.

    ``python_callable`` is the direct successor to importing ``labUtils.*`` by
    name, which is how pipelines already name their science code.
    """
    kind = reference.get("kind")
    if kind != "python_callable":
        raise ContractViolation(
            f"This runner handles 'python_callable'; the task asked for {kind!r}"
        )
    module_name = reference.get("module")
    attribute = reference.get("attribute")
    if not module_name or not attribute:
        raise ContractViolation("python_callable requires 'module' and 'attribute'")
    try:
        module = importlib.import_module(module_name)
    except ImportError as error:
        raise ContractViolation(
            f"Cannot import '{module_name}': {error}. The runtime environment "
            "may not have the package this pipeline needs."
        ) from error
    try:
        target = getattr(module, attribute)
    except AttributeError as error:
        raise ContractViolation(f"'{module_name}' has no attribute '{attribute}'") from error
    if not callable(target):
        raise ContractViolation(f"'{module_name}.{attribute}' is not callable")
    return target


def _write_result(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str))


def _report_outputs(spec: dict[str, Any], workspace: Path) -> list[dict[str, Any]]:
    """Report the declared outputs that exist.

    Advisory only: the worker stats the workspace itself and does not trust
    this. It is here because it costs nothing and helps when debugging.
    """
    reported: list[dict[str, Any]] = []
    for declaration in spec.get("outputs", []):
        relative = declaration.get("path")
        if not relative:
            continue
        candidate = workspace / relative
        if candidate.exists():
            size = (
                candidate.stat().st_size
                if candidate.is_file()
                else sum(p.stat().st_size for p in candidate.rglob("*") if p.is_file())
            )
            reported.append({"key": declaration.get("key"), "path": relative, "size_bytes": size})
    return reported


def _resolve(value: Any, payload: dict[str, Any]) -> Any:
    """Substitute payload references, recursing into containers.

    A scalar equal to a payload key resolves to that upstream value; anything
    else is passed literally. Lists and mappings resolve element-wise, so one
    parameter can gather several upstream results while keeping its shape.

    Matches the existing engine's behaviour deliberately, including the
    hashability guard: an unhashable value such as a DataFrame can never be a
    key, and testing membership with one raises.
    """
    if isinstance(value, dict):
        return {key: _resolve(item, payload) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve(item, payload) for item in value]
    try:
        found = value in payload
    except TypeError:
        return value
    return payload[value] if found else value


def _evict(payload: dict[str, Any], retain: list[str]) -> list[str]:
    """Drop payload entries no later step references.

    The compiler works out what is still needed; the runner simply obeys.
    Without this the payload holds every intermediate for the life of the
    stage, and a step that returns a path to save memory would not release the
    DataFrame an earlier step produced.
    """
    keep = set(retain)
    dropped = [name for name in payload if name not in keep]
    for name in dropped:
        del payload[name]
    return dropped


def _describe(value: Any) -> str:
    """A short description of a payload value, for the log.

    Deliberately does not stringify the value: a DataFrame's repr is large and
    a path's is not, and the log should not depend on which it got.
    """
    if isinstance(value, str | os.PathLike):
        return f"path {value}"
    kind = type(value).__name__
    try:
        length = len(value)  # type: ignore[arg-type]
    except TypeError:
        return kind
    return f"{kind}[{length}]"


def run(spec: dict[str, Any], workspace: Path) -> dict[str, Any]:
    """Execute every step of the stage, sharing one payload."""
    payload: dict[str, Any] = {}

    # Declared inputs seed the payload, so a step can name an input exactly as
    # it names an earlier step.
    for binding in spec.get("inputs") or []:
        key = binding.get("key")
        if not key:
            continue
        if binding.get("kind") == "value":
            payload[key] = binding.get("value")
        else:
            # Absolute, so science code never has to know the workspace layout.
            payload[key] = str(workspace / binding["path"])

    outputs_dir = workspace / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)

    # Work from the workspace, so a relative path in a parameter means the
    # same thing however the runner was started. The container already sets
    # --workdir; doing it here too keeps in-process execution identical, and
    # this process runs exactly one task before exiting, so changing global
    # state costs nothing.
    os.chdir(workspace)

    steps = spec.get("steps") or []
    for step in steps:
        name = step.get("name") or "<unnamed>"
        try:
            target = _resolve_callable(step.get("callable_ref") or {})
        except ContractViolation:
            raise
        arguments = {
            key: _resolve(value, payload) for key, value in (step.get("parameters") or {}).items()
        }
        # The existing engine passes output_dir to any function that accepts
        # it, so pipelines already rely on it being supplied.
        if "output_dir" in _accepted_arguments(target):
            arguments.setdefault("output_dir", str(outputs_dir))

        try:
            returned = target(**arguments)
        except TypeError as error:
            return _failure(
                spec,
                code="callable.signature_mismatch",
                kind="input_invalid",
                message=f"step '{name}': {error}",
                details={
                    "step": name,
                    "callable": _callable_name(step),
                    "arguments": sorted(arguments),
                    "payload": sorted(payload),
                    "traceback": traceback.format_exc(limit=5),
                },
            )
        except Exception as error:
            return _failure(
                spec,
                code=type(error).__name__,
                kind="science_error",
                message=f"step '{name}': {error}",
                details={"step": name, "traceback": traceback.format_exc(limit=20)},
            )

        payload[name] = returned
        print(f"step {name} -> {_describe(returned)}", flush=True)

        dropped = _evict(payload, [*step.get("retain", []), name])
        if dropped:
            print(f"  released {', '.join(sorted(dropped))}", flush=True)

    metrics: dict[str, float] = {}
    last = payload.get(steps[-1]["name"]) if steps else None
    if isinstance(last, dict):
        metrics = {
            key: float(value)
            for key, value in last.items()
            if isinstance(value, int | float) and not isinstance(value, bool)
        }

    return {
        "contract_version": CONTRACT_VERSION,
        "task_id": spec.get("task_id"),
        "attempt": spec.get("attempt", 1),
        "status": "succeeded",
        "outputs": _report_outputs(spec, workspace),
        "metrics": metrics,
    }


def _accepted_arguments(target: Any) -> set[str]:
    """Parameter names a callable accepts, or everything if it cannot be
    inspected (some C extensions cannot)."""
    try:
        return set(inspect.signature(target).parameters)
    except (TypeError, ValueError):
        return set()


def _callable_name(step: dict[str, Any]) -> str:
    reference = step.get("callable_ref") or {}
    return f"{reference.get('module')}.{reference.get('attribute')}"


def _failure(
    spec: dict[str, Any], *, code: str, kind: str, message: str, details: dict[str, Any]
) -> dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION,
        "task_id": spec.get("task_id"),
        "attempt": spec.get("attempt", 1),
        "status": "failed",
        "error": {"code": code, "kind": kind, "message": message, "details": details},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="BioPipeline2 task runner")
    parser.add_argument("--spec", default=os.environ.get("BP_TASK_SPEC", DEFAULT_SPEC))
    parser.add_argument("--result", default=os.environ.get("BP_RESULT_PATH", DEFAULT_RESULT))
    parser.add_argument("--workspace", default=os.environ.get("BP_WORKSPACE", "/work"))
    args = parser.parse_args(argv)

    result_path = Path(args.result)
    workspace = Path(args.workspace)

    try:
        spec = _load_spec(Path(args.spec))
    except ContractViolation as error:
        _write_result(
            result_path,
            {
                "contract_version": CONTRACT_VERSION,
                "task_id": None,
                "attempt": 1,
                "status": "failed",
                "error": {
                    "code": "contract.violation",
                    "kind": "internal",
                    "message": str(error),
                },
            },
        )
        print(f"contract violation: {error}", file=sys.stderr)
        return EXIT_CONTRACT

    try:
        result = run(spec, workspace)
    except ContractViolation as error:
        result = {
            "contract_version": CONTRACT_VERSION,
            "task_id": spec.get("task_id"),
            "attempt": spec.get("attempt", 1),
            "status": "failed",
            "error": {
                "code": "contract.violation",
                "kind": "internal",
                "message": str(error),
            },
        }
        _write_result(result_path, result)
        print(f"contract violation: {error}", file=sys.stderr)
        return EXIT_CONTRACT

    _write_result(result_path, result)
    if result["status"] == "succeeded":
        print(f"task {spec.get('task_id')} succeeded")
        return EXIT_OK
    print(f"task failed: {result['error']['message']}", file=sys.stderr)
    return EXIT_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
