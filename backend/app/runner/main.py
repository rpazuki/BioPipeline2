"""Task runner: the entry point of every task container.

Reads ``/work/.bp/task.json``, calls what it names, writes
``/work/.bp/result.json``, and exits. That is the whole contract
(ADR 0005).

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
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any

CONTRACT_VERSION = "1.0"
SUPPORTED_CONTRACT_VERSIONS = frozenset({"1.0"})

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


def run(spec: dict[str, Any], workspace: Path) -> dict[str, Any]:
    """Execute one task specification and build its result document."""
    target = _resolve_callable(spec.get("callable_ref") or {})

    arguments: dict[str, Any] = dict(spec.get("parameters") or {})
    for binding in spec.get("inputs") or []:
        key = binding.get("key")
        if not key:
            continue
        if binding.get("kind") == "value":
            arguments[key] = binding.get("value")
        else:
            # Paths are handed over as absolute paths inside the container, so
            # science code never has to know about the workspace layout.
            arguments[key] = str(workspace / binding["path"])

    outputs_dir = workspace / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)

    try:
        returned = target(**arguments)
    except TypeError as error:
        # Almost always a signature mismatch: the pipeline passes a parameter
        # the function does not accept. Worth distinguishing, because the fix
        # is in the pipeline rather than in the science code.
        return {
            "contract_version": CONTRACT_VERSION,
            "task_id": spec.get("task_id"),
            "attempt": spec.get("attempt", 1),
            "status": "failed",
            "error": {
                "code": "callable.signature_mismatch",
                "kind": "input_invalid",
                "message": str(error),
                "details": {
                    "callable": f"{spec['callable_ref']['module']}."
                    f"{spec['callable_ref']['attribute']}",
                    "arguments": sorted(arguments),
                    "traceback": traceback.format_exc(limit=5),
                },
            },
        }
    except Exception as error:
        return {
            "contract_version": CONTRACT_VERSION,
            "task_id": spec.get("task_id"),
            "attempt": spec.get("attempt", 1),
            "status": "failed",
            "error": {
                "code": type(error).__name__,
                "kind": "science_error",
                "message": str(error),
                "details": {"traceback": traceback.format_exc(limit=20)},
            },
        }

    metrics: dict[str, float] = {}
    if isinstance(returned, dict):
        metrics = {
            key: float(value)
            for key, value in returned.items()
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
